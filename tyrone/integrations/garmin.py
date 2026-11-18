"""Garmin Connect: sleep score, sleep stages, heart rate over the day, HRV, body battery, stress, steps.

Uses the community `garminconnect` library (0.3.x uses Garmin's mobile sign-in; the
older garth login stopped working in March 2026). Garmin has no official API for
individuals. Your password is used once to sign in and is never saved; the
resulting tokens live in %APPDATA%\\Tyrone\\garmin (owner-only file).
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

BUCKET_MS = 5 * 60 * 1000  # heart-rate chart resolution


def _min(sec) -> int | None:
    return round(sec / 60) if isinstance(sec, (int, float)) else None


def downsample_hr(values: list | None, bucket_ms: int = BUCKET_MS) -> list[list[int]]:
    """[[ts_ms, bpm|None], ...] -> 5-minute averages [[bucket_start_ms, bpm], ...], gaps dropped."""
    buckets: dict[int, list[int]] = {}
    for pair in values or []:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        ts, bpm = pair[0], pair[1]
        if not isinstance(ts, (int, float)) or not isinstance(bpm, (int, float)) or bpm <= 0:
            continue
        b = int(ts) // bucket_ms * bucket_ms
        buckets.setdefault(b, []).append(int(bpm))
    return [[b, round(sum(v) / len(v))] for b, v in sorted(buckets.items())]


def parse_health(day: str, sleep: dict | None, hr: dict | None, stats: dict | None, hrv: dict | None) -> dict:
    sleep, hr, stats, hrv = sleep or {}, hr or {}, stats or {}, hrv or {}
    dto = sleep.get("dailySleepDTO") or {}
    overall = (dto.get("sleepScores") or {}).get("overall") or {}
    hrv_sum = hrv.get("hrvSummary") or {}
    series = downsample_hr(hr.get("heartRateValues"))
    resting = hr.get("restingHeartRate") or sleep.get("restingHeartRate") or stats.get("restingHeartRate")
    return {
        "date": day,
        "sleep": {
            "score": overall.get("value"),
            "quality": (overall.get("qualifierKey") or "").replace("_", " ").title() or None,
            "total_min": _min(dto.get("sleepTimeSeconds")),
            "stages_min": {
                "deep": _min(dto.get("deepSleepSeconds")),
                "light": _min(dto.get("lightSleepSeconds")),
                "rem": _min(dto.get("remSleepSeconds")),
                "awake": _min(dto.get("awakeSleepSeconds")),
            },
            "start_ms": dto.get("sleepStartTimestampGMT"),
            "end_ms": dto.get("sleepEndTimestampGMT"),
            "avg_overnight_hrv": sleep.get("avgOvernightHrv"),
            "body_battery_change": sleep.get("bodyBatteryChange"),
        },
        "heart": {
            "resting": resting,
            "min": hr.get("minHeartRate") or (min((b for _, b in series), default=None)),
            "max": hr.get("maxHeartRate") or (max((b for _, b in series), default=None)),
            "seven_day_resting": hr.get("lastSevenDaysAvgRestingHeartRate"),
            "series": series,
        },
        "hrv": {"last_night": hrv_sum.get("lastNightAvg"), "weekly_avg": hrv_sum.get("weeklyAvg"),
                "status": (hrv_sum.get("status") or "").title() or None},
        "day": {
            "steps": stats.get("totalSteps"),
            "body_battery": stats.get("bodyBatteryMostRecentValue"),
            "body_battery_high": stats.get("bodyBatteryHighestValue"),
            "body_battery_low": stats.get("bodyBatteryLowestValue"),
            "stress_avg": stats.get("averageStressLevel"),
            "active_kcal": stats.get("activeKilocalories"),
        },
    }


def summarize(h: dict) -> str:
    """One compact line Tyrone can read before answering."""
    s, hrt, d = h["sleep"], h["heart"], h["day"]
    parts = []
    if s["score"] is not None:
        parts.append(f"sleep score {s['score']} ({s['quality'] or 'n/a'})")
    if s["total_min"]:
        parts.append(f"slept {s['total_min'] // 60}h{s['total_min'] % 60:02d}m")
    if hrt["resting"]:
        parts.append(f"resting HR {hrt['resting']}")
    if hrt["max"]:
        parts.append(f"max HR {hrt['max']}")
    if h["hrv"]["status"]:
        parts.append(f"HRV {h['hrv']['last_night']} ms ({h['hrv']['status']})")
    if d["body_battery"] is not None:
        parts.append(f"body battery {d['body_battery']}")
    if d["stress_avg"] is not None:
        parts.append(f"avg stress {d['stress_avg']}")
    if d["steps"] is not None:
        parts.append(f"{d['steps']} steps")
    return ", ".join(parts) or "no data for that day"


def resolve_day(when: str) -> str:
    w = (when or "today").strip().lower()
    today = date.today()
    if w in ("", "today", "now", "last night"):
        return today.isoformat()   # Garmin files last night's sleep under today's date
    if w == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    return date.fromisoformat(w).isoformat()


class GarminHealth:
    name = "garmin"

    def __init__(self, token_dir: Path):
        self.token_dir = Path(token_dir)
        self._api = None
        self._pending: tuple[Any, dict] | None = None   # (client, mfa state)
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict]] = {}

    @property
    def _token_path(self) -> str:
        return str(self.token_dir)

    def connected(self) -> bool:
        return (self.token_dir / "garmin_tokens.json").exists() or self._api is not None

    # ---- sign in -------------------------------------------------------
    def login(self, email: str, password: str) -> str:
        """Returns "ok" or "needs_mfa" (then call submit_mfa)."""
        from garminconnect import Garmin

        self.token_dir.mkdir(parents=True, exist_ok=True)
        api = Garmin(email, password, return_on_mfa=True)
        status, state = api.login()
        if status == "needs_mfa":
            self._pending = (api, state)
            return "needs_mfa"
        self._finish(api)
        return "ok"

    def submit_mfa(self, code: str) -> str:
        if not self._pending:
            raise RuntimeError("No Garmin sign-in is waiting for a code. Start again.")
        api, state = self._pending
        api.resume_login(state, code.strip())
        self._pending = None
        self._finish(api)
        return "ok"

    def _finish(self, api) -> None:
        api.client.dump(self._token_path)
        self._api = api

    def logout(self) -> None:
        self._api = None
        p = self.token_dir / "garmin_tokens.json"
        if p.exists():
            p.unlink()

    def _client(self):
        with self._lock:
            if self._api is None:
                if not self.connected():
                    raise RuntimeError("Garmin isn't connected. Sign in from Settings.")
                from garminconnect import Garmin

                api = Garmin()
                api.login(self._token_path)
                self._api = api
            return self._api

    # ---- data ----------------------------------------------------------
    def health(self, when: str = "today") -> dict:
        import time

        day = resolve_day(when)
        cached = self._cache.get(day)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        api = self._client()

        def safe(fn):
            try:
                return fn(day)
            except Exception:  # noqa: BLE001 - one missing metric shouldn't hide the rest
                return None

        out = parse_health(day, safe(api.get_sleep_data), safe(api.get_heart_rates),
                           safe(api.get_user_summary), safe(api.get_hrv_data))
        try:
            api.client.dump(self._token_path)   # keep refreshed tokens
        except Exception:  # noqa: BLE001
            pass
        self._cache[day] = (time.time(), out)
        return out


def today_str() -> str:
    return datetime.now().date().isoformat()

""""Check everything": one pass over every part of Monkey on this PC, with a fix for each problem.

Each check runs on its own (a crash or hang in one can't stop the rest). Network checks are free reads only
(list models, refresh the Google sign-in, read the Gmail profile, fetch your calendar link); nothing is sent,
bought or changed. The report never contains key values, tokens, email addresses or links, so it's safe to paste
into a chat.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
ICON = {OK: "✓", WARN: "⚠", FAIL: "✗", SKIP: "–"}
TIMEOUT_S = 20


@dataclass
class Check:
    area: str
    name: str
    status: str
    detail: str = ""
    fix: str = ""


def _scrub(text: str) -> str:
    """Belt and braces: no emails, links or long token-looking strings in the report."""
    text = str(text)
    text = re.sub(r"\{.*\}", "[data]", text, flags=re.S)                       # JSON blobs (tokens, client files)
    text = re.sub(r"[\w.+%-]+(@|%40)[\w-]+\.[\w.-]+", "[email]", text)
    text = re.sub(r"\b[a-z][a-z0-9+.-]*://\S+", "[link]", text, flags=re.I)
    text = re.sub(r"(?i)\b(token|secret|key|password)\b\s*[:=]\s*\S+", r"\1 [hidden]", text)
    text = re.sub(r"(?i)\bbearer\s+\S+", "Bearer [hidden]", text)
    text = re.sub(r"(sk-[\w-]{6,}|ya29\.[\w.-]+|1//[\w-]+|GOCSPX-[\w-]+|[A-Za-z0-9_\-.]{24,})", "[hidden]", text)
    return text[:300]


# ------------------------------------------------------------------------------------------------- checks
def _app_checks(app) -> list[Check]:
    from . import __version__

    out = [Check("App", "Version", OK, f"Monkey {__version__} on {sys.platform}")]
    up = getattr(app, "updater", None)
    if up is not None:
        st = up.state()
        newer = st.get("available") and st.get("available") != st.get("current")
        out.append(Check("App", "Updates", WARN if newer else OK,
                         f"{'update ' + str(st['available']) + ' ready' if newer else 'up to date or not checked yet'}"
                         f"; auto-update {'on' if st.get('enabled') else 'off'}",
                         "Settings → Images & updates → Check now" if newer else ""))
    data = Path(app.cfg.data_dir)
    moved = data / "last_transfer.json"
    if (data / "_incoming").exists():
        out.append(Check("App", "Move from old PC", WARN, "an import is waiting to be applied",
                         "Quit Monkey from the tray and open it again"))
    elif moved.exists():
        try:
            d = json.loads(moved.read_text(encoding="utf-8"))
            out.append(Check("App", "Move from old PC", OK,
                             f"moved in {d.get('at', '')[:10]}: {', '.join(d.get('moved', []))}; {len(d.get('keys', []))} keys"))
        except (OSError, ValueError):
            pass
    else:
        out.append(Check("App", "Move from old PC", SKIP, "no transfer file imported on this PC"))
    return out


def _brain_checks(app) -> list[Check]:
    from . import keys

    if not keys.get("anthropic"):
        return [Check("Brain", "Claude key", FAIL, "not saved", "Settings → Start here → Your Claude key")]
    client = app._ensure_client()
    try:
        page = client.models.list(limit=1)
        n = len(getattr(page, "data", []) or [])
        return [Check("Brain", "Claude key", OK, "working")]
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        fix = ("Make a new key at platform.claude.com and paste it in Settings → Start here"
               if "Authentication" in name or "401" in str(exc) else "Check your internet connection, then run the check again")
        return [Check("Brain", "Claude key", FAIL, "didn't work" if "Authentication" in name else "couldn't reach Claude", fix)]


def _voice_checks(app) -> list[Check]:
    from . import keys

    out = []
    s = app.cfg.settings
    fish = bool(keys.get("fish"))
    out.append(Check("Voice", "Fish Audio key", OK if fish else WARN, "saved" if fish else "not saved",
                     "" if fish else "Optional: Settings → Start here → Fish Audio key (without it Monkey uses his backup voice)"))
    ref = Path(app.cfg.data_dir) / "voice" / "monkey-ref.wav"
    out.append(Check("Voice", "Monkey's voice sample", OK if ref.exists() else WARN,
                     "present" if ref.exists() else "missing (the offline voice will sound generic)",
                     "" if ref.exists() else "Optional: Settings → Voice & sound → Make Monkey's voice set"))
    ov = getattr(app, "offline_voice", None)
    have_ov = bool(ov is not None and ov.available())
    out.append(Check("Voice", "Offline voice", OK if have_ov else WARN,
                     "ready" if have_ov else "not downloaded yet",
                     "" if have_ov else "Settings → Voice & sound → Backup voice → Download"))
    out.append(Check("Voice", "Loudness", OK, f"match videos/music {'on' if s.voice_match_loudness else 'off'}, "
                                              f"volume {s.voice_volume}%"))
    try:
        import sounddevice as sd

        dev = sd.query_devices(kind="output")
        out.append(Check("Voice", "Speakers", OK, f"default output: {_scrub(dev.get('name', '?'))}"))
    except Exception as exc:  # noqa: BLE001
        out.append(Check("Voice", "Speakers", FAIL, "no speakers or headphones found",
                         "Plug in or enable speakers/headphones in Windows Sound settings"))
    sp = getattr(app, "speaker", None)
    if sp is None:
        out.append(Check("Voice", "Speech engine", FAIL, "speaker not started", "Restart Monkey; if it repeats, send the report"))
    else:
        ready = []
        for e in sp.engines:
            try:
                if getattr(e, "enabled", lambda: True)() and e.available():
                    ready.append(type(e).__name__)
            except Exception:  # noqa: BLE001
                pass
        names = {"FishTTS": "Monkey's voice (Fish)", "PocketVoice": "backup voice", "SystemTTS": "Windows voice"}
        ready = [names.get(r, "a voice") for r in ready]
        out.append(Check("Voice", "Speech engine", OK if ready else FAIL,
                         f"ready: {', '.join(dict.fromkeys(ready))}" if ready else "no voice available",
                         "" if ready else "Add a Fish key or download the offline voice"))
    return out


def _listening_checks(app) -> list[Check]:
    out = []
    try:
        import sounddevice as sd

        dev = sd.query_devices(kind="input")
        out.append(Check("Listening", "Microphone", OK, f"default input: {_scrub(dev.get('name', '?'))}"))
    except Exception as exc:  # noqa: BLE001
        out.append(Check("Listening", "Microphone", FAIL, "no microphone found",
                         "Windows Settings → Privacy & security → Microphone → allow desktop apps; check the mic is enabled"))
    label = str(getattr(app, "wakeword_label", "") or "")
    bad = not label or "starting" in label or "off" in label.lower() or "fail" in label.lower()
    out.append(Check("Listening", "Wake word", WARN if bad else OK, "“Hey Monkey” is listening" if not bad else (_scrub(label) or "not running"),
                     "Restart Monkey; if it stays like this, send the report" if bad else ""))
    lst = getattr(app, "listener", None)
    if lst is None:
        out.append(Check("Listening", "Listener", FAIL, "not running", "Check the microphone, then restart Monkey"))
    else:
        out.append(Check("Listening", "Listener", WARN if lst.muted else OK, "muted" if lst.muted else "running",
                         "Tray icon → Mute microphone (untick)" if lst.muted else ""))
        out.append(Check("Listening", "Speech detection", OK if lst.vad is not None else WARN,
                         "smart speech detection on" if lst.vad is not None else "basic detection only (may cut you off more often)",
                         "" if lst.vad is not None else "Reinstall Monkey from the latest release"))
    return out


def _google_checks(app) -> list[Check]:
    from . import keys
    from .integrations.google import validate_client

    client = keys.get("google_client") or ""
    if not client and not keys.get("google_token"):
        return [Check("Google", "Gmail + Calendar", SKIP, "not set up",
                      "Optional: Settings → Accounts → Set up Google (or use a calendar link for classes)")]
    out = []
    try:
        validate_client(client)
        out.append(Check("Google", "Setup file", OK, "loaded"))
    except ValueError as exc:
        out.append(Check("Google", "Setup file", FAIL, "not loaded", "Settings → Accounts → Gmail + Google Calendar → Step 1"))
    if not keys.get("google_token"):
        out.append(Check("Google", "Sign-in", FAIL, "not signed in",
                         "Google Cloud → Audience → Publish app (or add yourself as a test user), then Settings → Accounts → Sign in"))
        return out
    try:
        prof = app.google.service("gmail", "v1").users().getProfile(userId="me").execute()
        out.append(Check("Google", "Gmail", OK, f"reads your inbox ({prof.get('messagesTotal', '?')} messages)"))
    except Exception as exc:  # noqa: BLE001
        out.append(Check("Google", "Gmail", FAIL, _scrub(exc),
                         "Enable the Gmail API in Google Cloud, or Sign in again in Settings → Accounts"))
        return out
    try:
        now = datetime.now().astimezone()
        n = len(app.gcal.list_events(now, now + timedelta(days=14)))
        out.append(Check("Google", "Calendar", OK, f"{n} events in the next 14 days"))
    except Exception as exc:  # noqa: BLE001
        out.append(Check("Google", "Calendar", FAIL, _scrub(exc), "Enable the Google Calendar API in Google Cloud"))
    return out


def _calendar_link_checks(app) -> list[Check]:
    from . import keys

    if not keys.get("calendar_ics"):
        return [Check("Calendar", "Calendar link", SKIP, "none saved", "Optional: Settings → Accounts → Calendar link")]
    try:
        now = datetime.now().astimezone()
        n = len(app.ics_calendar.list_events(now, now + timedelta(days=14)))
        return [Check("Calendar", "Calendar link", OK if n else WARN, f"{n} events in the next 14 days",
                      "" if n else "The link works but has nothing coming up: is it the right calendar?")]
    except Exception as exc:  # noqa: BLE001
        return [Check("Calendar", "Calendar link", FAIL, _scrub(exc), "Copy the secret iCal address again and re-save it")]


def _school_checks(app) -> list[Check]:
    out = []
    feed = bool(app.cfg.settings.canvas_ics_url)
    out.append(Check("Canvas", "Calendar feed", OK if feed else SKIP, "saved" if feed else "not set",
                     "" if feed else "Optional: Settings → Accounts → Canvas calendar feed"))
    tok = app.canvas_token_status()
    st = str(tok.get("status", ""))
    out.append(Check("Canvas", "Access token", OK if st == "ok" else (SKIP if st in ("none", "") else WARN),
                     _scrub(tok.get("message", st)), "" if st in ("ok", "none", "") else "Settings → API keys → Canvas token (and its expiry date in Morning brief)"))
    try:
        ol = app.outlook.available()
        out.append(Check("Outlook", "School email", OK if ol else SKIP, "connected" if ol else "not connected",
                         "" if ol else "Optional: install Microsoft 365 Apps (classic Outlook), then Settings → Accounts → Connect"))
    except Exception as exc:  # noqa: BLE001
        out.append(Check("Outlook", "School email", WARN, type(exc).__name__))
    try:
        g = app.garmin.connected()
        out.append(Check("Garmin", "Sleep + health", OK if g else SKIP, "connected" if g else "not connected"))
    except Exception as exc:  # noqa: BLE001
        out.append(Check("Garmin", "Sleep + health", WARN, type(exc).__name__))
    return out


def _memory_checks(app) -> list[Check]:
    from .memory import facts as F

    out = []
    root = Path(app.memory.memory_root)
    files = app.memory.files()
    out.append(Check("Memory", "Memory files", OK if files else FAIL, f"{len(files)} files",
                     "" if files else "Restart Monkey to recreate them"))
    real = 0
    for name in ("profile.md", "classes.md", "preferences.md", "projects.md"):
        try:
            real += len(F.parse_file(root, name))
        except Exception:  # noqa: BLE001
            pass
    out.append(Check("Memory", "About you", OK if real >= 5 else WARN, f"Monkey knows {real} thing{'' if real == 1 else 's'} about you",
                     "" if real >= 5 else "Settings → Memory → Add notes about you (or just tell Monkey things in chat)"))
    hist = getattr(app, "history", None)
    if hist is None:
        out.append(Check("Memory", "Chat history", WARN, "history is off"))
    else:
        st = hist.stats()
        out.append(Check("Memory", "Chat history", OK, f"{st['sessions']} conversations, {st['messages']} messages, "
                                                        f"search {'on' if st.get('fts') else 'basic'}"))
    return out


def _brief_checks(app, api) -> list[Check]:
    st = api.brief_status()
    out = [Check("Morning brief", "Class schedule", OK if st["verified"] else WARN,
                 f"confirmed: {', '.join(f'{d} {t}' for d, t in st['schedule'].items())}" if st["verified"] else "not confirmed",
                 "" if st["verified"] else "Settings → Morning brief → type your earliest class times → Confirm schedule")]
    out.append(Check("Morning brief", "Runs when Monkey is closed", OK if st.get("task") else SKIP,
                     "scheduled task enabled" if st.get("task") else "not enabled (brief still builds when you open Monkey)",
                     "" if st.get("task") else "Optional: Settings → Morning brief → Prepare it even when Monkey is closed → Enable"))
    return out


def _budget_checks(app) -> list[Check]:
    spent, budget = app.ledger.month_to_date(), app.cfg.settings.monthly_budget_usd
    pct = spent / budget * 100 if budget else 0
    return [Check("Budget", "This month", WARN if pct >= 90 else OK, f"${spent:.2f} of ${budget:.2f} ({pct:.0f}%)",
                  "Raise the budget in Settings → Brain & budget, or use Saver mode" if pct >= 90 else "")]


GROUPS: list[tuple[str, Callable]] = [
    ("App", _app_checks), ("Brain", _brain_checks), ("Voice", _voice_checks), ("Listening", _listening_checks),
    ("Google", _google_checks), ("Calendar", _calendar_link_checks), ("School & accounts", _school_checks),
    ("Memory", _memory_checks), ("Morning brief", None), ("Budget", _budget_checks),
]


def run_checks(app, api=None, timeout_s: float = TIMEOUT_S) -> list[Check]:
    """All groups in parallel; each one isolated. Order of the result follows GROUPS."""
    jobs = []
    pool = cf.ThreadPoolExecutor(max_workers=len(GROUPS), thread_name_prefix="health")
    for area, fn in GROUPS:
        if fn is None:
            jobs.append((area, pool.submit(_brief_checks, app, api) if api is not None else None))
        else:
            jobs.append((area, pool.submit(fn, app)))
    out: list[Check] = []
    for area, fut in jobs:
        if fut is None:
            continue
        try:
            out += fut.result(timeout=timeout_s)
        except cf.TimeoutError:
            out.append(Check(area, "Check", WARN, f"didn't answer within {timeout_s:.0f} s", "Run the check again"))
        except Exception as exc:  # noqa: BLE001
            out.append(Check(area, "Check", FAIL, f"couldn't check this ({_scrub(exc) or type(exc).__name__})",
                             "Send this report to Claude"))
    pool.shutdown(wait=False, cancel_futures=True)
    return out


def report_text(checks: list[Check]) -> str:
    from . import __version__

    counts = {k: sum(c.status == k for c in checks) for k in (OK, WARN, FAIL)}
    lines = [f"Monkey check — {datetime.now():%Y-%m-%d %H:%M} — v{__version__} — "
             f"{counts[OK]} ok, {counts[WARN]} warnings, {counts[FAIL]} problems"]
    for c in checks:
        line = f"{ICON[c.status]} {c.area} / {c.name}: {_scrub(c.detail)}"
        if c.fix and c.status in (WARN, FAIL):
            line += f"  → {_scrub(c.fix)}"
        lines.append(line)
    return "\n".join(lines)


def as_dicts(checks: list[Check]) -> list[dict]:
    return [{**asdict(c), "detail": _scrub(c.detail), "fix": c.fix} for c in checks]

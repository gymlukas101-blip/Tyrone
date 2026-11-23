"""Phone screen time: daily summaries from the owner's own phone, connected to the to-do list. Opt-in, off by default.

Neither iOS nor Android lets a Windows app read the phone's screen time directly, so the phone sends a small daily
summary and Monkey ingests it (research and setup: docs/research/PHONE_SCREEN_TIME.md):

- **Folder inbox** (iPhone: a Shortcuts automation saves a JSON file to iCloud Drive, which iCloud for Windows syncs
  to the PC; Android: Syncthing or any synced folder). Monkey reads new *.json / *.csv files in that folder.
- **Encrypted ntfy relay** (Android: Tasker posts a sealed message to a private ntfy topic; Monkey polls it, outbound
  only). Messages are AES-256-CBC + HMAC-SHA256 (encrypt-then-MAC) under a pairing key that only the PC (DPAPI,
  keys.py) and the phone hold; the relay sees random bytes. Unsealed messages on the topic are ignored.
- **Manual**: type today's total in the to-do panel, or import a JSON/CSV file.

Everything that arrives is untrusted: sizes are capped, numbers clamped, dates bounded, app names reduced to plain
short labels. Nothing in a payload is ever executed, and app names reach the model only as data from a tool that is
marked untrusted (brain/tools.py UNTRUSTED_TOOLS).

The to-do side: a daily goal shown next to today's total, goal to-dos ("Phone under 2h today", "30 min or less on
Instagram") that complete themselves or get flagged once the day is over, and a gentle suggestion when screen time
is high while important to-dos are open. This module never sends a notification: `ScreenTime.on_nudge` is the hook
a notifications feature can subscribe to (the app also emits a "screentime_nudge" UI event).
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

SCHEMA = "monkey-screentime"
MAX_RAW = 64 * 1024              # one payload / file
MAX_APPS = 30                    # apps kept per day
MAX_DAYS_PER_IMPORT = 120
NAME_MAX = 40
DAY_MIN = 24 * 60
MAX_PICKUPS = 5000
KEEP_DAYS_DEFAULT = 30
KEEP_DAYS_MAX = 400
PAIR_KEY = "screentime_pair"     # keys.py name: {"server", "topic", "key"} as JSON (DPAPI on Windows)
SEAL_PREFIX = "mst1"
_LABEL_ENC = b"monkey screentime v1 enc"
_LABEL_MAC = b"monkey screentime v1 mac"
FILE_SUFFIXES = (".json", ".csv", ".txt")
MAX_FILES_PER_SCAN = 200
NTFY_MAX_BYTES = 1024 * 1024
NTFY_MAX_MESSAGES = 200


class ScreenTimeError(ValueError):
    """A payload, file or setting that can't be used (the message is safe to show)."""


# ------------------------------------------------------------------ formatting
def fmt_min(m: int | float | None) -> str:
    """134 -> '2h 14m', 120 -> '2h', 45 -> '45m', 0 -> '0m'."""
    if m is None:
        return "?"
    m = max(0, int(round(m)))
    h, mm = divmod(m, 60)
    if h and mm:
        return f"{h}h {mm}m"
    return f"{h}h" if h else f"{mm}m"


# ------------------------------------------------------------------ untrusted text and numbers
_ALLOWED_PUNCT = set(" .&+'-_:!()/,#@")
_KNOWN_PACKAGES = {
    "com.instagram.android": "Instagram", "com.zhiliaoapp.musically": "TikTok", "com.ss.android.ugc.trill": "TikTok",
    "com.google.android.youtube": "YouTube", "com.snapchat.android": "Snapchat", "com.twitter.android": "X",
    "com.facebook.katana": "Facebook", "com.facebook.orca": "Messenger", "com.whatsapp": "WhatsApp",
    "com.reddit.frontpage": "Reddit", "com.discord": "Discord", "com.spotify.music": "Spotify",
    "com.android.chrome": "Chrome", "com.google.android.apps.messaging": "Messages", "org.telegram.messenger": "Telegram",
    "com.netflix.mediaclient": "Netflix", "com.pinterest": "Pinterest", "com.google.android.gm": "Gmail",
    "com.google.android.apps.maps": "Maps", "com.twitch.android.app": "Twitch",
}
_PKG_FILLER = {"com", "org", "net", "android", "app", "apps", "mobile", "client", "google", "www", "io", "co"}
_PKG = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+){1,8}$", re.I)


def clean_name(value: Any) -> str:
    """An app or device name from the phone -> a short plain label ('' when nothing usable is left).

    Control and formatting characters (bidi overrides, zero-width), markup and anything but letters, digits, spaces
    and a little punctuation are dropped, and it is cut to NAME_MAX characters, so a name can't smuggle layout tricks
    or long instructions into the UI or the model's context."""
    if not isinstance(value, str):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        else:
            return ""
    s = unicodedata.normalize("NFKC", value[:400])
    if _PKG.match(s.strip()) and "." in s:
        pkg = s.strip().lower()
        if pkg in _KNOWN_PACKAGES:
            return _KNOWN_PACKAGES[pkg]
        parts = [p for p in pkg.split(".") if p not in _PKG_FILLER] or pkg.split(".")
        s = max(parts, key=len).replace("_", " ").title()
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "N") or ch in _ALLOWED_PUNCT:
            out.append(ch)
        elif cat[0] == "Z" or ch in "\t\n\r":
            out.append(" ")
    s = " ".join("".join(out).split())
    return s[:NAME_MAX].strip()


_DUR_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s|ms|milliseconds?)\b", re.I)


def parse_duration(value: Any, unit: str = "min") -> int | None:
    """Minutes from a number (in `unit`: min | s | ms) or a phrase: '2h 14m', '2 hours, 14 minutes', '134 min',
    '1:02' (h:mm), '1:02:03' (h:mm:ss), '45s'. None when it isn't a duration. Never negative; not clamped here."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if not math.isfinite(v) or v < 0:
            return None
        v = v / 60 if unit == "s" else v / 60000 if unit == "ms" else v
        return int(round(v))
    if not isinstance(value, str):
        return None
    s = value.strip().lower()[:60]
    if not s:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return parse_duration(float(s), unit)
    m = re.fullmatch(r"(\d{1,2}):([0-5]\d)(?::([0-5]\d))?", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)) + (1 if m.group(3) and int(m.group(3)) >= 30 else 0)
    parts = _DUR_PART.findall(s)
    if not parts:
        return None
    rest = _DUR_PART.sub("", s)
    if re.search(r"[a-z0-9]", re.sub(r"\band\b", "", rest)):
        return None                     # "2h of TikTok" style junk: not a clean duration
    total = 0.0
    for num, u in parts:
        n = float(num)
        u = u.lower()
        if u in ("ms", "millisecond", "milliseconds"):
            total += n / 60000
        elif u.startswith("h"):
            total += n * 60
        elif u.startswith("s"):
            total += n / 60
        else:
            total += n
    return int(round(total)) if math.isfinite(total) else None


def _int_in(value: Any, lo: int, hi: int) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v < lo or v > hi:
        return None
    return int(round(v))


# ------------------------------------------------------------------ payloads
@dataclass
class DaySummary:
    day: str                                  # YYYY-MM-DD (the phone's local day)
    total_min: int
    pickups: int | None = None
    apps: list[dict] = field(default_factory=list)   # [{"name": str, "minutes": int}], most first
    device: str = ""
    platform: str = ""                        # ios | android | ""
    source: str = "manual"                    # folder | ntfy | manual | import
    as_of: float | None = None                # when the phone measured it (epoch seconds)
    estimated: bool = False                   # total = sum of apps (the phone sent no total)

    def as_dict(self) -> dict:
        return {"day": self.day, "total_min": self.total_min, "pickups": self.pickups, "apps": self.apps,
                "device": self.device, "platform": self.platform, "source": self.source, "as_of": self.as_of,
                "estimated": self.estimated}


_TOTAL_KEYS = (("total_minutes", "min"), ("total_min", "min"), ("minutes", "min"), ("total", "min"),
               ("screen_time", "min"), ("screentime", "min"), ("total_seconds", "s"), ("total_ms", "ms"))
_APP_TIME_KEYS = (("minutes", "min"), ("min", "min"), ("duration", "min"), ("time", "min"), ("usage", "min"),
                  ("seconds", "s"), ("secs", "s"), ("ms", "ms"), ("millis", "ms"), ("total_ms", "ms"))
_APP_NAME_KEYS = ("name", "app", "label", "title", "package", "bundle_id")
_APP_LINE = re.compile(r"^\s*(?:[-*•]\s*)?(.{1,120}?)\s*(?:[:=\t,–—|]|\s-\s|\s)\s*"
                       r"((?:\d+(?:\.\d+)?\s*(?:hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b[\s,]*(?:and\s+)?)+|"
                       r"\d{1,2}:[0-5]\d(?::[0-5]\d)?|\d+(?:\.\d+)?)\s*$", re.I)


def _parse_day(value: Any, today: date) -> date:
    if isinstance(value, str):
        v = value.strip().lower()[:40]
        if v in ("today", ""):
            return today
        if v == "yesterday":
            return today - timedelta(days=1)
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
    raise ScreenTimeError("the date must look like 2026-11-23")


def parse_apps(value: Any) -> list[dict]:
    """Apps from a list of objects, a {name: duration} object, or text lines ('Instagram: 1h 2m'). Untrusted."""
    found: list[tuple[str, int]] = []
    if isinstance(value, str):
        for line in value[:MAX_RAW].splitlines()[:300]:
            m = _APP_LINE.match(line)
            if not m:
                continue
            mins = parse_duration(m.group(2).strip().rstrip(","))
            name = clean_name(m.group(1))
            if name and mins is not None:
                found.append((name, mins))
    elif isinstance(value, dict):
        for k, v in list(value.items())[:300]:
            mins = parse_duration(v)
            name = clean_name(k)
            if name and mins is not None:
                found.append((name, mins))
    elif isinstance(value, list):
        for it in value[:300]:
            if isinstance(it, str):
                found.extend((a["name"], a["minutes"]) for a in parse_apps(it))
                continue
            if not isinstance(it, dict):
                continue
            name = next((clean_name(it[k]) for k in _APP_NAME_KEYS if k in it and clean_name(it[k])), "")
            mins = next((parse_duration(it[k], u) for k, u in _APP_TIME_KEYS if k in it
                         and parse_duration(it[k], u) is not None), None)
            if name and mins is not None:
                found.append((name, mins))
    merged: dict[str, list] = {}
    for name, mins in found:
        key = name.casefold()
        if mins > DAY_MIN:
            continue                    # more than a day in one app: junk
        if key in merged:
            merged[key][1] = min(DAY_MIN, merged[key][1] + mins)
        else:
            merged[key] = [name, mins]
    apps = [{"name": n, "minutes": m} for n, m in merged.values() if m > 0]
    apps.sort(key=lambda a: (-a["minutes"], a["name"].casefold()))
    return apps[:MAX_APPS]


def parse_payload(obj: Any, *, today: date, keep_days: int = KEEP_DAYS_DEFAULT, source: str = "import") -> DaySummary:
    """One day's summary from a decoded JSON object. Raises ScreenTimeError with a short reason."""
    if not isinstance(obj, dict):
        raise ScreenTimeError("expected a JSON object for one day")
    schema = obj.get("schema")
    if schema is not None and schema != SCHEMA:
        raise ScreenTimeError("not a Monkey screen-time payload")
    d = _parse_day(obj.get("date", obj.get("day", "")), today)
    if d > today + timedelta(days=1):
        raise ScreenTimeError("that date is in the future")
    if d <= today - timedelta(days=max(1, keep_days)):
        raise ScreenTimeError(f"that date is older than the {keep_days} days Monkey keeps")
    total: int | None = None
    for k, unit in _TOTAL_KEYS:
        if k in obj:
            total = parse_duration(obj[k], unit)
            if total is None:
                raise ScreenTimeError(f"couldn't read {k!r} as a duration")
            break
    apps: list[dict] = []
    for k in ("apps", "top_apps", "apps_text", "usage"):
        if k in obj:
            apps = parse_apps(obj[k])
            if apps:
                break
    estimated = False
    if total is None:
        if not apps:
            raise ScreenTimeError("no total screen time and no apps in it")
        total = sum(a["minutes"] for a in apps)
        estimated = True
    if total > DAY_MIN:
        if estimated:
            total = DAY_MIN
        else:
            raise ScreenTimeError("more than 24 hours in one day")
    for a in apps:
        a["minutes"] = min(a["minutes"], total) if not estimated else a["minutes"]
    pickups = None
    for k in ("pickups", "unlocks", "pick_ups"):
        if k in obj:
            pickups = _int_in(obj[k], 0, MAX_PICKUPS)
            break
    platform = str(obj.get("platform", "")).strip().lower()[:10]
    platform = {"iphone": "ios", "ios": "ios", "ipados": "ios", "android": "android"}.get(platform, "")
    as_of = None
    raw_as_of = obj.get("as_of", obj.get("time"))
    if isinstance(raw_as_of, (int, float)) and not isinstance(raw_as_of, bool) and math.isfinite(raw_as_of):
        as_of = float(raw_as_of) / (1000 if raw_as_of > 1e11 else 1)
    elif isinstance(raw_as_of, str) and raw_as_of.strip():
        try:
            dt = datetime.fromisoformat(raw_as_of.strip()[:40].replace("Z", "+00:00"))
            as_of = dt.timestamp()
        except ValueError:
            as_of = None
    if as_of is not None and not (0 < as_of < time.time() + 2 * 86400):
        as_of = None
    return DaySummary(d.isoformat(), int(total), pickups, apps, clean_name(obj.get("device", "")),
                      platform, source, as_of, estimated)


def _csv_rows(text: str) -> list[dict]:
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader][:2000]
    if not rows:
        return []
    head = [h.strip().lower().replace(" ", "_") for h in rows[0]]
    return [dict(zip(head, r)) for r in rows[1:] if any(c.strip() for c in r)]


def parse_text(text: str, *, today: date, keep_days: int = KEEP_DAYS_DEFAULT, source: str = "import",
               opener: Callable[[str], bytes] | None = None) -> list[DaySummary]:
    """A file or message body -> day summaries. JSON (one day, a list, or {"days": [...]}), CSV (date,total_minutes
    [,pickups] per row, or date,app,minutes rows), or a sealed 'mst1.' message when `opener` can open it."""
    if len(text.encode("utf-8", "replace")) > MAX_RAW:
        raise ScreenTimeError("too big for a screen-time summary")
    s = text.lstrip("﻿").strip()
    if not s:
        raise ScreenTimeError("empty")
    if s.startswith(SEAL_PREFIX + "."):
        if opener is None:
            raise ScreenTimeError("this message is encrypted and Monkey isn't paired with the phone")
        return parse_text(opener(s).decode("utf-8", "replace"), today=today, keep_days=keep_days, source=source)
    if s[0] in "[{":
        try:
            obj = json.loads(s)
        except ValueError as exc:
            raise ScreenTimeError(f"not valid JSON ({exc.msg})") from None
        if isinstance(obj, dict) and isinstance(obj.get("days"), list):
            obj = obj["days"]
        items = obj if isinstance(obj, list) else [obj]
        if len(items) > MAX_DAYS_PER_IMPORT:
            raise ScreenTimeError(f"more than {MAX_DAYS_PER_IMPORT} days in one file")
        out, errors = [], []
        for it in items:
            try:
                out.append(parse_payload(it, today=today, keep_days=keep_days, source=source))
            except ScreenTimeError as exc:
                errors.append(str(exc))
        if not out:
            raise ScreenTimeError(errors[0] if errors else "nothing usable in it")
        return out
    rows = _csv_rows(s)
    if not rows or "date" not in rows[0] and "day" not in rows[0]:
        raise ScreenTimeError("expected JSON, or CSV with a 'date' column")
    if any(k in rows[0] for k in ("app", "name", "package")):         # long format: one row per app
        by_day: dict[str, dict] = {}
        for r in rows:
            d = r.get("date") or r.get("day") or ""
            entry = by_day.setdefault(d, {"date": d, "apps": [], "device": r.get("device", "")})
            name = r.get("app") or r.get("name") or r.get("package") or ""
            mins = r.get("minutes") or r.get("duration") or r.get("time") or ""
            if name.strip().lower() in ("total", "all", "screen time"):
                entry["total_minutes"] = mins
            else:
                entry["apps"].append({"name": name, "minutes": mins})
        items = list(by_day.values())
    else:
        items = [{**r, "date": r.get("date") or r.get("day") or ""} for r in rows]
    if len(items) > MAX_DAYS_PER_IMPORT:
        raise ScreenTimeError(f"more than {MAX_DAYS_PER_IMPORT} days in one file")
    out, errors = [], []
    for it in items:
        for k in ("total_minutes", "minutes", "total", "pickups"):
            if it.get(k, None) == "":
                it.pop(k)
        try:
            out.append(parse_payload(it, today=today, keep_days=keep_days, source=source))
        except ScreenTimeError as exc:
            errors.append(str(exc))
    if not out:
        raise ScreenTimeError(errors[0] if errors else "nothing usable in it")
    return out


# ------------------------------------------------------------------ pairing and sealed messages (encrypt-then-MAC)
def new_pairing(server: str = "https://ntfy.sh") -> dict:
    """A fresh private topic and a 256-bit key. The key only goes to the owner's phone (shown on the PC's screen)."""
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    topic = "monkey-st-" + "".join(secrets.choice(alphabet) for _ in range(24))
    return {"server": normalize_server(server), "topic": topic, "key": secrets.token_hex(32)}


def pairing_uri(p: dict) -> str:
    """What the phone stores (one Tasker variable, or the QR code): '<server>/<topic>#<hex key>'. The part after
    '#' is never sent anywhere by the phone: it's split off before the request."""
    return f"{p['server'].rstrip('/')}/{p['topic']}#{p['key']}"


def _keys(key_hex: str) -> tuple[bytes, bytes]:
    try:
        master = bytes.fromhex(key_hex)
    except (ValueError, TypeError):
        raise ScreenTimeError("bad pairing key") from None
    if len(master) != 32:
        raise ScreenTimeError("bad pairing key")
    return (hmac.new(master, _LABEL_ENC, hashlib.sha256).digest(),
            hmac.new(master, _LABEL_MAC, hashlib.sha256).digest())


def seal(plaintext: bytes, key_hex: str, iv: bytes | None = None) -> str:
    """'mst1.<iv b64>.<ciphertext b64>.<mac b64>': AES-256-CBC/PKCS7, then HMAC-SHA256 over 'mst1.<iv>.<ct>'.
    The phone side (Tasker + CryptoJS) does the same; see docs/research/PHONE_SCREEN_TIME.md."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    k_enc, k_mac = _keys(key_hex)
    iv = iv or os.urandom(16)
    padder = padding.PKCS7(128).padder()
    data = padder.update(plaintext) + padder.finalize()
    enc = Cipher(algorithms.AES(k_enc), modes.CBC(iv)).encryptor()
    ct = enc.update(data) + enc.finalize()
    head = f"{SEAL_PREFIX}.{base64.b64encode(iv).decode()}.{base64.b64encode(ct).decode()}"
    mac = hmac.new(k_mac, head.encode(), hashlib.sha256).digest()
    return f"{head}.{base64.b64encode(mac).decode()}"


def open_sealed(message: str, key_hex: str) -> bytes:
    """Verify, then decrypt. Raises ScreenTimeError for anything that isn't a valid message under this key."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    s = (message or "").strip()
    if len(s) > 2 * MAX_RAW:
        raise ScreenTimeError("message too big")
    parts = s.split(".")
    if len(parts) != 4 or parts[0] != SEAL_PREFIX:
        raise ScreenTimeError("not a sealed screen-time message")
    k_enc, k_mac = _keys(key_hex)
    try:
        iv = base64.b64decode(parts[1], validate=True)
        ct = base64.b64decode(parts[2], validate=True)
        mac = base64.b64decode(parts[3], validate=True)
    except (ValueError, TypeError):
        raise ScreenTimeError("not a sealed screen-time message") from None
    want = hmac.new(k_mac, f"{parts[0]}.{parts[1]}.{parts[2]}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(mac, want):
        raise ScreenTimeError("message isn't from your paired phone (wrong key or tampered)")
    if len(iv) != 16 or not ct or len(ct) % 16:
        raise ScreenTimeError("malformed sealed message")
    dec = Cipher(algorithms.AES(k_enc), modes.CBC(iv)).decryptor()
    data = dec.update(ct) + dec.finalize()
    unpad = padding.PKCS7(128).unpadder()
    try:
        return unpad.update(data) + unpad.finalize()
    except ValueError:
        raise ScreenTimeError("malformed sealed message") from None


def normalize_server(url: str) -> str:
    """An ntfy server base URL. https only (http just for this PC itself, e.g. a self-hosted relay in testing)."""
    u = (url or "").strip().rstrip("/") or "https://ntfy.sh"
    m = re.fullmatch(r"(https?)://([a-z0-9.-]{1,253}|\[[0-9a-f:]+\])(?::(\d{1,5}))?(/[A-Za-z0-9._~/-]{0,100})?", u, re.I)
    if not m or ".." in u:
        raise ScreenTimeError("the relay address must look like https://ntfy.sh")
    if m.group(1).lower() == "http" and m.group(2).lower() not in ("localhost", "127.0.0.1", "[::1]"):
        raise ScreenTimeError("use https for the relay")
    return u


_TOPIC = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def poll_ntfy(server: str, topic: str, since: str = "", *, http_get: Callable | None = None) -> list[dict]:
    """Cached messages on the topic (outbound HTTPS GET only; the PC never listens). Returns [{"id", "time",
    "message"}] for plain message events, capped in count and size."""
    server = normalize_server(server)
    if not _TOPIC.match(topic or ""):
        raise ScreenTimeError("bad topic")
    since = since if re.fullmatch(r"[A-Za-z0-9]{1,32}|\d{1,3}h", since or "") else "48h"
    url = f"{server}/{topic}/json"
    params = {"poll": "1", "since": since}
    if http_get is None:
        import httpx

        def http_get(u, p):          # noqa: E306 - streamed so a flooded topic can't eat memory
            out = b""
            with httpx.stream("GET", u, params=p, timeout=15.0, follow_redirects=False) as r:
                r.raise_for_status()
                for chunk in r.iter_bytes():
                    out += chunk
                    if len(out) > NTFY_MAX_BYTES:
                        break
            return out.decode("utf-8", "replace")
    body = http_get(url, params)
    msgs = []
    for line in body.splitlines()[:NTFY_MAX_MESSAGES * 2]:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("event") != "message" or "attachment" in ev:
            continue
        mid, msg = ev.get("id"), ev.get("message")
        if not isinstance(mid, str) or not re.fullmatch(r"[A-Za-z0-9]{1,32}", mid) or not isinstance(msg, str):
            continue
        if len(msg) > 2 * MAX_RAW:
            continue
        msgs.append({"id": mid, "time": ev.get("time") if isinstance(ev.get("time"), (int, float)) else None,
                     "message": msg})
        if len(msgs) >= NTFY_MAX_MESSAGES:
            break
    return msgs


# ------------------------------------------------------------------ storage (monkey.db)
class ScreenTimeStore:
    """Daily summaries, goal to-dos and what has been read already. One row per day (one phone)."""

    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS screentime_days(day TEXT PRIMARY KEY, total_min INTEGER NOT NULL,"
                      " pickups INTEGER, apps TEXT NOT NULL DEFAULT '[]', device TEXT NOT NULL DEFAULT '',"
                      " platform TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'manual', as_of REAL,"
                      " estimated INTEGER NOT NULL DEFAULT 0, received REAL)")
            c.execute("CREATE TABLE IF NOT EXISTS screentime_goals(id TEXT PRIMARY KEY, todo_id TEXT, kind TEXT NOT NULL,"
                      " app TEXT NOT NULL DEFAULT '', limit_min INTEGER NOT NULL, day TEXT NOT NULL,"
                      " repeat INTEGER NOT NULL DEFAULT 0, series TEXT NOT NULL DEFAULT '',"
                      " status TEXT NOT NULL DEFAULT 'pending', note TEXT NOT NULL DEFAULT '', created REAL, evaluated REAL,"
                      " apps TEXT NOT NULL DEFAULT '[]', label TEXT NOT NULL DEFAULT '')")
            have = {r[1] for r in c.execute("PRAGMA table_info(screentime_goals)")}
            for col in ("apps TEXT NOT NULL DEFAULT '[]'", "label TEXT NOT NULL DEFAULT ''"):   # app-group goals
                if col.split()[0] not in have:
                    c.execute(f"ALTER TABLE screentime_goals ADD COLUMN {col}")
            c.execute("CREATE TABLE IF NOT EXISTS screentime_seen(key TEXT PRIMARY KEY, ts REAL)")
            c.execute("CREATE TABLE IF NOT EXISTS screentime_meta(k TEXT PRIMARY KEY, v TEXT)")

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    # ---- days
    @staticmethod
    def _day(r: sqlite3.Row | None) -> dict | None:
        if r is None:
            return None
        d = dict(r)
        try:
            d["apps"] = [a for a in json.loads(d.get("apps") or "[]") if isinstance(a, dict)]
        except ValueError:
            d["apps"] = []
        d["estimated"] = bool(d.get("estimated"))
        return d

    def upsert(self, s: DaySummary) -> tuple[bool, dict]:
        """Save a day. A later automatic reading only replaces a bigger-or-equal one (totals only grow during a
        day, so an old message replayed or arriving late can't roll it back); a manual entry always replaces."""
        with self._lock, self._conn() as c:
            cur = self._day(c.execute("SELECT * FROM screentime_days WHERE day=?", (s.day,)).fetchone())
            if cur is not None and s.source not in ("manual", "import") and s.total_min < cur["total_min"]:
                return False, cur
            c.execute("INSERT OR REPLACE INTO screentime_days(day, total_min, pickups, apps, device, platform, source,"
                      " as_of, estimated, received) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (s.day, s.total_min, s.pickups, json.dumps(s.apps), s.device, s.platform, s.source, s.as_of,
                       int(s.estimated), time.time()))
        return True, self.get(s.day)  # type: ignore[return-value]

    def get(self, day: str) -> dict | None:
        with self._conn() as c:
            return self._day(c.execute("SELECT * FROM screentime_days WHERE day=?", (day,)).fetchone())

    def recent(self, n: int = 7, until: str | None = None) -> list[dict]:
        q = "SELECT * FROM screentime_days" + (" WHERE day<=?" if until else "") + " ORDER BY day DESC LIMIT ?"
        with self._conn() as c:
            rows = c.execute(q, ((until, n) if until else (n,))).fetchall()
        return [self._day(r) for r in rows]  # type: ignore[misc]

    def count(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM screentime_days").fetchone()[0])

    def purge(self, keep_days: int, today: date) -> int:
        cutoff = (today - timedelta(days=max(1, keep_days) - 1)).isoformat()
        with self._lock, self._conn() as c:
            n = c.execute("DELETE FROM screentime_days WHERE day<?", (cutoff,)).rowcount
            c.execute("DELETE FROM screentime_seen WHERE ts<?", (time.time() - 2 * max(1, keep_days) * 86400,))
            c.execute("DELETE FROM screentime_goals WHERE day<? AND status!='pending'",
                      ((today - timedelta(days=max(1, keep_days) - 1)).isoformat(),))
        return n

    def forget(self) -> None:
        """Delete all usage data (goal to-dos stay: they're the owner's to-dos)."""
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM screentime_days")
            c.execute("DELETE FROM screentime_seen")
            c.execute("DELETE FROM screentime_meta")

    # ---- seen (files and relay messages already read)
    def seen(self, key: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM screentime_seen WHERE key=?", (key,)).fetchone() is not None

    def mark_seen(self, key: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO screentime_seen(key, ts) VALUES (?,?)", (key, time.time()))

    def meta(self, k: str, v: str | None = None) -> str | None:
        with self._lock, self._conn() as c:
            if v is not None:
                c.execute("INSERT OR REPLACE INTO screentime_meta(k, v) VALUES (?,?)", (k, v))
                return v
            r = c.execute("SELECT v FROM screentime_meta WHERE k=?", (k,)).fetchone()
            return r[0] if r else None

    # ---- goals
    def add_goal(self, todo_id: str, kind: str, limit_min: int, day: str, app: str = "", repeat: bool = False,
                 series: str = "", apps: list[str] | None = None, label: str = "") -> dict:
        gid = uuid.uuid4().hex[:8]
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO screentime_goals(id, todo_id, kind, app, limit_min, day, repeat, series, status,"
                      " created, apps, label) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (gid, todo_id, kind, app, int(limit_min), day, int(repeat), series or gid, "pending", time.time(),
                       json.dumps(list(apps or [])), label))
        return self.goal(gid)  # type: ignore[return-value]

    @staticmethod
    def _goal(r: sqlite3.Row) -> dict:
        d = dict(r)
        try:
            d["apps"] = [a for a in json.loads(d.get("apps") or "[]") if isinstance(a, str)]
        except ValueError:
            d["apps"] = []
        return d

    def goal(self, gid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM screentime_goals WHERE id=?", (gid,)).fetchone()
        return self._goal(r) if r else None

    def goals(self, status: str | None = None) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM screentime_goals" + (" WHERE status=?" if status else "")
                             + " ORDER BY day DESC, created DESC", ((status,) if status else ())).fetchall()
        return [self._goal(r) for r in rows]

    def set_goal(self, gid: str, **changes) -> None:
        keep = {k: v for k, v in changes.items() if k in ("status", "note", "evaluated", "repeat", "todo_id")}
        if not keep:
            return
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE screentime_goals SET {', '.join(k + '=?' for k in keep)} WHERE id=?",
                      (*keep.values(), gid))


# ------------------------------------------------------------------ the feature
def goal_text(kind: str, limit_min: int, app: str = "", label: str = "") -> str:
    """The goal to-do's text. A repeating goal makes one of these per day, so it always says "today"."""
    if kind == "app":
        return f"{fmt_min(limit_min)} or less on {app} today"
    if kind == "group":
        return f"{label or 'Those'} apps under {fmt_min(limit_min)} today"
    return f"Phone under {fmt_min(limit_min)} today"


# Other names the same app shows up under (Screen Time lists websites too, e.g. youtube.com in Safari).
APP_ALIASES = {"yt": "youtube", "youtubemusic": "youtube", "ig": "instagram", "insta": "instagram",
               "tiktoklite": "tiktok", "musically": "tiktok", "twitter": "x"}
_WEB_SUFFIXES = ("com", "net", "org", "tv", "app")


def app_key(name: str) -> str:
    """'YouTube', 'YT', 'youtube.com', 'www.youtube.com', 'You Tube' -> 'youtube'. Case-insensitive."""
    s = clean_name(name).casefold()
    parts = [p for p in re.split(r"[.\s]+", s) if p]
    if "." in s and len(parts) >= 2 and parts[-1] in _WEB_SUFFIXES:           # a website: drop www./m. and the suffix
        parts = [p for p in parts[:-1] if p not in ("www", "m")]
    k = re.sub(r"[^0-9a-z\u00c0-\uffff]", "", "".join(parts))
    return APP_ALIASES.get(k, k)


SUGGESTED_GROUP = {"label": "Social", "apps": ["TikTok", "Instagram", "YouTube"], "limit_min": 180}


def default_folder(platform: str) -> str:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return str(home / ("iCloudDrive" if platform != "android" else "Sync") / "Monkey")


class ScreenTime:
    """The app-level service: reads from the chosen transport, stores, evaluates goal to-dos, computes the gentle
    suggestion. All settings come from `settings()` (config.Settings) each time, so Settings changes apply at once."""

    FOLDER_EVERY_S = 120
    NTFY_EVERY_S = 20 * 60

    def __init__(self, store: ScreenTimeStore, todos: Any, settings: Callable[[], Any], *,
                 secret_get: Callable[[str], str | None], secret_set: Callable[[str, str], None],
                 secret_delete: Callable[[str], None], emit: Callable[[str, dict], None] | None = None,
                 http_get: Callable | None = None):
        self.store, self.todos, self._settings = store, todos, settings
        self._sget, self._sset, self._sdel = secret_get, secret_set, secret_delete
        self._emit = emit or (lambda n, p: None)
        self._http_get = http_get
        self._last_folder = 0.0
        self._last_ntfy = 0.0
        self._lock = threading.Lock()
        self.last_error = ""
        self.on_nudge: list[Callable[[dict], None]] = []   # hook for a notifications feature (none here)

    # ---- settings
    @property
    def st(self):
        return self._settings()

    def enabled(self) -> bool:
        return bool(getattr(self.st, "screentime_enabled", False))

    def keep_days(self) -> int:
        try:
            return max(1, min(KEEP_DAYS_MAX, int(getattr(self.st, "screentime_keep_days", KEEP_DAYS_DEFAULT))))
        except (TypeError, ValueError):
            return KEEP_DAYS_DEFAULT

    def goal_min(self) -> int:
        try:
            return max(0, min(DAY_MIN, int(getattr(self.st, "screentime_goal_min", 0) or 0)))
        except (TypeError, ValueError):
            return 0

    def platform(self) -> str:
        p = str(getattr(self.st, "screentime_platform", "") or "")
        return p if p in ("iphone", "android") else "iphone"        # the owner's phone is an iPhone

    def transport(self) -> str:
        t = str(getattr(self.st, "screentime_transport", "") or "")
        if t in ("folder", "ntfy", "manual"):
            return t
        return "ntfy" if self.platform() == "android" else "folder"

    def folder(self) -> str:
        return str(getattr(self.st, "screentime_folder", "") or "") or default_folder(self.platform())

    # ---- pairing (ntfy)
    def relay_server(self) -> str:
        """This feature's relay, else the one phone reminders use (`ntfy_server`, feature/todo-notifications), else
        ntfy.sh. Only the address is shared: screen time has its own topic and key."""
        return (getattr(self.st, "screentime_ntfy_server", "") or getattr(self.st, "ntfy_server", "")
                or "https://ntfy.sh")

    def pairing(self) -> dict | None:
        raw = self._sget(PAIR_KEY)
        if not raw:
            return None
        try:
            p = json.loads(raw)
            _keys(p["key"])
            if not _TOPIC.match(p["topic"]):
                return None
            p["server"] = normalize_server(p.get("server", "https://ntfy.sh"))
            return p
        except (ValueError, KeyError, TypeError, ScreenTimeError):
            return None

    def pair(self, server: str | None = None) -> dict:
        """A new topic + key (replaces the old pairing: the phone needs the new one)."""
        p = new_pairing(server or self.relay_server())
        self._sset(PAIR_KEY, json.dumps(p))
        self.store.meta("ntfy_since", "")
        return p

    def unpair(self) -> None:
        self._sdel(PAIR_KEY)
        self.store.meta("ntfy_since", "")

    def _opener(self) -> Callable[[str], bytes] | None:
        p = self.pairing()
        return (lambda s: open_sealed(s, p["key"])) if p else None

    # ---- ingest
    def ingest_text(self, text: str, source: str, today: date | None = None) -> list[dict]:
        today = today or date.today()
        out = []
        for s in parse_text(text, today=today, keep_days=self.keep_days(), source=source, opener=self._opener()):
            saved, row = self.store.upsert(s)
            out.append({"saved": saved, **row})
        if any(r["saved"] for r in out):
            self.store.meta("last_received", json.dumps({"ts": time.time(), "source": source}))
            self._emit("screentime", {"action": "updated"})
        return out

    def manual(self, total: Any, day: str = "today", pickups: Any = None, today: date | None = None,
               top_app: Any = "", top_app_time: Any = "") -> dict:
        """What the owner reads off the phone's Screen Time page: today's total, and optionally the top app and its
        time (the iPhone's Screen Time can't be exported, so this is the zero-setup path)."""
        today = today or date.today()
        mins = parse_duration(total)
        if mins is None:
            raise ScreenTimeError("type it like 2h 15m or 135")
        obj: dict = {"date": day or "today", "total_minutes": mins, "device": "typed in Monkey"}
        if pickups not in (None, ""):
            obj["pickups"] = pickups
        s = parse_payload(obj, today=today, keep_days=self.keep_days(), source="manual")
        if pickups not in (None, "") and s.pickups is None:
            raise ScreenTimeError("pickups must be a number from 0 to 5000")
        cur = self.store.get(s.day)
        if cur and cur.get("apps"):
            s.apps = [a for a in cur["apps"] if a["minutes"] <= s.total_min]   # keep the phone's per-app detail
        name = clean_name(top_app) if top_app not in (None, "") else ""
        if top_app not in (None, "") and not name:
            raise ScreenTimeError("type the app's name, like Instagram")
        if name:
            am = parse_duration(top_app_time)
            if am is None:
                raise ScreenTimeError(f"how long on {name}? Type it like 45m")
            if am > s.total_min:
                raise ScreenTimeError(f"{name} can't be more than the total")
            s.apps = [a for a in s.apps if a["name"].casefold() != name.casefold()] + [{"name": name, "minutes": am}]
            s.apps.sort(key=lambda a: (-a["minutes"], a["name"].casefold()))
        _, row = self.store.upsert(s)
        self._emit("screentime", {"action": "updated"})
        return row

    def scan_folder(self, today: date | None = None) -> dict:
        folder = Path(self.folder())
        if not folder.is_dir():
            raise ScreenTimeError(f"folder not found yet: {folder}. Finish the phone setup in Settings → Phone, or switch "
                                  "to typing it in")
        files = [p for p in folder.iterdir() if p.suffix.lower() in FILE_SUFFIXES and p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        read = skipped = 0
        errors = []
        for p in files[:MAX_FILES_PER_SCAN]:
            st = p.stat()
            key = f"file:{p.name}:{st.st_size}:{st.st_mtime_ns}"
            if self.store.seen(key):
                continue
            self.store.mark_seen(key)
            if st.st_size > MAX_RAW:
                errors.append(f"{p.name}: too big")
                continue
            try:
                got = self.ingest_text(p.read_text(encoding="utf-8", errors="replace"), "folder", today)
                read += sum(1 for g in got if g["saved"])
                skipped += sum(1 for g in got if not g["saved"])
            except (ScreenTimeError, OSError) as exc:
                errors.append(f"{p.name}: {exc}")
        if errors:
            self.last_error = errors[0]
        return {"read": read, "skipped": skipped, "errors": errors[:5]}

    def poll_relay(self, today: date | None = None) -> dict:
        p = self.pairing()
        if p is None:
            raise ScreenTimeError("not paired: click Pair phone in Settings → Phone")
        msgs = poll_ntfy(p["server"], p["topic"], self.store.meta("ntfy_since") or "", http_get=self._http_get)
        read = 0
        errors = []
        for m in msgs:
            key = "ntfy:" + m["id"]
            if self.store.seen(key):
                continue
            self.store.mark_seen(key)
            if not m["message"].strip().startswith(SEAL_PREFIX + "."):
                errors.append("ignored a message that wasn't encrypted with your pairing key")
                continue
            try:
                read += sum(1 for g in self.ingest_text(m["message"], "ntfy", today) if g["saved"])
            except ScreenTimeError as exc:
                errors.append(str(exc))
        if msgs:
            self.store.meta("ntfy_since", msgs[-1]["id"])
        if errors:
            self.last_error = errors[0]
        return {"read": read, "messages": len(msgs), "errors": errors[:5]}

    def check_now(self, today: date | None = None) -> dict:
        """Read from the chosen transport right away (the Settings button)."""
        t = self.transport()
        try:
            if t == "folder":
                r = self.scan_folder(today)
            elif t == "ntfy":
                r = self.poll_relay(today)
            else:
                return {"ok": True, "read": 0, "note": "Manual mode: type today's total in the To-do panel."}
            self.last_error = r["errors"][0] if r["errors"] else ""
            return {"ok": True, **r}
        except Exception as exc:  # noqa: BLE001 - network, disk: say what happened
            msg = str(exc)
            p = self.pairing()
            if p:
                msg = msg.replace(p["topic"], "<topic>")        # the topic stays out of the status line
            self.last_error = msg[:200]
            return {"ok": False, "error": self.last_error}

    # ---- periodic work (app thread)
    def tick(self, now: datetime | None = None) -> None:
        if not self.enabled():
            return
        now = now or datetime.now()
        mono = time.monotonic()
        t = self.transport()
        if t == "folder" and mono - self._last_folder >= self.FOLDER_EVERY_S:
            self._last_folder = mono
            self.check_now(now.date())
        elif t == "ntfy" and mono - self._last_ntfy >= self.NTFY_EVERY_S:
            self._last_ntfy = mono
            self.check_now(now.date())
        self.store.purge(self.keep_days(), now.date())
        self.evaluate_goals(now)
        self.nudge(now)

    # ---- goal to-dos
    def add_goal(self, kind: str, limit: Any, app: str = "", repeat: bool = False, now: datetime | None = None,
                 apps: Any = None, label: str = "") -> dict:
        """kind total (whole phone), app (one app) or group (several apps added up, e.g. TikTok + Instagram +
        YouTube). For a group, `apps` is a list or a comma-separated string (`app` works too)."""
        now = now or datetime.now()
        if kind not in ("total", "app", "group"):
            raise ScreenTimeError("goal kind must be total, app or group")
        mins = parse_duration(limit)
        if mins is None or not 1 <= mins <= DAY_MIN:
            raise ScreenTimeError("the limit must be between 1 minute and 24 hours, like 2h or 30m")
        names: list[str] = []
        if kind == "group":
            raw = apps if apps is not None else app
            items = raw.split(",") if isinstance(raw, str) else list(raw or []) if isinstance(raw, (list, tuple)) else []
            seen: set[str] = set()
            for x in items[:20]:
                n = clean_name(x)
                if n and app_key(n) and app_key(n) not in seen:
                    seen.add(app_key(n))
                    names.append(n)
            if len(names) < 2:
                raise ScreenTimeError("a group needs at least two apps, like TikTok, Instagram, YouTube")
            names = names[:10]
            label = clean_name(label)[:20] or "Chosen"
            app = ""
        else:
            label = ""
            app = clean_name(app) if kind == "app" else ""
            if kind == "app" and not app:
                raise ScreenTimeError("which app?")
        return self._make_goal(kind, mins, app, bool(repeat), now.date(), "", names, label)

    def _make_goal(self, kind: str, mins: int, app: str, repeat: bool, day: date, series: str,
                   apps: list[str] | None = None, label: str = "") -> dict:
        notes = "Checks itself off from your phone's screen time after the day ends."
        if kind == "group":
            notes = f"Counts {', '.join(apps or [])} together. " + notes
        item = self.todos.add(goal_text(kind, mins, app, label), due=day.isoformat(), list="phone", notes=notes,
                              source="Monkey", now=datetime.combine(day, datetime.min.time()))
        g = self.store.add_goal(item["id"], kind, mins, day.isoformat(), app, repeat, series, apps, label)
        self._emit("todo_changed", {"action": "added_goal", "item": item})
        return {**g, "todo": item}

    def goal_usage(self, g: dict) -> int | None:
        """Minutes used against the goal on its day, None when there's no data (or no per-app detail). App names
        match case-insensitively and by alias (YT = YouTube, IG = Instagram, youtube.com = YouTube)."""
        row = self.store.get(g["day"])
        if row is None:
            return None
        if g["kind"] == "total":
            return int(row["total_min"])
        if not row["apps"]:
            return None
        want = {app_key(a) for a in (g.get("apps") or [])} if g["kind"] == "group" else {app_key(g["app"])}
        return min(DAY_MIN, sum(a["minutes"] for a in row["apps"] if app_key(a["name"]) in want))

    @staticmethod
    def _goal_what(g: dict) -> str:
        if g["kind"] == "app":
            return g["app"]
        if g["kind"] == "group":
            return f"{', '.join(g.get('apps') or [])}"
        return "your phone"

    def evaluate_goals(self, now: datetime | None = None) -> list[dict]:
        """Pending goal to-dos: met -> checked off; over -> flagged in the note (during the day already, final once
        the day is over). Repeating goals get today's to-do. Returns what changed."""
        now = now or datetime.now()
        today = now.date()
        changed = []
        for g in self.store.goals("pending"):
            item = self.todos.get(g["todo_id"]) if g["todo_id"] else None
            if item is None:                       # the owner deleted the to-do: the goal (and its series) ends
                self.store.set_goal(g["id"], status="dropped", evaluated=time.time())
                self.stop_goal(g["id"])
                continue
            day = date.fromisoformat(g["day"])
            used = self.goal_usage(g)
            limit = int(g["limit_min"])
            row = self.store.get(g["day"])
            # final once the day is over and either the phone reported after midnight or it's mid-morning by now
            settled = day < today and (row is not None and (row.get("received") or 0) >= datetime.combine(
                day + timedelta(days=1), datetime.min.time()).timestamp() or now >= datetime.combine(
                day + timedelta(days=1), datetime.min.time()) + timedelta(hours=10))
            what = self._goal_what(g)
            if used is not None and used > limit:
                note = f"Over: {fmt_min(used)} on {what} (goal {fmt_min(limit)})."
                if note != g["note"]:
                    self.todos.update(item["id"], notes=note)
                    self.store.set_goal(g["id"], note=note)
                    changed.append({"goal": g["id"], "result": "over"})
                    self._emit("todo_changed", {"action": "updated", "item": self.todos.get(item["id"])})
                if settled:
                    self.store.set_goal(g["id"], status="missed", evaluated=time.time())
                    changed.append({"goal": g["id"], "result": "missed"})
            elif settled and used is not None:
                note = f"Made it: {fmt_min(used)} on {what} (goal {fmt_min(limit)})."
                self.todos.update(item["id"], notes=note)
                done = item if item["status"] == "done" else self.todos.complete(item["id"])
                self.store.set_goal(g["id"], status="met", note=note, evaluated=time.time())
                changed.append({"goal": g["id"], "result": "met"})
                self._emit("todo_changed", {"action": "done", "item": done})
            elif day < today - timedelta(days=2) and used is None:
                note = "No screen-time data came in for that day."
                self.todos.update(item["id"], notes=note)
                self.store.set_goal(g["id"], status="nodata", note=note, evaluated=time.time())
                changed.append({"goal": g["id"], "result": "nodata"})
        # repeating goals: one to-do per day, until the owner deletes one (or stops it)
        latest: dict[str, dict] = {}
        for g in self.store.goals():
            cur = latest.get(g["series"])
            if cur is None or g["day"] > cur["day"]:
                latest[g["series"]] = g
        for series, g in latest.items():
            if g["day"] < today.isoformat() and g["repeat"] and g["status"] != "dropped":
                self._make_goal(g["kind"], int(g["limit_min"]), g["app"], True, today, series, g.get("apps"),
                                g.get("label") or "")
                changed.append({"goal": series, "result": "repeated"})
        return changed

    def stop_goal(self, gid: str) -> None:
        g = self.store.goal(gid)
        if g is None:
            raise ScreenTimeError("that goal is gone")
        for x in self.store.goals():
            if x["series"] == g["series"]:
                self.store.set_goal(x["id"], repeat=0)

    def active_goals(self, today: date) -> list[dict]:
        """Today's goal to-dos and older ones still waiting for their day's final numbers."""
        out = []
        for g in self.store.goals():
            if g["day"] != today.isoformat() and not (g["status"] == "pending" and g["day"] < today.isoformat()):
                continue
            out.append({"id": g["id"], "todo_id": g["todo_id"], "kind": g["kind"], "app": g["app"],
                        "apps": g.get("apps") or [], "label": g.get("label") or "",
                        "limit_min": g["limit_min"], "day": g["day"], "repeat": bool(g["repeat"]),
                        "status": g["status"], "used_min": self.goal_usage(g),
                        "text": goal_text(g["kind"], g["limit_min"], g["app"], g.get("label") or "")})
        return out[:10]

    # ---- the suggested app group (offered, never created on its own)
    def suggested_group(self) -> dict | None:
        """"Social: TikTok, Instagram, YouTube ≤ 3h", until the owner accepts or dismisses it."""
        if self.store.meta("group_suggestion") in ("accepted", "dismissed"):
            return None
        want = {app_key(a) for a in SUGGESTED_GROUP["apps"]}
        for g in self.store.goals():
            if g["kind"] == "group" and {app_key(a) for a in g.get("apps") or []} == want and (
                    g["repeat"] or g["status"] == "pending"):
                return None
        s = SUGGESTED_GROUP
        today = {"kind": "group", "apps": s["apps"], "app": "", "day": date.today().isoformat()}
        return {**s, "text": f"{s['label']}: {', '.join(s['apps'])} ≤ {fmt_min(s['limit_min'])}",
                "todo_text": goal_text("group", s["limit_min"], label=s["label"]), "used_min": self.goal_usage(today)}

    def accept_suggested_group(self, now: datetime | None = None) -> dict:
        """One click: the suggested group as a daily goal to-do ("Social apps under 3h today", every day)."""
        s = SUGGESTED_GROUP
        g = self.add_goal("group", s["limit_min"], apps=s["apps"], label=s["label"], repeat=True, now=now)
        self.store.meta("group_suggestion", "accepted")
        return g

    def dismiss_suggested_group(self) -> None:
        self.store.meta("group_suggestion", "dismissed")

    # ---- the gentle suggestion
    def _important_open(self, now: datetime) -> list[dict]:
        goal_ids = {g["todo_id"] for g in self.store.goals()}
        items = [t for t in self.todos.items("open", now) if t["id"] not in goal_ids]
        return [t for t in items if t.get("overdue") or t.get("priority") == "high"
                or (t.get("due") and t["due"][:10] == now.date().isoformat())]

    def suggestion(self, now: datetime | None = None) -> dict | None:
        """{text, total_min, goal_min, todo} when today's screen time is past the goal (or 3h without one) and an
        important to-do (overdue, due today, high priority) is still open. Never a notification by itself."""
        if not self.enabled():
            return None
        now = now or datetime.now()
        row = self.store.get(now.date().isoformat())
        if row is None:
            return None
        goal = self.goal_min()
        threshold = goal or 180
        if row["total_min"] < threshold:
            return None
        todo = next(iter(self._important_open(now)), None)
        if todo is None:
            return None
        text = (f"You've been on your phone {fmt_min(row['total_min'])} today"
                + (f" (goal {fmt_min(goal)})" if goal else "")
                + f", and “{todo['text']}” is still open. Maybe park the phone and knock it out?")
        return {"text": text, "total_min": row["total_min"], "goal_min": goal,
                "todo": {"id": todo["id"], "text": todo["text"]}}

    def nudge(self, now: datetime | None = None) -> dict | None:
        """At most once a day: emit 'screentime_nudge' and call the on_nudge hooks (for a notifications feature)."""
        if not getattr(self.st, "screentime_nudges", True):
            return None
        now = now or datetime.now()
        s = self.suggestion(now)
        if s is None or self.store.meta("nudged_day") == now.date().isoformat():
            return None
        self.store.meta("nudged_day", now.date().isoformat())
        self._emit("screentime_nudge", s)
        for fn in list(self.on_nudge):
            try:
                fn(s)
            except Exception:  # noqa: BLE001 - a subscriber must not break the tick
                log.warning("screen-time nudge hook failed", exc_info=True)
        return s

    # ---- views
    def summary(self, day: str = "today", now: datetime | None = None) -> dict:
        """For the brain tool and the morning brief: one day, or 'week' (the last 7 days)."""
        now = now or datetime.now()
        today = now.date()
        goal = self.goal_min()
        if (day or "").strip().lower() == "week":
            rows = [r for r in self.store.recent(7, today.isoformat()) if r["day"] > (today - timedelta(days=7)).isoformat()]
            if not rows:
                return {"days": [], "note": "No screen-time data for the last 7 days yet."}
            avg = sum(r["total_min"] for r in rows) / len(rows)
            return {"days": [{"date": r["day"], "total": fmt_min(r["total_min"]), "total_minutes": r["total_min"]}
                             for r in rows],
                    "average": fmt_min(avg), "goal": fmt_min(goal) if goal else "none",
                    "days_over_goal": sum(1 for r in rows if goal and r["total_min"] > goal)}
        try:
            d = _parse_day(day or "today", today)
        except ScreenTimeError:
            return {"error": "day must be today, yesterday, week or YYYY-MM-DD"}
        row = self.store.get(d.isoformat())
        if row is None:
            return {"date": d.isoformat(), "note": "No screen-time data for that day yet."}
        out: dict = {"date": row["day"], "total": fmt_min(row["total_min"]), "total_minutes": row["total_min"],
                     "top_apps": [{"app": a["name"], "minutes": a["minutes"]} for a in row["apps"][:5]],
                     "updated": datetime.fromtimestamp(row["received"]).strftime("%a %I:%M %p").replace(" 0", " ")
                     if row.get("received") else "", "source": row["source"]}
        if row["pickups"] is not None:
            out["pickups"] = row["pickups"]
        if row["estimated"]:
            out["note"] = "Total is the sum of the apps the phone listed."
        if goal:
            diff = row["total_min"] - goal
            out["goal"] = fmt_min(goal)
            out["vs_goal"] = f"{fmt_min(abs(diff))} {'over' if diff > 0 else 'under'}" if diff else "right at it"
        goals = [g for g in self.store.goals() if g["day"] == row["day"] and g["status"] != "dropped"]
        if goals:
            out["goals"] = [{"goal": goal_text(g["kind"], g["limit_min"], g["app"], g.get("label") or "")
                             + (f" ({', '.join(g['apps'])})" if g["kind"] == "group" else ""),
                             "used": fmt_min(u) if (u := self.goal_usage(g)) is not None else "no per-app data",
                             "limit": fmt_min(g["limit_min"])} for g in goals[:5]]
        return out

    def status(self) -> dict:
        p = self.pairing()
        lr = self.store.meta("last_received")
        try:
            last = json.loads(lr) if lr else None
        except ValueError:
            last = None
        folder = self.folder()
        return {"enabled": self.enabled(), "platform": self.platform(), "transport": self.transport(),
                "folder": folder, "folder_exists": Path(folder).is_dir(), "paired": p is not None,
                "server": p["server"] if p else self.relay_server(),
                "topic": p["topic"] if p else "", "last_received": last, "last_error": self.last_error,
                "days": self.store.count(), "goal_min": self.goal_min(), "keep_days": self.keep_days(),
                "in_brief": bool(getattr(self.st, "screentime_in_brief", True)),
                "nudges": bool(getattr(self.st, "screentime_nudges", True))}

    def panel(self, now: datetime | None = None) -> dict:
        """What the to-do panel's widget shows."""
        now = now or datetime.now()
        today = now.date()
        if not self.enabled():
            return {"enabled": False}
        week = self.store.recent(7, today.isoformat())
        return {"enabled": True, "goal_min": self.goal_min(), "today": self.store.get(today.isoformat()),
                "yesterday": self.store.get((today - timedelta(days=1)).isoformat()),
                "week": [{"day": r["day"], "total_min": r["total_min"]} for r in week],
                "goals": self.active_goals(today), "suggestion": self.suggestion(now),
                "suggested_group": self.suggested_group(), "status": self.status()}

    def brief_line(self, now: datetime | None = None) -> str | None:
        """Yesterday, for the morning brief (None when off or no data)."""
        if not self.enabled() or not getattr(self.st, "screentime_in_brief", True):
            return None
        now = now or datetime.now()
        row = self.store.get((now.date() - timedelta(days=1)).isoformat())
        if row is None:
            return None
        goal = self.goal_min()
        line = f"Phone yesterday: {fmt_min(row['total_min'])}"
        if goal:
            diff = row["total_min"] - goal
            line += f" (goal {fmt_min(goal)}, {fmt_min(abs(diff))} {'over' if diff > 0 else 'under'})" if diff else \
                f" (right at your {fmt_min(goal)} goal)"
        if row["apps"]:
            line += f"; most on {row['apps'][0]['name']} ({fmt_min(row['apps'][0]['minutes'])})"
        return line + "."

    def forget(self) -> None:
        self.store.forget()
        self.last_error = ""
        self._emit("screentime", {"action": "forgotten"})


# ------------------------------------------------------------------ setup steps (shown in Settings → Phone)
TASKER_JS = """// Monkey screen time (runs in Tasker's JavaScriptlet; Libraries: crypto-js 4.2.0)
var pair = global('MONKEY_PAIR');              // <server>/<topic>#<key>, from Monkey's Settings → Phone
var cut = pair.indexOf('#');
var url = pair.slice(0, cut), key = CryptoJS.enc.Hex.parse(pair.slice(cut + 1));
var names = typeof app_name !== 'undefined' ? app_name : [];   // App Info outputs (step 1)
var times = typeof app_time !== 'undefined' ? app_time : [];
var apps = [], total = 0;
for (var i = 0; i < names.length && i < 30; i++) {
  var m = Math.round(Number(times[i]) / 60000);         // milliseconds -> minutes
  if (m > 0) { apps.push({name: names[i], minutes: m}); total += m; }
}
var d = new Date(), p = function (n) { return (n < 10 ? '0' : '') + n; };
var body = JSON.stringify({schema: 'monkey-screentime', v: 1, platform: 'android', device: 'Android phone',
  date: d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()), as_of: Math.floor(d.getTime() / 1000),
  total_minutes: Math.min(total, 1440), pickups: Number(global('MONKEY_PICKUPS')) || undefined, apps: apps});
var kEnc = CryptoJS.HmacSHA256('monkey screentime v1 enc', key);
var kMac = CryptoJS.HmacSHA256('monkey screentime v1 mac', key);
var iv = CryptoJS.lib.WordArray.random(16);
var ct = CryptoJS.AES.encrypt(body, kEnc, {iv: iv, mode: CryptoJS.mode.CBC, padding: CryptoJS.pad.Pkcs7}).ciphertext;
var head = 'mst1.' + CryptoJS.enc.Base64.stringify(iv) + '.' + CryptoJS.enc.Base64.stringify(ct);
var sealed = head + '.' + CryptoJS.enc.Base64.stringify(CryptoJS.HmacSHA256(head, kMac));
setLocal('st_url', url);
setLocal('st_body', sealed);
"""
CRYPTOJS_URL = "https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.2.0/crypto-js.min.js"


def setup_steps(platform: str, transport: str, folder: str = "", pairing: dict | None = None) -> list[str]:
    """Plain steps for the owner's chosen path (Settings → Phone shows these; the research doc has the why)."""
    if transport == "manual":
        return ["On the phone, open Settings → Screen Time (iPhone) or Settings → Digital Wellbeing (Android) and look "
                "at today's total and the top app.",
                "In Monkey's To-do panel, open the phone card's \"Type today's total\" and enter them (like 2h 15m, "
                "Instagram 45m). It takes about 10 seconds; do it in the evening for the goal to-dos.",
                "Or import a JSON/CSV file here (date,total_minutes per row)."]
    if platform == "iphone":
        return [
            "On the PC: install iCloud for Windows (Microsoft Store), sign in with your Apple Account and turn on iCloud Drive.",
            "On the iPhone (iOS 26 or later): in the Files app, make a folder named Monkey in iCloud Drive.",
            "Open Shortcuts → Automation → + → Time of Day → 9:00 PM, Daily → Run Immediately → New Blank Automation.",
            "Add the action Screen Time → Get App & Website Data, set to Today.",
            "Add Text and put the result of Get App & Website Data in it (this is the per-app list).",
            "Add Dictionary with: schema = monkey-screentime, v = 1, platform = ios, device = iPhone, "
            "date = Current Date (Format Date → Custom: yyyy-MM-dd), apps_text = the Text above. "
            "If the action also gives a total, add total = that value (like 2h 14m or a number of minutes).",
            "Add Set Name → name: screentime-<the date>.json (use the formatted date), then Save File → "
            "iCloud Drive/Monkey, Ask Where to Save off, Overwrite If File Exists on.",
            "Run it once by hand and allow Screen Time access when asked. Make two copies of the automation for "
            "midday and 11:55 PM so the to-do panel stays current.",
            f"Monkey reads new files in: {folder or default_folder('iphone')}. Click Check now to test.",
            "No Screen Time action in Shortcuts (iOS 25 or earlier), or it doesn't work: choose \"I'll type it in\" "
            "and enter the total and top app from Settings → Screen Time in the To-do panel.",
        ]
    if transport == "folder":
        return [
            "Install Syncthing on the PC and Syncthing-Fork on the phone (free, phone-to-PC, encrypted, no cloud).",
            f"Share a phone folder named Monkey with the PC and point it at: {folder or default_folder('android')}.",
            "In Tasker, build the task from the ntfy steps but replace the last two steps with Write File → "
            "Monkey/screentime-%DATE.json (the JSON before encryption, or the sealed text: both work).",
            "Click Check now here to test.",
        ]
    pair_txt = pairing_uri(pairing) if pairing else "(click Pair phone first)"
    return [
        "Install Tasker on the phone (Google Play). In Android Settings → Apps → Special app access → Usage access, allow Tasker.",
        f"In Tasker → Vars, add a global variable MONKEY_PAIR = {pair_txt} (scan the QR code with the phone camera "
        "and copy the text). Keep it private: it's the key.",
        "New Task 'Monkey screen time'. Step 1: App → App Info, Get: most used apps, Time span: today "
        "(check the action's output variables; the script expects %app_name() and %app_time() in milliseconds; "
        "rename them in the script if yours differ).",
        f"Step 2: Code → JavaScriptlet, Libraries: {CRYPTOJS_URL}, Code: the script below (Copy script).",
        "Step 3: Net → HTTP Request, Method POST, URL %st_url, Body %st_body, Timeout 30.",
        "Profile: Time from 08:00 to 23:59, repeat every 1 hour → Monkey screen time. (Optional pickups: a "
        "Display Unlocked profile that adds 1 to %MONKEY_PICKUPS, and a midnight profile that sets it to 0.)",
        "Run the task once, then click Check now here. Monkey polls the relay every 20 minutes; the relay keeps "
        "messages about 12 hours, so the next hourly run fills any gap.",
    ]

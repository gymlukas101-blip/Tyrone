"""The user's own to-do list: things they need to do, stored in monkey.db (never in memory files or the repo).

Due dates are local wall-clock strings: "YYYY-MM-DD" (a day) or "YYYY-MM-DDTHH:MM" (a time). One PC, one user, so
local time is what "tomorrow 5pm" means, and the UI (ui/src/todoparse.ts) reads the same strings with `new Date`.

`split_quick` turns a typed or spoken phrase ("call the dentist tomorrow 5pm !high #health") into text, due,
priority and list. It is best effort: the UI shows what it understood so the user can correct it, and the brain
tools say which date they saved. tests/todo_due_cases.json holds the shared cases the TypeScript port must match.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

PRIORITIES = ("low", "normal", "high")
SOURCES = ("typed", "voice", "Monkey")
PRIO_RANK = {"high": 0, "normal": 1, "low": 2}
DELETED_KEEP_S = 30 * 86400          # deleted items stay restorable (Undo) this long, then they're purged

COLUMNS: dict[str, str] = {           # name -> type/default; new columns are added to old databases on open
    "id": "TEXT PRIMARY KEY",
    "text": "TEXT NOT NULL",
    "notes": "TEXT NOT NULL DEFAULT ''",
    "due": "TEXT",                     # "YYYY-MM-DD" | "YYYY-MM-DDTHH:MM" | NULL
    "priority": "TEXT NOT NULL DEFAULT 'normal'",
    "list": "TEXT NOT NULL DEFAULT ''",
    "status": "TEXT NOT NULL DEFAULT 'open'",
    "steps": "TEXT NOT NULL DEFAULT '[]'",   # JSON [{"text": .., "done": bool}]
    "source": "TEXT NOT NULL DEFAULT 'typed'",
    "created": "REAL",
    "updated": "REAL",
    "done_at": "REAL",
    "deleted_at": "REAL",
    "reminded_for": "TEXT NOT NULL DEFAULT ''",   # the due string the in-app reminder already fired for
    "snooze_until": "REAL",
}


# ------------------------------------------------------------------ due-date parsing
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WD_FULL = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
# Short forms ("sat", "sun", "wed") are ordinary words too, so they only count after next/this/on/by: "by fri".
_WD_SHORT = r"(?:mon|tues?|weds?|thu(?:rs?)?|fri|sat|sun)"
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_PART = {"morning": 9, "afternoon": 15, "evening": 18, "night": 20, "tonight": 20}
_LEAD = r"(?:(?:\bby|\bat|\bon|\bdue|\bbefore|\buntil|@)\s+)?"


@dataclass
class Quick:
    text: str
    due: str | None = None
    priority: str = "normal"
    list: str = ""


def _wd_index(tok: str) -> int:
    return next(i for i, n in enumerate(WEEKDAYS) if n.startswith(tok.lower()[:3]))


def _hour(h: int, m: int, ap: str, bare: bool) -> tuple[int, int] | None:
    """12h/24h clock to (hour, minute). bare = "at 5" with no am/pm: 1-7 means the afternoon/evening."""
    ap = (ap or "").lower().replace(".", "")
    if m > 59:
        return None
    if ap.startswith("a"):
        if not 1 <= h <= 12:
            return None
        return (0 if h == 12 else h), m
    if ap.startswith("p"):
        if not 1 <= h <= 12:
            return None
        return (12 if h == 12 else h + 12), m
    if bare and 1 <= h <= 7:
        return h + 12, m
    return (h, m) if 0 <= h <= 23 else None


def split_quick(phrase: str, now: datetime) -> Quick:
    """'call the dentist tomorrow at 5pm !high #health' -> Quick('call the dentist', '2026-11-24T17:00', 'high',
    'health'). `now` is local wall-clock time (naive or aware: only its date and time are used)."""
    now = _naive(now)
    s = " " + " ".join((phrase or "").split()) + " "
    today = now.date()
    day: date | None = None
    hm: tuple[int, int] | None = None
    exact: datetime | None = None            # "in 2 hours": a full point in time
    prio, lst = "normal", ""

    def cut(m: re.Match) -> None:
        nonlocal s
        s = s[:m.start()] + " " + s[m.end():]

    def find(pattern: str) -> re.Match | None:
        return re.search(pattern, s, re.I)

    # priority and list markers (typed shorthand)
    m = find(r"(?<!\S)(?:!high|!h|!!!?|!urgent)(?!\S)|\b(?:high|top) priority\b")
    if m:
        prio = "high"
        cut(m)
    m = find(r"(?<!\S)(?:!low|!l)(?!\S)|\blow priority\b")
    if m:
        prio = "low"
        cut(m)
    m = find(r"(?<!\S)#([\w-]{1,30})(?!\S)")
    if m:
        lst = m.group(1).lower()
        cut(m)

    # ISO date (+ optional time) e.g. 2026-12-01, 2026-12-01T17:00, 2026-12-01 5pm
    m = find(_LEAD + r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\b")
    if m:
        try:
            day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if m.group(4):
                hm = (int(m.group(4)), int(m.group(5)))
            cut(m)
        except ValueError:
            day = None
    # relative offsets: "in 2 hours", "in 30 min", "in an hour", "in half an hour", "in 3 days", "in a week"
    if day is None:
        m = find(r"\bin\s+(half an|an|a|\d{1,3})\s*(minutes?|mins?|hours?|hrs?|h|days?|weeks?|wks?)\b")
        if m:
            n_txt, unit = m.group(1).lower(), m.group(2).lower()
            n = 0.5 if n_txt == "half an" else 1 if n_txt in ("a", "an") else int(n_txt)
            if unit.startswith("m"):
                exact = now + timedelta(minutes=n)
            elif unit.startswith("h"):
                exact = now + timedelta(hours=n)
            elif unit.startswith("d"):
                day = today + timedelta(days=int(n))
            else:
                day = today + timedelta(weeks=int(n))
            cut(m)
    if day is None and exact is None:
        m = find(_LEAD + r"\b(today|tonight|this (?:morning|afternoon|evening))\b")
        if m:
            day = today
            word = m.group(1).lower().split()[-1]
            if word in _PART:
                hm = (_PART[word], 0)
            cut(m)
    if day is None and exact is None:
        m = find(_LEAD + r"\b(?:tomorrow|tmrw?|tomorow|tmw)(?:\s+(morning|afternoon|evening|night))?\b")
        if m:
            day = today + timedelta(days=1)
            if m.group(1):
                hm = (_PART[m.group(1).lower()], 0)
            cut(m)
    if day is None and exact is None:
        m = find(r"\b(?:next week)\b")
        if m:
            day = today + timedelta(days=7 - today.weekday())
            cut(m)
    if day is None and exact is None:
        m = find(_LEAD + r"\b(?:this weekend|the weekend)\b")
        if m:
            day = today + timedelta(days=(5 - today.weekday()) % 7)
            cut(m)
    if day is None and exact is None:
        m = find(_LEAD + r"\b(?:the )?end of (?:the |this )?week\b")
        if m:
            day = today + timedelta(days=(4 - today.weekday()) % 7)
            cut(m)
    if day is None and exact is None:
        m = (find(_LEAD + r"\b(next|this|on)?\s*\b(" + _WD_FULL + r")\b(?:\s+(morning|afternoon|evening|night))?")
             or find(r"\b(next|this|on|by|due|before|until)\s+(" + _WD_SHORT + r")\b\.?(?:\s+(morning|afternoon|evening|night))?"))
        if m:
            idx = _wd_index(m.group(2))
            ahead = (idx - today.weekday()) % 7
            if (m.group(1) or "").lower() == "next":
                monday_next = today + timedelta(days=7 - today.weekday())
                day = monday_next + timedelta(days=idx)
            else:
                day = today + timedelta(days=ahead)
            if m.group(3):
                hm = (_PART[m.group(3).lower()], 0)
            cut(m)
    if day is None and exact is None:
        # "dec 5", "December 5th, 2026", "5 dec", "the 5th of december"
        m = (find(_LEAD + r"\b(" + _MON + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b")
             or find(_LEAD + r"\b(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + _MON + r")\b(?:,?\s+(\d{4}))?"))
        if m:
            g = m.groups()
            mon_tok, d_tok = (g[0], g[1]) if not g[0].isdigit() else (g[1], g[0])
            mon = MONTHS.index(mon_tok.lower()[:3]) + 1
            year = int(g[2]) if g[2] else today.year
            try:
                day = date(year, mon, int(d_tok))
                if not g[2] and day < today:
                    day = date(year + 1, mon, int(d_tok))
                cut(m)
            except ValueError:
                day = None
    if day is None and exact is None:
        m = find(_LEAD + r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)\b")          # "on the 1st": the next one coming
        if m and 1 <= int(m.group(1)) <= 31:
            want, y, mo = int(m.group(1)), today.year, today.month
            if want < today.day:
                y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
            for _ in range(3):                                              # skip months without a 31st
                try:
                    day = date(y, mo, want)
                    break
                except ValueError:
                    y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
            if day is not None:
                cut(m)
    if day is None and exact is None:
        m = find(_LEAD + r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?(?![\d/])")
        if m:
            year = int(m.group(3)) if m.group(3) else today.year
            year += 2000 if year < 100 else 0
            try:
                day = date(year, int(m.group(1)), int(m.group(2)))
                if not m.group(3) and day < today:
                    day = date(year + 1, int(m.group(1)), int(m.group(2)))
                cut(m)
            except ValueError:
                day = None

    # time of day
    if exact is None and hm is None:
        m = find(_LEAD + r"\b(noon|midday|midnight)\b")
        if m:
            hm = (12, 0) if m.group(1).lower() != "midnight" else (23, 59)
            cut(m)
    if exact is None and hm is None:
        m = find(_LEAD + r"\b(\d{1,2})(?::(\d{2}))?(?:\s*([ap]\.?m\b\.?)|([ap]))(?![\w])")
        if m:
            hm = _hour(int(m.group(1)), int(m.group(2) or 0), m.group(3) or m.group(4), False)
            if hm:
                cut(m)
    if exact is None and hm is None:
        m = find(r"\b(?:at|by|@|before)\s+(\d{1,2})(?::(\d{2}))?\b(?!\s*(?:%|percent|pages?|min|hours?|days?))")
        if m:
            hm = _hour(int(m.group(1)), int(m.group(2) or 0), "", True)
            if hm:
                cut(m)
    if exact is None and hm is None:
        m = find(_LEAD + r"(?<![\d:/.])\b([01]?\d|2[0-3]):([0-5]\d)\b")
        if m:
            h24 = m.group(1).startswith("0") or int(m.group(1)) >= 13      # "07:30", "17:00" are 24-hour times
            hm = _hour(int(m.group(1)), int(m.group(2)), "", not h24)
            cut(m)
    if exact is None and hm is None and day is not None:
        m = find(_LEAD + r"\b(?:in the )?(morning|afternoon|evening|night)\b")
        if m:
            hm = (_PART[m.group(1).lower()], 0)
            cut(m)

    due: str | None = None
    if exact is not None:
        due = exact.strftime("%Y-%m-%dT%H:%M")
    elif day is not None or hm is not None:
        if day is None:                      # a time alone: the next time it comes round
            day = today if (hm[0], hm[1]) > (now.hour, now.minute) else today + timedelta(days=1)
        due = day.isoformat() + (f"T{hm[0]:02d}:{hm[1]:02d}" if hm else "")

    text = " ".join(s.split())
    text = re.sub(r"(?:\s*\b(?:by|at|on|due|before|until)\b|\s*@)+\s*$", "", text, flags=re.I)
    text = re.sub(r"^\s*(?:remind me to|i need to|i have to|i gotta|need to|todo:?|to-do:?)\s+", "", text, flags=re.I)
    text = text.strip(" ,;:-–—").strip()
    return Quick(text, due, prio, lst)


def normalize_due(value: str | None, now: datetime) -> str | None:
    """Anything the model or UI sends ("", "none", "2026-11-24", "2026-11-24T17:00:00-06:00", "friday 3pm") ->
    a stored due string or None. Raises ValueError when it can't be understood."""
    v = (value or "").strip()
    if not v or v.lower() in ("none", "null", "no", "clear", "no date", "remove"):
        return None
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?", v)
    if m:
        if m.group(3):                      # an absolute time with an offset: shown in this PC's local time
            dt = datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone()
            return dt.strftime("%Y-%m-%dT%H:%M")
        date.fromisoformat(m.group(1))       # validates
        return m.group(1) + (f"T{m.group(2)}" if m.group(2) else "")
    q = split_quick(v, now)
    if q.due is None:
        raise ValueError(f"couldn't understand the due date {v!r}; use YYYY-MM-DD or YYYY-MM-DDTHH:MM")
    return q.due


def due_datetime(due: str | None) -> datetime | None:
    """The moment something is due (a day-only item is due at the end of that day). Naive local time."""
    if not due:
        return None
    try:
        if "T" in due:
            return datetime.fromisoformat(due)
        return datetime.combine(date.fromisoformat(due), datetime.max.time()).replace(microsecond=0)
    except ValueError:
        return None


def is_overdue(item: dict, now: datetime) -> bool:
    if item.get("status") != "open":
        return False
    d = due_datetime(item.get("due"))
    return d is not None and d < _naive(now)


def _naive(now: datetime) -> datetime:
    return now.astimezone().replace(tzinfo=None) if now.tzinfo else now


def when_text(due: str | None, now: datetime) -> str:
    """'today 5:00 PM', 'tomorrow', 'Fri Nov 27', 'overdue since Mon 9:00 AM' (for speaking and short lists)."""
    d = due_datetime(due)
    if d is None:
        return "no due date"
    n = _naive(now)
    days = (d.date() - n.date()).days
    label = "today" if days == 0 else "tomorrow" if days == 1 else "yesterday" if days == -1 else (
        d.strftime("%a") if 1 < days < 7 else f"{d:%a %b} {d.day}")
    if "T" in (due or ""):
        label += " " + d.strftime("%I:%M %p").lstrip("0")
    return ("overdue since " + label) if d < n else label


# ------------------------------------------------------------------ store
class TodoStore:
    """CRUD for to-do items in monkey.db. Thread-safe; every call opens its own short connection."""

    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        with self._conn() as c:
            cols = ", ".join(f"{k} {v}" for k, v in COLUMNS.items())
            c.execute(f"CREATE TABLE IF NOT EXISTS todos({cols})")
            have = {r[1] for r in c.execute("PRAGMA table_info(todos)")}
            for name, decl in COLUMNS.items():         # older databases: add what's missing, never drop anything
                if name not in have:
                    c.execute(f"ALTER TABLE todos ADD COLUMN {name} {decl.replace('PRIMARY KEY', '')}")
            c.execute("CREATE INDEX IF NOT EXISTS todos_status ON todos(status)")
            c.execute("DELETE FROM todos WHERE deleted_at IS NOT NULL AND deleted_at < ?", (time.time() - DELETED_KEEP_S,))

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    # ---- helpers
    @staticmethod
    def _row(r: sqlite3.Row | None, now: datetime | None = None) -> dict | None:
        if r is None:
            return None
        d = dict(r)
        try:
            d["steps"] = [{"text": str(s.get("text", "")), "done": bool(s.get("done"))}
                          for s in json.loads(d.get("steps") or "[]") if isinstance(s, dict)]
        except ValueError:
            d["steps"] = []
        d["overdue"] = is_overdue(d, now or datetime.now())
        d["due_time"] = "T" in (d.get("due") or "")
        d.pop("snooze_until", None)
        d.pop("reminded_for", None)
        return d

    @staticmethod
    def _clean_steps(steps) -> list[dict]:
        out = []
        for s in steps or []:
            if isinstance(s, str):
                s = {"text": s, "done": False}
            if isinstance(s, dict) and str(s.get("text", "")).strip():
                out.append({"text": str(s["text"]).strip()[:200], "done": bool(s.get("done"))})
        return out[:20]

    # ---- create / read
    def add(self, text: str, *, due: str | None = None, priority: str = "normal", list: str = "",  # noqa: A002
            notes: str = "", steps=None, source: str = "typed", now: datetime | None = None) -> dict:
        text = " ".join((text or "").split())[:300]
        if not text:
            raise ValueError("a to-do needs some text")
        now = now or datetime.now()
        tid = uuid.uuid4().hex[:8]
        ts = time.time()
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO todos(id, text, notes, due, priority, list, status, steps, source, created, updated)"
                      " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (tid, text, (notes or "")[:2000], normalize_due(due, now),
                       priority if priority in PRIORITIES else "normal", (list or "").strip()[:40],
                       "open", json.dumps(self._clean_steps(steps)), source if source in SOURCES else "typed", ts, ts))
        return self.get(tid, now)  # type: ignore[return-value]

    def get(self, tid: str, now: datetime | None = None, include_deleted: bool = False) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM todos WHERE id=?" + ("" if include_deleted else " AND deleted_at IS NULL"),
                          (tid,)).fetchone()
        return self._row(r, now)

    def items(self, status: str = "open", now: datetime | None = None, sort: str = "due",
              done_limit: int = 50) -> list[dict]:
        """status: open | done | overdue | today | all. Sorted by due (soonest first, no date last) or priority."""
        now = now or datetime.now()
        with self._conn() as c:
            rows = [self._row(r, now) for r in c.execute("SELECT * FROM todos WHERE deleted_at IS NULL")]
        n = _naive(now)
        if status == "done":
            out = sorted((r for r in rows if r["status"] == "done"), key=lambda r: -(r["done_at"] or 0))[:done_limit]
            return out
        out = [r for r in rows if r["status"] == "open"] if status != "all" else rows
        if status == "overdue":
            out = [r for r in out if r["overdue"]]
        elif status == "today":
            out = [r for r in out if r["overdue"] or ((due_datetime(r["due"]) or datetime.max).date() <= n.date())]
        far = datetime.max

        def by_due(r):
            return (r["status"] != "open", due_datetime(r["due"]) or far, PRIO_RANK.get(r["priority"], 1), r["created"] or 0)

        def by_prio(r):
            return (r["status"] != "open", PRIO_RANK.get(r["priority"], 1), due_datetime(r["due"]) or far, r["created"] or 0)

        return sorted(out, key=by_prio if sort == "priority" else by_due)

    def find(self, ref: str, now: datetime | None = None, status: str = "all") -> list[dict]:
        """By id, else by words in the text (best matches first). Used when the user says "mark laundry done"."""
        ref = (ref or "").strip()
        if not ref:
            return []
        exact = self.get(ref.lower(), now)
        if exact:
            return [exact]
        pool = self.items("all", now)
        if status != "all":
            pool = [r for r in pool if r["status"] == status]
        low = ref.lower()
        same = [r for r in pool if r["text"].lower() == low]
        if same:
            return same
        words = {w for w in re.findall(r"[a-z0-9']+", low) if len(w) > 2 and w not in _FILLER}
        if not words:
            return [r for r in pool if low in r["text"].lower()]
        scored = []
        for r in pool:
            have = set(re.findall(r"[a-z0-9']+", r["text"].lower()))
            hit = sum(1 for w in words if w in have or any(h.startswith(w[:5]) for h in have if len(w) >= 5))
            if hit:
                scored.append((hit / len(words), r["status"] == "open", r))
        scored.sort(key=lambda t: (-t[0], not t[1]))
        best = [r for score, _, r in scored if score == scored[0][0]] if scored else []
        return best

    # ---- update
    def update(self, tid: str, now: datetime | None = None, **changes) -> dict:
        now = now or datetime.now()
        cur = self.get(tid, now)
        if cur is None:
            raise KeyError(f"no to-do with id {tid}")
        sets: dict = {}
        if "text" in changes and changes["text"] is not None:
            t = " ".join(str(changes["text"]).split())[:300]
            if not t:
                raise ValueError("a to-do needs some text")
            sets["text"] = t
        if "notes" in changes and changes["notes"] is not None:
            sets["notes"] = str(changes["notes"])[:2000]
        if "due" in changes:
            sets["due"] = normalize_due(changes["due"], now)
            sets["reminded_for"] = ""
            sets["snooze_until"] = None
        if changes.get("priority") in PRIORITIES:
            sets["priority"] = changes["priority"]
        if "list" in changes and changes["list"] is not None:
            sets["list"] = str(changes["list"]).strip()[:40]
        if "steps" in changes and changes["steps"] is not None:
            sets["steps"] = json.dumps(self._clean_steps(changes["steps"]))
        if changes.get("status") in ("open", "done") and changes["status"] != cur["status"]:
            sets["status"] = changes["status"]
            sets["done_at"] = time.time() if changes["status"] == "done" else None
        if not sets:
            return cur
        sets["updated"] = time.time()
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE todos SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), tid))
        return self.get(tid, now)  # type: ignore[return-value]

    def complete(self, tid: str, done: bool = True, now: datetime | None = None) -> dict:
        return self.update(tid, now, status="done" if done else "open")

    def set_step(self, tid: str, index: int, done: bool, now: datetime | None = None) -> dict:
        cur = self.get(tid, now)
        if cur is None:
            raise KeyError(f"no to-do with id {tid}")
        steps = cur["steps"]
        if not 0 <= index < len(steps):
            raise IndexError(f"step {index + 1} doesn't exist (it has {len(steps)})")
        steps[index]["done"] = bool(done)
        return self.update(tid, now, steps=steps)

    # ---- delete (soft, so Undo works) / restore
    def delete(self, tid: str) -> dict:
        cur = self.get(tid)
        if cur is None:
            raise KeyError(f"no to-do with id {tid}")
        with self._lock, self._conn() as c:
            c.execute("UPDATE todos SET deleted_at=? WHERE id=?", (time.time(), tid))
        return cur

    def restore(self, tid: str) -> dict:
        with self._lock, self._conn() as c:
            c.execute("UPDATE todos SET deleted_at=NULL, updated=? WHERE id=?", (time.time(), tid))
        got = self.get(tid)
        if got is None:
            raise KeyError(f"no deleted to-do with id {tid}")
        return got

    # ---- in-app reminders
    def due_reminders(self, now: datetime, lead_min: int = 10, grace_h: float = 2.0) -> list[dict]:
        """Open items with a due TIME that should nudge now: from `lead_min` before the due time until `grace_h`
        after it, once per due time (a snoozed one comes back when its snooze ends)."""
        n = _naive(now)
        ts = now.timestamp()
        out = []
        with self._conn() as c:
            rows = c.execute("SELECT * FROM todos WHERE status='open' AND deleted_at IS NULL AND due LIKE '%T%'").fetchall()
        for r in rows:
            d = due_datetime(r["due"])
            if d is None:
                continue
            if r["snooze_until"] is not None:
                if ts >= r["snooze_until"]:
                    out.append(self._row(r, now))
                continue
            if r["reminded_for"] == r["due"]:
                continue
            if d - timedelta(minutes=lead_min) <= n <= d + timedelta(hours=grace_h):
                out.append(self._row(r, now))
        return out

    def mark_reminded(self, tid: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE todos SET reminded_for=due, snooze_until=NULL WHERE id=?", (tid,))

    def snooze(self, tid: str, minutes: int = 10) -> dict:
        with self._lock, self._conn() as c:
            c.execute("UPDATE todos SET snooze_until=? WHERE id=?", (time.time() + max(1, int(minutes)) * 60, tid))
        got = self.get(tid)
        if got is None:
            raise KeyError(f"no to-do with id {tid}")
        return got

    def counts(self, now: datetime | None = None) -> dict:
        now = now or datetime.now()
        open_ = self.items("open", now)
        n = _naive(now)
        return {"open": len(open_), "overdue": sum(1 for r in open_ if r["overdue"]),
                "today": sum(1 for r in open_ if not r["overdue"] and r["due"]
                             and due_datetime(r["due"]).date() == n.date())}


_FILLER = {"the", "and", "for", "my", "to-do", "todo", "list", "item", "one", "that", "this", "thing", "off", "done",
           "mark", "check", "finished", "with", "about"}

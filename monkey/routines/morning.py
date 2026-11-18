"""Weekday morning brief: 90 minutes before your earliest VERIFIED class (America/Chicago), at most once a day.

Rules (from the sprint brief):
  * Only a schedule you confirmed in the app counts. Calendar events are offered as candidates to confirm; class
    times remembered from old notes are never used to time anything. Canvas due dates are never class times.
  * Idempotent: one brief per school day (kv key "brief:YYYY-MM-DD"). A PC that wakes after your first class has
    started gets a clearly labeled "late" summary in the app, never a fake morning brief, and never a duplicate.
  * Every section says where it came from or why it's missing ("Calendar not connected", "points unknown").
    Nothing is invented: no bus times, addresses, grades or due times that the integrations didn't return.
  * No external notifications here at all. Speaking it on app open is opt-in and kept to two short sentences.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SCHOOL_DAYS = DAYS[:5]


# ------------------------------------------------------------------ schedule
@dataclass
class Schedule:
    by_day: dict[str, str] = field(default_factory=dict)      # "mon" -> "08:50" (earliest in-person class)
    source: str = ""                                           # "confirmed in app (from Google Calendar)" …
    confirmed_at: str | None = None

    @property
    def verified(self) -> bool:
        return bool(self.confirmed_at) and bool(self.by_day)

    @classmethod
    def from_settings(cls, d: dict | None) -> "Schedule":
        d = d or {}
        by_day = {k: v for k, v in (d.get("by_day") or {}).items() if k in DAYS and _hhmm(v) is not None}
        return cls(by_day, d.get("source", ""), d.get("confirmed_at"))

    def to_settings(self) -> dict:
        return asdict(self)


def _hhmm(s: str | None) -> time | None:
    try:
        h, m = str(s).split(":")
        return time(int(h), int(m))
    except (ValueError, TypeError):
        return None


def candidate_schedule(events: list, now: datetime) -> dict[str, dict]:
    """Earliest recurring timed event per weekday over the next 2 weeks, as candidates for the user to confirm.

    Only calendar events (not Canvas due dates), not all-day, at most 4 hours long, and recurring: the same title
    at the same time at least twice in the window, or a course-code-looking title (e.g. "COMM ARTS 100")."""
    import re

    course = re.compile(r"\b[A-Z][A-Z &]{1,14}\s?\d{3}\b")
    seen: dict[tuple, list] = {}
    for e in events:
        if getattr(e, "source", "") == "canvas" or getattr(e, "all_day", False) or e.start is None:
            continue
        st = e.start.astimezone(TZ)
        if e.end and (e.end - e.start) > timedelta(hours=4):
            continue
        key = (DAYS[st.weekday()], e.title.strip(), st.strftime("%H:%M"))
        seen.setdefault(key, []).append(st)
    # "recurring" = the same title at the same time at least twice in the window, on any weekday (a MWF lecture
    # still counts on a Wednesday that a holiday removed from the other week)
    repeats: dict[tuple, int] = {}
    for (day, title, hhmm), starts in seen.items():
        repeats[(title, hhmm)] = repeats.get((title, hhmm), 0) + len(starts)
    out: dict[str, dict] = {}
    for (day, title, hhmm), starts in seen.items():
        if day not in SCHOOL_DAYS:
            continue
        if repeats[(title, hhmm)] < 2 and not course.search(title):
            continue
        cur = out.get(day)
        if cur is None or hhmm < cur["time"]:
            out[day] = {"time": hhmm, "title": title, "seen": len(starts)}
    return dict(sorted(out.items(), key=lambda kv: DAYS.index(kv[0])))


def first_class(day: date, schedule: Schedule) -> datetime | None:
    t = _hhmm(schedule.by_day.get(DAYS[day.weekday()]))
    return datetime.combine(day, t, tzinfo=TZ) if t else None


def brief_time(day: date, schedule: Schedule, lead_min: int = 90) -> datetime | None:
    """When the brief should be ready that day (None: no verified class, or weekend)."""
    if not schedule.verified or DAYS[day.weekday()] not in SCHOOL_DAYS:
        return None
    fc = first_class(day, schedule)
    return fc - timedelta(minutes=lead_min) if fc else None


def next_run(now: datetime, schedule: Schedule, lead_min: int = 90) -> datetime | None:
    now = now.astimezone(TZ)
    for i in range(0, 8):
        d = (now + timedelta(days=i)).date()
        bt = brief_time(d, schedule, lead_min)
        if bt and bt > now:
            return bt
    return None


# ------------------------------------------------------------------ brief
@dataclass
class Section:
    title: str
    status: str                  # ok | empty | not_connected | unavailable | expired
    items: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class Brief:
    day: str
    kind: str                    # morning | late | draft (schedule not confirmed yet)
    created: str
    first_class: str | None
    sections: list[Section]
    top: str
    next_step: str
    spoken: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Sources:
    """Everything the brief reads. Each returns data or raises; None means 'not connected'."""
    events_today: Callable[[date], list] | None = None          # calendar events for that day (google/outlook)
    assignments: Callable[[], dict] | None = None               # AssignmentBoard.load()
    emails: Callable[[], list] | None = None                    # recent unread emails
    weather: Callable[[], dict] | None = None
    sleep: Callable[[], dict | None] | None = None              # Garmin (optional)
    canvas_token: Callable[[], dict] | None = None              # {"status": ok|expiring|expired|none, "days": n}


def _safe(fn, *a):
    if fn is None:
        return "not_connected", None
    try:
        return "ok", fn(*a)
    except Exception as exc:  # noqa: BLE001
        return "unavailable", str(exc)[:120]


def _due(a: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(a["due"]).astimezone(TZ) if a.get("due") else None
    except (TypeError, ValueError):
        return None


def build(now: datetime, schedule: Schedule, src: Sources, kind: str) -> Brief:
    now = now.astimezone(TZ)
    today = now.date()
    fc = first_class(today, schedule) if schedule.verified else None
    sections: list[Section] = []

    # classes: today's calendar events; the confirmed schedule gives the first-class time
    st, evs = _safe(src.events_today, today)
    if st == "ok":
        timed = sorted([e for e in (evs or []) if not getattr(e, "all_day", False) and e.start], key=lambda e: e.start)
        items = [f"{e.start.astimezone(TZ):%I:%M %p}".lstrip("0") + f" {e.title}" + (f" ({e.location})" if e.location else "")
                 for e in timed]
        sections.append(Section("Today", "ok" if items else "empty", items,
                                "" if items else "Nothing on your calendar today."))
    else:
        sections.append(Section("Today", st, [], "Calendar not connected." if st == "not_connected"
                                else f"Calendar unavailable ({evs})."))
    if not schedule.verified:
        sections[-1].note = (sections[-1].note + " " if sections[-1].note else "") + \
            "Class schedule not confirmed yet, so the brief isn't timed."

    # assignments due within 72 h, ranked by verified points (when Canvas gives them), then deadline
    st, board = _safe(src.assignments)
    due_soon: list[dict] = []
    if st == "ok" and board and board.get("source") != "none":
        horizon = now + timedelta(hours=72)
        for a in board.get("todo", []):
            d = _due(a)
            if d and now - timedelta(hours=1) <= d <= horizon and not a.get("done"):
                due_soon.append(a)
        # grade impact (% of final grade, from Canvas weights) first, then points, then the deadline
        due_soon.sort(key=lambda a: (-(a.get("impact_pct") or 0), -(a.get("points") or 0), _due(a)))
        items = []
        for a in due_soon[:5]:
            if isinstance(a.get("impact_pct"), (int, float)):
                pts = f"{a['impact_pct']:.1f}% of grade"
            elif isinstance(a.get("points"), (int, float)):
                pts = f"{a['points']:g} pts"
            else:
                pts = "points unknown"
            items.append(f"{a.get('title', '?')} ({a.get('course', '')}) due {_due(a):%a %I:%M %p}, {pts}")
        note = "" if items else "Nothing due in the next 3 days."
        if board.get("source") == "feed":
            note = (note + " " if note else "") + "From the Canvas calendar feed (no points or grades)."
        sections.append(Section("Due in 72 h", "ok" if items else "empty", items, note.strip()))
    else:
        sections.append(Section("Due in 72 h", "not_connected" if st == "not_connected" or not board
                                else st, [], "Canvas not connected." if st != "unavailable" else f"Canvas unavailable ({board})."))

    st, tok = _safe(src.canvas_token)
    if st == "ok" and tok and tok.get("status") in ("expiring", "expired"):
        sections.append(Section("Canvas token", "expired" if tok["status"] == "expired" else "ok", [],
                                "Canvas token expired. Request a new one (UW DoIT form) and paste it in Settings."
                                if tok["status"] == "expired" else f"Canvas token expires in {tok.get('days')} days."))

    st, mail = _safe(src.emails)
    if st == "ok":
        mail = mail or []
        items = [f"{getattr(m, 'sender', '')}: {getattr(m, 'subject', '')}" for m in mail[:3]]
        sections.append(Section("Unread email", "ok" if items else "empty", items,
                                f"{len(mail)} unread (newest first, not ranked)." if mail else "Inbox clear."))
    else:
        sections.append(Section("Unread email", st, [], "Email not connected." if st == "not_connected"
                                else "Email unavailable."))

    st, w = _safe(src.weather)
    if st == "ok" and w:
        sections.append(Section("Weather", "ok", [str(w.get("summary") or w.get("short") or w)[:140]]))
    else:
        sections.append(Section("Weather", "unavailable" if st != "not_connected" else st, [], "Weather unavailable."))

    if src.sleep is not None:
        st, sl = _safe(src.sleep)
        if st == "ok" and sl:
            sections.append(Section("Sleep", "ok", [str(sl.get("summary") or sl)[:140]]))

    # top priority + next step, only from verified data
    top, step = "No deadlines in the next 3 days.", "Pick one project task for today."
    if due_soon:
        a = due_soon[0]
        top = f"{a.get('title')} ({a.get('course', '')}), due {_due(a):%a %I:%M %p}"
        step = f"Open it on Canvas and do the first 25 minutes before {'class' if fc else 'lunch'}."
    elif fc:
        top = f"First class at {fc:%I:%M %p}".replace(" 0", " ")
        step = "Leave enough time to get there."

    spoken_bits = []
    if kind == "late":
        spoken_bits.append("Late start today.")
    if fc:
        spoken_bits.append(f"First class at {fc:%I:%M}".replace(" 0", " ") + ".")
    if due_soon:
        spoken_bits.append(f"Top priority: {due_soon[0].get('title')}.")
    spoken = " ".join(spoken_bits[:2]) or "Morning. Your rundown is on screen."
    return Brief(today.isoformat(), kind, now.isoformat(timespec="minutes"),
                 fc.isoformat(timespec="minutes") if fc else None, sections, top, step, spoken)


class MorningRoutine:
    """Decides whether a brief is due, builds it once per day, and caches it in the app's kv store."""

    def __init__(self, get_state: Callable[[str], Any], put_state: Callable[[str, Any, float], None],
                 schedule: Callable[[], Schedule], sources: Callable[[], Sources], lead_min: Callable[[], int] = lambda: 90):
        self.get_state, self.put_state = get_state, put_state
        self.schedule, self.sources, self.lead_min = schedule, sources, lead_min

    def key(self, day: date) -> str:
        return f"brief:{day.isoformat()}"

    def cached(self, day: date) -> dict | None:
        got = self.get_state(self.key(day))
        return got[0] if got else None

    def status(self, now: datetime) -> dict:
        now = now.astimezone(TZ)
        sched = self.schedule()
        nr = next_run(now, sched, self.lead_min())
        today = self.cached(now.date())
        return {"verified": sched.verified, "schedule": sched.by_day, "next_run": nr.isoformat() if nr else None,
                "today": today["kind"] if today else None,
                "weekend": DAYS[now.weekday()] not in SCHOOL_DAYS}

    def run(self, now: datetime, trigger: str = "scheduled") -> dict | None:
        """trigger: 'scheduled' (Task Scheduler / timer) or 'app_open'. Returns the brief dict, or None."""
        now = now.astimezone(TZ)
        day = now.date()
        if DAYS[day.weekday()] not in SCHOOL_DAYS:
            return None                                                 # no weekend briefs by default
        have = self.cached(day)
        if have is not None:
            return have                                                 # never build (or show as new) twice
        sched = self.schedule()
        if not sched.verified:
            if trigger != "app_open":
                return None                                             # no timed runs without a confirmed schedule
            b = build(now, sched, self.sources(), "draft").to_dict()
            return b                                                    # draft preview isn't cached as "the" brief
        fc = first_class(day, sched)
        bt = brief_time(day, sched, self.lead_min())
        if bt is None:
            return None                                                 # no class today
        if now < bt and trigger == "scheduled":
            return None                                                 # too early (timer fired early)
        kind = "late" if fc and now >= fc else "morning"
        b = build(now, sched, self.sources(), kind).to_dict()
        self.put_state(self.key(day), b, now.timestamp())
        return b


def brief_json(b: dict) -> str:
    return json.dumps(b, indent=1, default=str)

"""Morning brief: verified schedule only, 90 min lead in America/Chicago, idempotent, honest about gaps."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS

from monkey.routines.morning import (TZ, MorningRoutine, Schedule, Sources, brief_time, build,
                                     candidate_schedule, next_run)

SCHED = Schedule({"mon": "08:50", "tue": "09:30", "wed": "08:50", "thu": "09:30", "fri": "08:50"},
                 "confirmed in app", "2026-11-18T10:00")


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def kv():
    store = {}
    return store, (lambda k: store.get(k)), (lambda k, v, ts: store.__setitem__(k, (v, ts)))


def board(now, *items):
    return {"source": "canvas", "todo": [dict(it) for it in items], "done": [], "stats": {}}


def sources(now, assignments=None, events=None, mail=None):
    return Sources(
        events_today=(lambda d: events or []),
        assignments=(lambda: assignments if assignments is not None else {"source": "none", "todo": []}),
        emails=(lambda: mail or []), weather=lambda: {"summary": "Cloudy, 38°F"},
    )


# ---------------------------------------------------------------- timing
def test_brief_is_90_minutes_before_earliest_verified_class():
    assert brief_time(date(2026, 11, 18), SCHED) == at(2026, 11, 18, 7, 20)        # Wed 8:50 -> 7:20
    assert brief_time(date(2026, 11, 19), SCHED) == at(2026, 11, 19, 8, 0)         # Thu 9:30 -> 8:00


def test_weekends_and_unverified_schedules_have_no_timed_run():
    assert brief_time(date(2026, 11, 21), SCHED) is None                           # Saturday
    unverified = Schedule(SCHED.by_day, "from old notes", None)
    assert brief_time(date(2026, 11, 18), unverified) is None
    assert next_run(at(2026, 11, 18, 6, 0), unverified) is None


def test_dst_transitions_keep_wall_clock_time():
    # US DST ends 2026-11-01 and starts 2027-03-14; Monday-after must still be 7:20 local
    fall = brief_time(date(2026, 11, 2), SCHED)
    spring = brief_time(date(2027, 3, 15), SCHED)
    assert (fall.hour, fall.minute) == (7, 20) and fall.utcoffset() == timedelta(hours=-6)
    assert (spring.hour, spring.minute) == (7, 20) and spring.utcoffset() == timedelta(hours=-5)


def test_next_run_skips_weekend():
    nr = next_run(at(2026, 11, 20, 12, 0), SCHED)                                  # Friday noon
    assert nr == at(2026, 11, 23, 7, 20)                                           # Monday


# ---------------------------------------------------------------- idempotency + missed runs
def test_one_brief_per_day_even_with_duplicate_triggers():
    store, get, put = kv()
    r = MorningRoutine(get, put, lambda: SCHED, lambda: sources(None))
    first = r.run(at(2026, 11, 18, 7, 21), "scheduled")
    again = r.run(at(2026, 11, 18, 7, 22), "scheduled")
    opened = r.run(at(2026, 11, 18, 7, 40), "app_open")
    assert first["kind"] == "morning" and again == first and opened == first and len(store) == 1


def test_early_timer_does_nothing_and_late_wake_is_labeled_late():
    store, get, put = kv()
    r = MorningRoutine(get, put, lambda: SCHED, lambda: sources(None))
    assert r.run(at(2026, 11, 18, 6, 0), "scheduled") is None and not store         # before 7:20
    late = r.run(at(2026, 11, 18, 10, 15), "scheduled")                              # laptop woke after class
    assert late["kind"] == "late" and late["spoken"].startswith("Late start")


def test_unverified_schedule_gives_draft_preview_only_on_open():
    store, get, put = kv()
    r = MorningRoutine(get, put, lambda: Schedule({"mon": "08:50"}, "old notes", None), lambda: sources(None))
    assert r.run(at(2026, 11, 16, 7, 30), "scheduled") is None
    d = r.run(at(2026, 11, 16, 7, 30), "app_open")
    assert d["kind"] == "draft" and not store                                       # preview, never cached
    assert "not confirmed" in d["sections"][0]["note"]


def test_weekend_runs_nothing():
    store, get, put = kv()
    r = MorningRoutine(get, put, lambda: SCHED, lambda: sources(None))
    assert r.run(at(2026, 11, 21, 9, 0), "app_open") is None


# ---------------------------------------------------------------- content honesty
def test_missing_integrations_are_labeled_not_invented():
    b = build(at(2026, 11, 18, 7, 20), SCHED, Sources(), "morning").to_dict()
    notes = {s["title"]: (s["status"], s["note"]) for s in b["sections"]}
    assert notes["Today"][0] == "not_connected" and "Calendar not connected" in notes["Today"][1]
    assert notes["Due in 72 h"][0] == "not_connected"
    assert notes["Unread email"][0] == "not_connected"
    assert b["top"] == "First class at 8:50 AM"                                     # only verified data
    text = str(b)
    assert "bus" not in text.lower() and "address" not in text.lower()


def test_assignments_ranked_by_grade_impact_then_points_then_deadline():
    now = at(2026, 11, 18, 7, 20)
    iso = lambda h: (now + timedelta(hours=h)).astimezone(timezone.utc).isoformat()   # noqa: E731
    bd = board(now,
               {"title": "Reading quiz", "course": "COMM", "due": iso(5), "points": 5, "impact_pct": 0.5},
               {"title": "Project proposal", "course": "DS 240", "due": iso(50), "points": 100, "impact_pct": 10},
               {"title": "Far away essay", "course": "X", "due": iso(24 * 6), "points": 200},
               {"title": "Unknown points thing", "course": "Y", "due": iso(30)})
    b = build(now, SCHED, sources(now, assignments=bd), "morning").to_dict()
    due = next(s for s in b["sections"] if s["title"] == "Due in 72 h")
    assert due["items"][0].startswith("Project proposal") and "10.0% of grade" in due["items"][0]
    assert not any("Far away" in i for i in due["items"])                          # outside 72 h
    assert any("points unknown" in i for i in due["items"])
    assert b["top"].startswith("Project proposal")


def test_feed_only_canvas_says_no_points():
    now = at(2026, 11, 18, 7, 20)
    bd = {"source": "feed", "todo": [{"title": "HW", "course": "C", "due": (now + timedelta(hours=3)).isoformat()}]}
    b = build(now, SCHED, sources(now, assignments=bd), "morning").to_dict()
    due = next(s for s in b["sections"] if s["title"] == "Due in 72 h")
    assert "points unknown" in due["items"][0] and "calendar feed" in due["note"]


def test_failing_source_is_unavailable_not_crash():
    def boom(*a):
        raise RuntimeError("offline")
    b = build(at(2026, 11, 18, 7, 20), SCHED, Sources(events_today=boom, emails=boom, weather=boom), "morning")
    st = {s.title: s.status for s in b.sections}
    assert st["Today"] == "unavailable" and st["Unread email"] == "unavailable" and st["Weather"] == "unavailable"


def test_canvas_token_expiry_shows_up():
    src = sources(None)
    src.canvas_token = lambda: {"status": "expired", "days": 0}
    b = build(at(2026, 11, 18, 7, 20), SCHED, src, "morning")
    assert any(s.title == "Canvas token" and "expired" in s.note for s in b.sections)


# ---------------------------------------------------------------- schedule candidates from the calendar
def test_candidate_schedule_from_recurring_calendar_events():
    def ev(title, day, hh, mm, source="google", hours=1):
        st = datetime(2026, 11, day, hh, mm, tzinfo=TZ)
        return NS(title=title, start=st, end=st + timedelta(hours=hours), source=source, all_day=False, location="")
    events = [ev("Intro to Entrepreneurship", 16, 11, 0), ev("Intro to Entrepreneurship", 23, 11, 0),   # Mon x2
              ev("COMM ARTS 100", 17, 9, 30),                                                         # Tue course code
              ev("Dentist", 18, 8, 0),                                                                # one-off Wed
              ev("Essay due", 19, 8, 0, source="canvas"),                                             # Canvas: never a class
              ev("Hackathon", 20, 9, 0, hours=10)]                                                     # too long
    c = candidate_schedule(events, at(2026, 11, 16, 0, 0))
    assert c == {"mon": {"time": "11:00", "title": "Intro to Entrepreneurship", "seen": 2},
                 "tue": {"time": "09:30", "title": "COMM ARTS 100", "seen": 1}}


def test_moved_class_changes_the_brief_time():
    s = Schedule(dict(SCHED.by_day), "confirmed", "2026-11-18")
    assert brief_time(date(2026, 11, 19), s) == at(2026, 11, 19, 8, 0)
    s.by_day["thu"] = "11:00"                                                     # user re-confirms a change
    assert brief_time(date(2026, 11, 19), s) == at(2026, 11, 19, 9, 30)

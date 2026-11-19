"""Fixes from the persona playtests (docs/PLAYTEST.md): each test pins down one thing testers tripped on."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from monkey import app as app_mod, keys
from monkey.brain.tools import ToolRunner
from monkey.integrations.base import Event
from monkey.integrations.canvas_api import pretty_course


@pytest.fixture
def mk(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    a = app_mod.MonkeyApp(tmp_path / "Monkey", headless=True)
    events = []
    a.ui.emit = lambda name, p=None: events.append((name, p))
    return a, app_mod.Api(a), events


def test_memory_inspector_lists_everything_and_edits(mk):
    a, api, _ = mk
    root = Path(a.memory.memory_root)
    from monkey.memory import facts as F

    F.add_fact(root, "profile.md", "Roommate is Sam")
    r = api.memory_list()
    texts = [f["text"] for f in r["facts"]]
    assert r["ok"] and "Roommate is Sam" in texts
    assert not any(f["file"] in ("model_policy.md", "sites.md") for f in r["facts"])   # internal notes hidden
    fid = next(f["id"] for f in r["facts"] if f["text"] == "Roommate is Sam")
    e = api.memory_edit(fid, "Roommate is Sam Kim")
    assert e["ok"]
    texts = [f["text"] for f in api.memory_list()["facts"]]
    assert "Roommate is Sam Kim" in texts and "Roommate is Sam" not in texts
    assert api.memory_edit(fid, "")["ok"] is False


def test_typed_question_does_not_open_the_mic(mk, monkeypatch):
    a, api, _ = mk
    keys.set("anthropic", "sk-ant-test-key-1234567890abcdef")
    monkeypatch.setattr(a, "_ensure_client", lambda: object())
    monkeypatch.setattr(a.agent, "handle", lambda *x, **k: "ok")
    a.cfg.settings.conversation_mode = True
    a._in_conversation = True
    a.ask("what's due?", typed=True)
    assert a._in_conversation is False


def test_calendar_day_window_and_local_times():
    w = ToolRunner._day_window("tomorrow")
    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    assert w[0] == today + timedelta(days=1) and w[1] - w[0] == timedelta(days=1) and w[2].startswith("Tomorrow")
    assert ToolRunner._day_window("") is None and ToolRunner._day_window("someday") is None
    utc = datetime(2026, 11, 20, 5, 59, tzinfo=timezone.utc)
    b = Event(id="x", source="canvas", title="Problem Set 7 [MATH_222_001_F26]", start=utc).brief()
    assert b["title"] == "Problem Set 7 (MATH 222)"
    assert b["start"] == utc.astimezone().isoformat() and "when" in b


def test_get_calendar_tomorrow_only_returns_tomorrow():
    now = datetime.now().astimezone()
    today_ev = Event(id="t", source="calendar", title="Today thing", start=now + timedelta(minutes=30))
    tom = (now + timedelta(days=1)).replace(hour=9, minute=55, second=0, microsecond=0)
    tom_ev = Event(id="m", source="calendar", title="MATH 222 Lecture", start=tom)
    cal = NS(name="calendar", available=lambda: True, list_events=lambda s, e: [today_ev, tom_ev])
    emitted = []
    runner = ToolRunner(NS(calendars=[cal], emit=lambda n, p: emitted.append((n, p))))
    out = runner.t_get_calendar(day="tomorrow")
    assert [e["title"] for e in out] == ["MATH 222 Lecture"]
    assert emitted[-1][1]["label"].startswith("Tomorrow")
    assert "Nothing on the calendar" in ToolRunner(NS(calendars=[NS(name="c", available=lambda: True, list_events=lambda s, e: [])],
                                                      emit=lambda *a: None)).t_get_calendar(day="today")


def test_pretty_course_names():
    assert pretty_course("PSYCH_202_001_F26") == "PSYCH 202"
    assert pretty_course("COMP_SCI_300_002_F26") == "COMP SCI 300"
    assert pretty_course("Biology 101") == "Biology 101"


def test_text_from_two_rounds_is_not_glued(tmp_path):
    from tests.test_agent_loop import build, text_block, tool_block

    script = [([text_block("Let me check Canvas."), tool_block("emote", {"name": "happy"})], "tool_use"),
              ([text_block("You've got 6 things.")], "end_turn")]
    agent, _client, events, *_ = build(tmp_path, script)
    agent.handle("what's due")
    shown = "".join(p["text"] for n, p in events if n == "delta")
    assert "Canvas. You've" in shown and "Canvas.You've" not in shown


def test_brief_refresh_rebuilds_todays_brief_after_setup_changes():
    from tests.test_morning import SCHED, at, kv, sources

    from monkey.routines.morning import MorningRoutine

    store, get, put = kv()
    srcs = {"now": sources(None)}
    r = MorningRoutine(get, put, lambda: SCHED, lambda: srcs["now"])
    first = r.run(at(2026, 11, 18, 7, 21), "scheduled")
    srcs["now"] = sources(None, mail=[NS(sender="Prof", subject="Room change", unread=True, account="gmail",
                                         received=at(2026, 11, 18, 7, 0), brief=lambda: {})])
    assert r.run(at(2026, 11, 18, 7, 40), "app_open") == first                   # normal opens reuse it
    rebuilt = r.run(at(2026, 11, 18, 7, 40), "app_open", rebuild=True)            # after you changed your setup
    assert rebuilt != first and json.dumps(rebuilt, default=str).count("Room change") >= 1
    assert r.run(at(2026, 11, 18, 7, 45), "scheduled", rebuild=True) == rebuilt     # timer never rebuilds


def test_download_error_is_plain_words():
    from monkey.app import explain_download_error

    assert "refused" in explain_download_error(RuntimeError("HTTP Error 403: Forbidden"))
    assert "internet" in explain_download_error(OSError("timed out"))
    assert "403" not in explain_download_error(RuntimeError("HTTP Error 403: Forbidden"))


def test_open_settings_tool(tmp_path):
    emitted = []
    r = ToolRunner(NS(emit=lambda n, p: emitted.append((n, p)))).t_open_settings("sound")
    assert emitted == [("open_settings", {"section": "sound"})] and "sound" in r


# ---------------------------------------------------------------- verification round 2
def test_class_times_from_notes_and_calendar_ignores_non_classes():
    from monkey.routines.morning import TZ, candidate_schedule, schedule_from_notes

    notes = ("- MATH 222 (Calculus 2) — Mon/Wed/Fri 9:55, Van Vleck\n- COMP SCI 300 — Tue/Thu 11:00; lab Wed 1:30\n"
             "- PSYCH 202 — Tue/Thu 2:30\n- Office hours Fri 3:00\n- (Monkey fills in your classes)")
    got = schedule_from_notes(notes)
    assert {d: v["time"] for d, v in got.items()} == {"mon": "09:55", "tue": "11:00", "wed": "09:55", "thu": "11:00", "fri": "09:55"}
    assert got["tue"]["title"] == "COMP SCI 300"
    fri = datetime(2026, 11, 20, 5, 0, tzinfo=TZ)
    odd = [Event(id="o", source="google", title="Office hours: MATH 222", start=fri, end=fri + timedelta(hours=1))]
    assert candidate_schedule(odd, fri) == {}            # the 5 AM "class" testers got is gone


def test_detect_uses_notes_when_no_calendar(mk):
    a, api, _ = mk
    a.memory.write("classes.md", "# Classes\n- BIO 151 MWF 8:50\n- CS 300 TTh 11:00am\n")
    r = api.brief_candidates()
    assert r["ok"] and r["source"] == "your notes" and r["candidates"]["mon"]["time"] == "08:50"


def test_rejected_claude_key_is_not_kept(mk, monkeypatch):
    a, api, _ = mk
    monkeypatch.setattr(a, "verify_anthropic", lambda: {"ok": False, "rejected": True,
                                                        "error": "Anthropic didn't accept the key."})
    r = api.save_key("anthropic", "sk-ant-api03-half")
    assert r["ok"] is False and "didn't accept" in r["error"] and not keys.get("anthropic")


def test_x_on_listening_stops_the_mic_now(mk):
    a, api, events = mk
    cancelled = []
    a.listener = NS(mode="record", muted=False, cancel=lambda: cancelled.append(1), end_conversation=lambda: None)
    a._listening = True
    api.end_conversation()
    assert cancelled and a._listening is False
    assert events[-1][0] == "state" and events[-1][1]["state"] != "listening"


def test_brief_today_shows_first_class_when_calendar_is_empty():
    from tests.test_morning import SCHED, at, sources

    from monkey.routines.morning import build

    b = build(at(2026, 11, 19, 7, 0), SCHED, sources(None), "morning").to_dict()
    today = next(s for s in b["sections"] if s["title"] == "Today")
    assert today["items"] and "First class" in today["items"][0] and "Nothing on your calendar" not in today["note"]


def test_not_connected_tells_claude_to_open_settings():
    r = ToolRunner(NS(calendars=[], emit=lambda *a: None)).t_get_calendar()
    assert "open_settings('accounts')" in r


# ---------------------------------------------------------------- verification round 3
def test_memory_search_skips_internal_notes_and_the_question_itself(tmp_path):
    from monkey.memory.history import HistoryStore
    from monkey.memory import facts as F

    root = tmp_path / "memory"
    (root / "memories").mkdir(parents=True)
    F.add_fact(root / "memories", "profile.md", "Roommate is Sam")
    F.add_fact(root / "memories", "model_policy.md", "Auto Haiku 5.5 low; Important Sonnet 5.5 about me")
    hist = HistoryStore(tmp_path / "h.db")
    sid = hist.start_session("typed")
    hist.add_message(sid, "user", "what do you know about me", "typed")
    runner = ToolRunner(NS(history=hist, emit=lambda *a: None, memory=NS(memory_root=str(root))))
    runner._mem_root = lambda: root / "memories"
    runner.user_texts = ["what do you know about me"]
    out = runner.t_search_memory("about me Sam")
    assert "Roommate is Sam" in out or "No matching" in out
    assert "Haiku" not in out and "what do you know about me" not in out


# ---------------------------------------------------------------- verification round 4
def test_short_key_is_only_a_hint_claude_decides(mk, monkeypatch):
    """A hard length block locked a tester out; the server check is the only gate."""
    a, api, _ = mk
    monkeypatch.setattr(a, "verify_anthropic", lambda: {"ok": True})
    r = api.save_key("anthropic", "sk-ant-api03-ShortButValidKey123")
    assert r["ok"] and keys.get("anthropic") == "sk-ant-api03-ShortButValidKey123"


def test_brief_today_lists_classes_from_notes():
    from tests.test_morning import SCHED, at, sources

    from monkey.routines.morning import build

    src = sources(None)
    src.class_notes = lambda: "- COMP SCI 300 — Tue/Thu 11:00\n- PSYCH 202 — Tue/Thu 2:30\n- MATH 222 — Mon/Wed/Fri 9:55"
    b = build(at(2026, 11, 19, 7, 0), SCHED, src, "morning").to_dict()        # a Thursday
    today = next(x for x in b["sections"] if x["title"] == "Today")
    assert today["items"][0].startswith("11:00 AM COMP SCI 300") and "PSYCH 202" in today["items"][1]
    assert not any("MATH" in i for i in today["items"])


# ---------------------------------------------------------------- verification round 5
def test_memory_search_skips_this_conversation_but_keeps_past_ones(tmp_path):
    """Monkey's earlier reply in the same chat (with a since-corrected fact) came back as a 'memory'."""
    from monkey.memory.history import HistoryStore
    from monkey.memory import facts as F

    root = tmp_path / "memory"
    (root / "memories").mkdir(parents=True)
    F.add_fact(root / "memories", "profile.md", "Sophomore CS major, works at the library desk")
    hist = HistoryStore(tmp_path / "h.db")
    old = hist.start_session("old")
    hist.add_message(old, "assistant", "Monkey said: the library desk shift moved to Friday", "reply")
    now = hist.start_session("now")
    hist.add_message(now, "assistant", "Here's what I know: Student at UW, library desk maybe", "reply")
    runner = ToolRunner(NS(history=hist, emit=lambda *a: None, memory=NS(memory_root=str(root))))
    runner._mem_root = lambda: root / "memories"
    runner.user_texts, runner.session_id = ["what about the library desk"], now
    out = runner.t_search_memory("library desk")
    assert "Sophomore CS major" in out and "shift moved to Friday" in out
    assert "Student at UW" not in out

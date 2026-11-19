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

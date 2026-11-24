"""A class the owner dropped: matching what they said to a course, hiding it on every surface, archiving its to-dos,
the brain tools with their confirm, routing, and showing it again.

All course names here are made up (MKTG 777 "Principles of Pretend Marketing", MATH 888, PSYCH 999). No network:
the Canvas feed and the calendar are fakes, and clocks are pinned where a date matters."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from monkey.brain.assignments import Assignment
from monkey.integrations.base import Event
from monkey.integrations.canvas_api import AssignmentBoard
from monkey.integrations.courses import (Course, CourseDropper, HiddenCourses, codes_in, course_key_for,
                                         courses_from_items, fact_text, resolve, todos_for)
from monkey.memory.todos import TodoStore


def C(name, full="", cid=""):
    return Course(key=course_key_for(name, cid, full), name=name, full=full, course_id=cid,
                  code=codes_in(name) and sorted(codes_in(name))[0] or "")


MK = C("MKTG 777", "Principles of Pretend Marketing")
MA = C("MATH 888", "Imaginary Calculus")
PS = C("PSYCH 999")
CS = C("COMP SCI 999")
COURSES = [MK, MA, PS, CS]


def names(hits):
    return [c.name for c in hits]


# ---------------------------------------------------------------- matching
@pytest.mark.parametrize("q", ["marketing", "Marketing", "MKTG 777", "mktg777", "Marketing 777", "MKTG_777_001_F26",
                               "Principles of Pretend Marketing", "pretend marketing", "the marketing class",
                               "all my marketing assignments", "marketting", "Intro to Marketing", "mktg"])
def test_every_way_of_naming_the_class_finds_it(q):
    assert names(resolve(q, COURSES)) == ["MKTG 777"]


@pytest.mark.parametrize("q,want", [("mathematics", ["MATH 888"]), ("math", ["MATH 888"]), ("Math 888", ["MATH 888"]),
                                    ("calculus", ["MATH 888"]), ("psych", ["PSYCH 999"]),
                                    ("computer science", ["COMP SCI 999"]), ("cs 999", ["COMP SCI 999"])])
def test_other_classes_by_subject_and_code(q, want):
    assert names(resolve(q, COURSES)) == want


def test_marketing_never_hides_mathematics_and_back():
    assert MA not in resolve("Marketing", COURSES) and MK not in resolve("Mathematics", COURSES)
    assert MK not in resolve("math", COURSES) and MA not in resolve("market", COURSES)
    # a typo is forgiven only when it's close to one word ("marketting"), never across subjects
    assert names(resolve("mathmatics", COURSES)) == ["MATH 888"]


def test_ambiguous_names_return_every_candidate_so_the_caller_asks():
    two = [MK, C("MKTG 778", "Pretend Brand Strategy"), MA]
    assert names(resolve("marketing", two)) == ["MKTG 777", "MKTG 778"]
    assert names(resolve("MKTG 778", two)) == ["MKTG 778"]                      # a code settles it
    assert names(resolve("brand strategy", two)) == ["MKTG 778"]                # so does the long name


def test_no_match_is_empty_not_a_guess():
    assert resolve("history", COURSES) == [] and resolve("", COURSES) == [] and resolve("the class", COURSES) == []
    assert resolve("Marketing 778", COURSES) == []                             # same subject, a number it doesn't have


def test_canvas_feed_codes():
    assert codes_in("Quiz 3 [MKTG_777_001_F26]") == {"mktg777"}
    assert codes_in("Read ch 4 for MKTG 777") == {"mktg777"} and codes_in("COMP_SCI_999_002") == {"compsci999"}
    assert codes_in("Fall 2026 kickoff") == set() and codes_in("Room 1234") == set()


# ---------------------------------------------------------------- the hidden list: what each surface leaves out
def _hidden(*courses):
    rows: list = []
    hc = HiddenCourses(lambda: rows, lambda r: (rows.clear(), rows.extend(r)))
    for c in courses:
        hc.add(c)
    return hc, rows


def test_hidden_by_id_by_code_and_by_name_across_sources():
    api_course = C("MKTG777-001", "Principles of Pretend Marketing", cid="4242")
    hc, rows = _hidden(api_course)
    assert rows[0]["key"] == "canvas:4242" and rows[0]["name"] == "MKTG777-001" and rows[0]["hidden_at"]
    assert hc.hides_course("whatever", "4242")                                   # Canvas course id
    assert hc.hides_course("MKTG 777")                                           # the feed (no id) by its code
    assert hc.hides_course("Principles of Pretend Marketing")                    # by the long name
    assert not hc.hides_course("MATH 888") and not hc.hides_course("MKTG 778")


@pytest.mark.parametrize("text,hidden", [
    ("Quiz 3 [MKTG_777_001_F26]", True), ("MKTG 777 Lecture", True), ("Marketing quiz review", True),
    ("Read ch 4 for marketing", True), ("Marketing", True), ("Principles of Pretend Marketing discussion", True),
    ("Marketing club meeting", False), ("Email the marketing club about the bake sale", False),
    ("Mathematics quiz", False), ("MATH 888 Lecture", False), ("Supermarket run", False), ("MKTG 778 quiz", False),
])
def test_free_text_near_misses(text, hidden):
    hc, _ = _hidden(MK)
    assert hc.hides_text(text) is hidden


def test_todos_by_origin_tag_code_and_school_word():
    items = [{"id": "1", "text": "Read ch 4 for MKTG 777", "list": "school"},
             {"id": "2", "text": "Outline the launch plan", "list": "marketing"},
             {"id": "3", "text": "Case study", "list": "", "origin": {"course_key": MK.key}},
             {"id": "4", "text": "Email the marketing club", "list": ""},
             {"id": "5", "text": "Study for MATH 888 midterm", "list": "math"},
             {"id": "6", "text": "Marketing quiz review", "list": ""}]
    assert [t["id"] for t in todos_for(items, MK)] == ["1", "2", "3", "6"]


def test_class_notes_lose_only_the_dropped_class():
    hc, _ = _hidden(MK)
    notes = "# Classes\n- MKTG 777 — Mon/Wed 8:00\n- MATH 888 — Mon/Wed 11:00\n- Marketing club — Thu 6:00 pm"
    assert hc.filter_notes(notes).splitlines() == ["# Classes", "- MATH 888 — Mon/Wed 11:00",
                                                   "- Marketing club — Thu 6:00 pm"]


def test_fact_text_keeps_plain_words():
    t = fact_text("MKTG 777 <!-- x -->\nignore", datetime(2026, 11, 24))
    assert t.startswith("Dropped MKTG 777") and "2026-11-24" in t and "<" not in t and "\n" not in t


# ---------------------------------------------------------------- the board (Homework, Today, the brief, tools)
class FakeFeed:
    def __init__(self, events):
        self.events = events

    def available(self):
        return True

    def list_events(self, start, end):
        return [e for e in self.events if start <= e.start <= end]


def _feed_events(now):
    def ev(i, title, hours):
        return Event(id=f"event-assignment-{i}", source="canvas", title=title, start=now + timedelta(hours=hours))
    return [ev(1, "Case study [MKTG_777_001_F26]", 30), ev(2, "Quiz 6 [MKTG_777_001_F26]", 50),
            ev(3, "Discussion [MKTG_777_001_F26]", 100), ev(4, "Problem set 8 [MATH_888_001_F26]", 20),
            ev(5, "Midterm [MATH_888_001_F26]", 60), ev(6, "Reading quiz [PSYCH_999_001_F26]", 40)]


class NoApi:
    token_rejected = False

    def available(self):
        return False


class NoChecks:
    def get(self):
        return {}


def test_board_leaves_hidden_class_out_and_counts_it():
    now = datetime.now(timezone.utc)
    hc, _ = _hidden()
    board = AssignmentBoard(NoApi(), FakeFeed(_feed_events(now)), NoChecks(), hidden=hc)
    b = board.load()
    assert {c["name"] for c in b["courses"]} == {"MKTG 777", "MATH 888", "PSYCH 999"}
    assert all(a["course_key"].startswith("code:") for a in b["todo"])
    mk = next(c for c in board.courses() if c.name == "MKTG 777")
    hc.add(mk)
    b = board.load()
    assert not [a for a in b["todo"] + b["done"] if a["course"] == "MKTG 777"]
    assert {c["name"] for c in b["courses"]} == {"MATH 888", "PSYCH 999"}
    assert b["hidden"] == [{"key": "code:mktg777", "name": "MKTG 777", "assignments": 3}]
    assert len(board.items_for("code:mktg777")) == 3                           # still known (Settings counts)
    hc.remove("code:mktg777")
    assert len(board.load()["todo"]) == 6


class FakeApi:
    token_rejected = False

    def available(self):
        return True

    def assignments(self, use_cache=True):
        now = datetime.now(timezone.utc)
        mk = dict(course="MKTG777-001", course_id="4242", course_name="Principles of Pretend Marketing", course_grade=71.0)
        ma = dict(course="MATH888", course_id="5151", course_name="Imaginary Calculus", course_grade=93.0)
        return [Assignment(id="canvas:4242:1", title="Case study", due=now + timedelta(hours=20), points=50, **mk),
                Assignment(id="canvas:4242:2", title="Pricing quiz", due=now + timedelta(hours=40), points=10, **mk),
                Assignment(id="canvas:5151:1", title="Problem set", due=now + timedelta(hours=30), points=20, **ma)]


def test_api_board_hides_by_course_id_with_its_grades():
    hc, _ = _hidden()
    board = AssignmentBoard(FakeApi(), None, NoChecks(), hidden=hc)
    b = board.load()
    assert any("71%" in a["reason"] for a in b["todo"])                         # the grade shows before
    hc.add(next(c for c in board.courses() if c.course_id == "4242"))
    b = board.load()
    assert [a["title"] for a in b["todo"]] == ["Problem set"]
    assert not any("71%" in a["reason"] or "MKTG" in a["reason"] for a in b["todo"])
    assert b["hidden"][0]["key"] == "canvas:4242"


# ---------------------------------------------------------------- to-dos: archived, not deleted, and restored
def test_todo_archive_hides_everywhere_and_restores_status(tmp_path):
    s = TodoStore(tmp_path / "monkey.db")
    now = datetime(2026, 11, 23, 10, 0)
    a = s.add("Read ch 4 for MKTG 777", due="2026-11-23T10:05", now=now)
    b = s.add("Marketing quiz review", now=now)
    s.complete(b["id"], now=now)
    keep = s.add("Call mom", due="2026-11-23T10:05", now=now)
    got = s.archive_for_course([a["id"], b["id"]], "code:mktg777")
    assert [t["status"] for t in got] == ["dropped", "dropped"]
    assert [t["id"] for t in s.items("all", now)] == [keep["id"]]
    assert s.items("open", now) == [s.get(keep["id"], now)] and s.items("done", now) == []
    assert [t["id"] for t in s.due_reminders(now)] == [keep["id"]]              # no reminder for the dropped one
    assert s.find("MKTG 777 reading", now) == [] and s.find(a["id"], now) == []
    assert s.counts(now)["open"] == 1
    assert {t["id"] for t in s.items("dropped", now)} == {a["id"], b["id"]}
    back = {t["id"]: t["status"] for t in s.restore_course("code:mktg777")}
    assert back == {a["id"]: "open", b["id"]: "done"}                         # exactly as they were
    assert s.get(a["id"], now)["dropped_course"] == "" and len(s.items("all", now)) == 3


# ---------------------------------------------------------------- the whole app: every surface, then Undo
class FakeCal:
    name = "calendar"

    def available(self):
        return True

    def list_events(self, start, end):
        out, day = [], start.replace(hour=0, minute=0, second=0, microsecond=0)
        while day < end:
            if day.weekday() < 5:
                for hhmm, title in (((9, 30), "MKTG 777 Lecture"), ((11, 0), "MATH 888 Lecture"),
                                    ((18, 0), "Marketing club meeting")):
                    st = day.replace(hour=hhmm[0], minute=hhmm[1])
                    if start <= st < end:
                        out.append(Event(id=f"{title}@{st.isoformat()}", source="ics", title=title, start=st,
                                         end=st + timedelta(minutes=50)))
            day += timedelta(days=1)
        return out


@pytest.fixture
def app(tmp_path, monkeypatch):
    from monkey import app as app_mod

    monkeypatch.setenv("APPDATA", str(tmp_path))
    a = app_mod.MonkeyApp(tmp_path / "Monkey", headless=True)
    a.cfg.settings.todo_windows_notify = False
    now = datetime.now(timezone.utc)
    a.board.feed = FakeFeed(_feed_events(now))
    a.canvas = a.board.feed
    a.ics_calendar = FakeCal()
    a.refresh_accounts()
    root = Path(a.memory.memory_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "classes.md").write_text("# Classes\n- MKTG 777 — Mon/Wed 8:00\n- MATH 888 — Mon/Wed 11:00\n",
                                     encoding="utf-8")
    return a, app_mod.Api(a)


def _todos(a):
    t = a.todos
    return {"read": t.add("Read ch 4 for MKTG 777", due=(datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")),
            "tag": t.add("Outline the launch plan", list="marketing"),
            "club": t.add("Email the marketing club about the bake sale"),
            "math": t.add("Study for MATH 888 midterm")}


def _text(x) -> str:
    return json.dumps(x, default=str)


def test_drop_hides_on_every_surface_and_undo_brings_it_all_back(app):
    from monkey.brain.tools import ToolRunner
    from monkey.routines.morning import TZ, Schedule, build, schedule_from_notes

    a, api = app
    todos = _todos(a)
    a.suggestions.record(account="gmail", message_id="m1", text="Submit the MKTG 777 case study",
                         subject="MKTG 777: case study due Friday")
    a.suggestions.record(account="gmail", message_id="m2", text="Pay the intramural fee", subject="Team fee")
    r = ToolRunner(a.services)
    r.begin_turn("what's due", ["what's due"])
    now = datetime.now(TZ).replace(hour=7, minute=0, second=0, microsecond=0)

    def surfaces():
        board = api.get_assignments(False)
        dash = api.dashboard()
        brief = build(now, Schedule(), a._brief_sources(), "draft").to_dict()
        return {
            "homework": [x["course"] for x in board["todo"] + board["done"]],
            "today": _text(dash["sections"]),
            "brief": _text(brief),
            "tool_assignments": r.run("get_assignments", {"include_done": True})[0],
            "tool_calendar": r.run("get_calendar", {"days_ahead": 7, "day": ""})[0],
            "suggestions": [s["text"] for s in a.suggestions.pending()],
            "todo_list": [t["text"] for t in a.todos.items("all")],
            "notes_schedule": schedule_from_notes(a._class_notes()),
            "candidates": api.brief_candidates(),
        }

    before = surfaces()
    assert "MKTG 777" in before["homework"] and "MKTG 777" in before["tool_assignments"]
    assert "MKTG 777" in before["tool_calendar"] and "MKTG 777" in before["brief"]
    assert len(before["suggestions"]) == 2 and before["notes_schedule"]["mon"]["time"] == "08:00"
    assert before["candidates"]["candidates"]["mon"]["title"] == "MKTG 777 Lecture"

    p = api.course_drop_preview("code:mktg777")
    assert p["ok"] and p["name"] == "MKTG 777" and p["assignments"] == 3
    assert sorted(t["text"] for t in p["todos"]) == ["Outline the launch plan", "Read ch 4 for MKTG 777"]
    assert api.course_drop("code:mktg777", "wrong")["ok"] is False                    # only the confirm's token
    d = api.course_drop("code:mktg777", p["token"])
    assert d["ok"] and d["say"] == "Removed 3 MKTG 777 assignments and 2 to-dos."
    assert api.course_drop("code:mktg777", p["token"])["ok"] is False                 # one use

    after = surfaces()
    assert "MKTG 777" not in after["homework"] and "MATH 888" in after["homework"]
    assert "MKTG 777" not in after["today"]
    assert "MKTG 777" not in after["brief"] and "MATH 888" in after["brief"]
    tool = json.loads(after["tool_assignments"])
    assert "MKTG 777" not in _text(tool["todo"] + tool["done"]) and "MATH 888" in _text(tool["todo"])
    assert "left out here on purpose" in tool["hidden_classes"]                     # so Monkey doesn't bring it up
    assert "MKTG 777" not in after["tool_calendar"] and "Marketing club meeting" in after["tool_calendar"]
    assert after["suggestions"] == ["Pay the intramural fee"] and a.suggestions.count_pending() == 1
    assert "Read ch 4 for MKTG 777" not in after["todo_list"] and "Outline the launch plan" not in after["todo_list"]
    assert "Email the marketing club about the bake sale" in after["todo_list"]      # the near miss stays
    assert after["notes_schedule"]["mon"]["time"] == "11:00"
    assert after["candidates"]["candidates"]["mon"] == {"time": "11:00", "title": "MATH 888 Lecture", "seen": 2} or \
        after["candidates"]["candidates"]["mon"]["title"] == "MATH 888 Lecture"
    # reminders: the archived to-do due in 5 minutes doesn't nudge
    fired = a.todo_tick(datetime.now() + timedelta(minutes=1))
    assert todos["read"]["id"] not in [f["id"] for f in fired]
    # memory: one line through the fact path, never the course list
    classes = (Path(a.memory.memory_root) / "classes.md").read_text(encoding="utf-8")
    assert "Dropped MKTG 777 on" in classes
    hidden = api.hidden_courses()["items"]
    assert hidden == [{"key": "code:mktg777", "name": "MKTG 777", "full": "", "hidden_at": hidden[0]["hidden_at"],
                       "assignments": 3, "todos": 2}]
    assert a.cfg.settings.hidden_courses[0]["key"] == "code:mktg777"
    api.save_settings({"hidden_courses": []})                                         # only through drop/undrop
    assert a.cfg.settings.hidden_courses

    back = api.course_undrop("code:mktg777")
    assert back["ok"] and back["assignments"] == 3 and len(back["todos"]) == 2
    again = surfaces()
    for k in ("homework", "tool_assignments", "tool_calendar", "brief"):
        assert "MKTG 777" in _text(again[k]), k
    assert len(again["suggestions"]) == 2 and "Read ch 4 for MKTG 777" in again["todo_list"]
    assert "Dropped MKTG 777" not in (Path(a.memory.memory_root) / "classes.md").read_text(encoding="utf-8")
    assert api.hidden_courses()["items"] == [] and api.course_undrop("code:mktg777")["ok"] is False


def test_brief_cached_today_follows_a_drop(app):
    import time

    a, api = app
    a.cfg.settings.brief_enabled = True
    a._last_brief = {"day": "x", "sections": []}
    seen = []
    a.morning.run = lambda now, trigger, rebuild=False: seen.append((trigger, rebuild)) or {"day": "y", "sections": []}
    events = []
    a._emit = lambda e, p: events.append(e)
    p = api.course_drop_preview("code:mktg777")
    api.course_drop("code:mktg777", p["token"])
    for _ in range(50):
        if "courses_changed" in events:
            break
        time.sleep(0.05)
    assert ("app_open", True) in seen and a._last_brief == {"day": "y", "sections": []} and "courses_changed" in events


# ---------------------------------------------------------------- the brain tools: confirm first, the user's words
def _runner(a, said):
    from monkey.brain.tools import ToolRunner

    events = []
    a.services.emit = lambda e, p: events.append((e, p))
    r = ToolRunner(a.services)
    r.begin_turn(said[-1], said)
    return r, events


def test_drop_course_tool_asks_then_hides_only_after_a_yes(app):
    a, _ = app
    _todos(a)
    r, events = _runner(a, ["I dropped marketing"])
    out, err = r.run("drop_course", {"course": "marketing", "confirmed": False})
    got = json.loads(out)
    assert not err and got["ask_user"] == "Hide MKTG 777 everywhere? 3 assignments, 2 to-dos."
    assert events[-1][0] == "course_drop_confirm" and events[-1][1]["token"]          # the card's token: UI only
    assert "token" not in out and not a.hidden_courses.entries()
    out, _ = r.run("drop_course", {"course": "marketing", "confirmed": True})         # no yes yet
    assert out.startswith("Not hidden") and not a.hidden_courses.entries()
    r.begin_turn("no wait, keep it", ["I dropped marketing", "no wait, keep it"])
    out, _ = r.run("drop_course", {"course": "MKTG 777", "confirmed": True})
    assert out.startswith("Not hidden") and not a.hidden_courses.entries()
    r.begin_turn("yeah hide it", ["I dropped marketing", "no wait, keep it", "yeah hide it"])
    out, _ = r.run("drop_course", {"course": "MKTG 777", "confirmed": True})
    assert out.startswith("Done: Removed 3 MKTG 777 assignments and 2 to-dos.")
    assert events[-1][0] == "course_dropped" and a.hidden_courses.find("code:mktg777")
    out, _ = r.run("drop_course", {"course": "marketing", "confirmed": False})
    assert "already hidden" in out
    r.begin_turn("show marketing again", ["show marketing again"])
    out, _ = r.run("undrop_course", {"course": "marketing"})
    assert out.startswith("MKTG 777 is back") and events[-1][0] == "course_restored"
    assert not a.hidden_courses.entries()


def test_drop_course_tool_needs_the_users_own_words_and_asks_which(app):
    a, _ = app
    r, _ = _runner(a, ["what's due this week"])
    out, _ = r.run("drop_course", {"course": "MATH 888", "confirmed": False})    # e.g. text inside an assignment
    assert out.startswith("Not changed") and not a.hidden_courses.entries()
    r, events = _runner(a, ["I dropped mathematics"])
    out, _ = r.run("drop_course", {"course": "mathematics", "confirmed": False})
    assert json.loads(out)["class"] == "MATH 888"                                   # never the marketing class
    r, _ = _runner(a, ["I dropped history"])
    out, _ = r.run("drop_course", {"course": "history", "confirmed": False})
    assert out.startswith("No class matching") and "MKTG 777" in out
    # two marketing classes: ask which
    now = datetime.now(timezone.utc)
    a.board.feed.events.append(Event(id="event-assignment-9", source="canvas", title="Brand plan [MKTG_778_001_F26]",
                                     start=now + timedelta(hours=70)))
    a.board.load(refresh=True)
    r, _ = _runner(a, ["I dropped marketing"])
    out, _ = r.run("drop_course", {"course": "marketing", "confirmed": False})
    assert out.startswith("Which one?") and "MKTG 777" in out and "MKTG 778" in out


def test_tool_confirm_expires_and_ui_token_is_separate(app):
    a, api = app
    r, events = _runner(a, ["I dropped marketing"])
    r.run("drop_course", {"course": "marketing", "confirmed": False})
    token = events[-1][1]["token"]
    assert api.course_drop("code:mktg777", token)["ok"]                            # the card's Hide button
    r.begin_turn("yes", ["I dropped marketing", "yes"])
    out, _ = r.run("drop_course", {"course": "marketing", "confirmed": True})
    assert "already hidden" in out                                                 # never twice
    api.course_undrop("code:mktg777")
    r2, _ = _runner(a, ["I dropped marketing"])
    r2.run("drop_course", {"course": "marketing", "confirmed": False})
    key, tok, at = r2._course_pending
    r2._course_pending = (key, tok, at - 3600)                                     # an hour later
    r2.begin_turn("yes", ["I dropped marketing", "yes"])
    out, _ = r2.run("drop_course", {"course": "marketing", "confirmed": True})
    assert "ask_user" in out and not a.hidden_courses.entries()                    # asks again instead


# ---------------------------------------------------------------- routing
@pytest.mark.parametrize("text", ["I dropped marketing", "remove all my marketing assignments", "hide the marketing class",
                                  "I just dropped MKTG 777", "i'm not taking marketing anymore", "show marketing again",
                                  "unhide marketing", "bring back my marketing class", "what classes are hidden",
                                  "get rid of the marketing homework", "I've dropped out of marketing"])
def test_drop_phrases_route_to_course_drop(text):
    from monkey.brain.router import rule_task

    assert rule_task(text)[0] == "course_drop"


@pytest.mark.parametrize("text,task", [("I dropped my phone", None), ("delete the history assignment", "assignments"),
                                       ("remove the dentist to-do", "todo"), ("remove the old assignments", "assignments"),
                                       ("show the weather again", "weather"), ("my grade dropped like crazy", None),
                                       ("the temperature dropped below zero", None), ("show me my class schedule", "command"),
                                       ("what's due tomorrow", "assignments"), ("clear my to-do list", "todo")])
def test_near_misses_dont_route_there(text, task):
    from monkey.brain.router import rule_task

    assert rule_task(text)[0] == task


def test_policy_classifier_calibration_and_tools_know_the_task():
    from monkey.brain.calibrate import FAKE, SAMPLES
    from monkey.brain.policy import ModelPolicy
    from monkey.brain.router import CLASSIFIER_TASKS
    from monkey.brain.tools import LOCAL_TOOLS

    assert ModelPolicy().has("course_drop") and "course_drop" in CLASSIFIER_TASKS and "course_drop" in SAMPLES
    assert {"drop_course", "undrop_course"} <= set(FAKE) <= {t["name"] for t in LOCAL_TOOLS} | set(FAKE)
    assert {"drop_course", "undrop_course"} <= {t["name"] for t in LOCAL_TOOLS}
    persona = (Path(__file__).resolve().parents[1] / "monkey" / "brain" / "persona.md").read_text(encoding="utf-8")
    assert "drop_course" in persona and "undrop_course" in persona


def test_dropper_without_canvas_or_memory_is_harmless(tmp_path):
    rows: list = []
    hc = HiddenCourses(lambda: rows, lambda r: (rows.clear(), rows.extend(r)))
    d = CourseDropper(hc, None)
    assert d.courses() == [] and d.preview("code:x")["ok"] is False and d.undrop("code:x")["ok"] is False
    board = NS(courses=lambda refresh=False: courses_from_items([{"course": "MKTG 777"}]), items_for=lambda k: [1])
    d = CourseDropper(hc, board)
    p = d.preview("code:mktg777")
    assert p["ok"] and d.drop("code:mktg777", p["token"])["ok"] and hc.find("code:mktg777")["fact_id"] == ""

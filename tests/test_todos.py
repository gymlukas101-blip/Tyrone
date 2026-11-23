"""The to-do list: the store in monkey.db, due-date parsing, the brain tools and their gates, reminders, the morning
brief, and routing. (The panel itself: tests/test_todo_ui.py.)"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from monkey.brain.approval import ApprovalGate
from monkey.brain.tools import STRICT_TOOLS, TODO_TOOLS, Services, ToolRunner
from monkey.memory.todos import TodoStore, due_datetime, is_overdue, normalize_due, split_quick, when_text

CASES = json.loads((Path(__file__).parent / "todo_due_cases.json").read_text(encoding="utf-8"))
MON = datetime(2026, 11, 23, 10, 0)            # a Monday morning, local time


# ---------------------------------------------------------------- parsing
@pytest.mark.parametrize("case", CASES["cases"], ids=[c["in"] for c in CASES["cases"]])
def test_quick_add_parsing_matches_the_shared_cases(case):
    q = split_quick(case["in"], datetime.fromisoformat(CASES["now"]))
    assert (q.text, q.due, q.priority, q.list) == (case["text"], case["due"], case["priority"], case["list"])


@pytest.mark.parametrize("text", ["take 2 a day", "go out in the sun", "may the best one win", "read chapter 5",
                                  "wed planning doc", "sat with the TA"])
def test_ordinary_words_are_not_read_as_dates(text):
    """Near-misses: words that look like dates or times stay part of the text."""
    q = split_quick(text, MON)
    assert q.due is None and q.text == text


def test_normalize_due_accepts_iso_phrases_and_clearing():
    assert normalize_due("2026-12-01", MON) == "2026-12-01"
    assert normalize_due("2026-12-01T17:30:00", MON) == "2026-12-01T17:30"
    assert normalize_due("friday 3pm", MON) == "2026-11-27T15:00"
    for empty in ("", "none", "  ", None):
        assert normalize_due(empty, MON) is None
    aware = datetime(2026, 12, 1, 23, 0).astimezone()            # this PC's zone, with its own DST rules
    assert normalize_due(aware.isoformat(), MON) == "2026-12-01T23:00"          # an offset is shown in local time
    with pytest.raises(ValueError):
        normalize_due("whenever I feel like it", MON)


def test_overdue_logic_day_items_last_until_midnight():
    assert is_overdue({"status": "open", "due": "2026-11-23T09:59"}, MON)
    assert not is_overdue({"status": "open", "due": "2026-11-23T10:01"}, MON)
    assert not is_overdue({"status": "open", "due": "2026-11-23"}, MON)            # due today: not late yet
    assert is_overdue({"status": "open", "due": "2026-11-22"}, MON)
    assert not is_overdue({"status": "done", "due": "2026-11-22"}, MON)
    assert not is_overdue({"status": "open", "due": None}, MON)
    assert due_datetime("2026-11-23") == datetime(2026, 11, 23, 23, 59, 59)
    assert when_text("2026-11-24T17:00", MON) == "tomorrow 5:00 PM"
    assert when_text("2026-11-22", MON) == "overdue since yesterday"


# ---------------------------------------------------------------- store
def test_crud_sort_filters_and_persistence_across_reopen(tmp_path):
    db = tmp_path / "monkey.db"
    st = TodoStore(db)
    a = st.add("Email the TA", due="2026-11-22T17:00", priority="high", list="school", source="voice", now=MON)
    b = st.add("Pick up package", due="today 4:30pm", now=MON)
    c = st.add("Call the dentist", priority="low", steps=["Find the number", "Call"], now=MON)
    assert b["due"] == "2026-11-23T16:30" and a["overdue"] and not b["overdue"]
    assert [s["text"] for s in c["steps"]] == ["Find the number", "Call"] and c["source"] == "typed"
    assert [t["text"] for t in st.items("open", MON)] == ["Email the TA", "Pick up package", "Call the dentist"]
    assert [t["text"] for t in st.items("open", MON, sort="priority")][0] == "Email the TA"
    assert [t["id"] for t in st.items("overdue", MON)] == [a["id"]]
    assert {t["id"] for t in st.items("today", MON)} == {a["id"], b["id"]}

    st.complete(b["id"], now=MON)
    st.set_step(c["id"], 0, True, now=MON)
    st.update(c["id"], MON, text="Call the dentist about a cleaning", due="friday")
    st2 = TodoStore(db)                                                   # a restart: everything is still there
    assert [t["text"] for t in st2.items("done", MON)] == ["Pick up package"]
    got = st2.get(c["id"], MON)
    assert got["text"] == "Call the dentist about a cleaning" and got["due"] == "2026-11-27"
    assert got["steps"][0]["done"] and not got["steps"][1]["done"]
    assert st2.counts(MON) == {"open": 2, "overdue": 1, "today": 0}
    st2.complete(b["id"], False, now=MON)
    assert st2.get(b["id"], MON)["status"] == "open" and st2.get(b["id"], MON)["done_at"] is None


def test_delete_is_undoable_and_old_deletions_are_purged(tmp_path):
    db = tmp_path / "monkey.db"
    st = TodoStore(db)
    t = st.add("Return library books", now=MON)
    st.delete(t["id"])
    assert st.get(t["id"]) is None and st.items("all", MON) == []
    assert st.restore(t["id"])["text"] == "Return library books"
    st.delete(t["id"])
    with sqlite3.connect(db) as c:                                        # deleted 31 days ago
        c.execute("UPDATE todos SET deleted_at=deleted_at-31*86400")
    TodoStore(db)
    with pytest.raises(KeyError):
        st.restore(t["id"])


def test_validation(tmp_path):
    st = TodoStore(tmp_path / "monkey.db")
    with pytest.raises(ValueError):
        st.add("   ")
    t = st.add("Something", priority="urgent!!", source="email")          # unknown values fall back safely
    assert t["priority"] == "normal" and t["source"] == "typed"
    with pytest.raises(KeyError):
        st.update("nope", text="x")
    with pytest.raises(ValueError):
        st.update(t["id"], text=" ")


def test_find_by_id_or_words(tmp_path):
    st = TodoStore(tmp_path / "monkey.db")
    a = st.add("Do laundry", now=MON)
    b = st.add("Finish the CS 400 project proposal", now=MON)
    st.add("Finish the reading for PSYCH", now=MON)
    assert [t["id"] for t in st.find(a["id"])] == [a["id"]]
    assert [t["id"] for t in st.find("laundry")] == [a["id"]]
    assert [t["id"] for t in st.find("the proposal")] == [b["id"]]
    assert len(st.find("finish")) == 2                                     # ambiguous: both come back
    assert st.find("groceries") == []


def test_migration_adds_missing_columns_to_an_older_table(tmp_path):
    db = tmp_path / "monkey.db"
    with sqlite3.connect(db) as c:                                        # an imagined older version of the table
        c.execute("CREATE TABLE todos(id TEXT PRIMARY KEY, text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', "
                  "created REAL, updated REAL)")
        c.execute("INSERT INTO todos(id, text, status, created, updated) VALUES ('old1', 'Old item', 'open', 1, 1)")
        c.execute("CREATE TABLE spend(x)")                                # other tables in monkey.db are untouched
    st = TodoStore(db)
    got = st.get("old1", MON)
    assert got["text"] == "Old item" and got["steps"] == [] and got["priority"] == "normal" and got["due"] is None
    st.update("old1", MON, due="tomorrow", steps=["one"])
    assert st.get("old1", MON)["due"] == "2026-11-24"
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM sqlite_master WHERE name='spend'").fetchone()[0] == 1


def test_reminders_fire_once_per_due_time_and_snooze_brings_them_back(tmp_path):
    st = TodoStore(tmp_path / "monkey.db")
    t = st.add("Call mom", due="2026-11-23T10:15", now=MON)
    st.add("No time on this one", due="2026-11-23", now=MON)               # day-only items never nudge
    assert st.due_reminders(MON, lead_min=10) == []                       # 15 min away, lead is 10
    at = MON + timedelta(minutes=6)
    assert [r["id"] for r in st.due_reminders(at, 10)] == [t["id"]]
    st.mark_reminded(t["id"])
    assert st.due_reminders(at, 10) == []                                 # once
    st.snooze(t["id"], 10)
    import time as _t

    assert st.due_reminders(datetime.fromtimestamp(_t.time() + 11 * 60), 10)    # back after the snooze
    st.mark_reminded(t["id"])
    st.update(t["id"], at, due="2026-11-23T12:00")                         # a new due time reminds again
    assert [r["id"] for r in st.due_reminders(datetime(2026, 11, 23, 11, 55), 10)] == [t["id"]]
    assert st.due_reminders(datetime(2026, 11, 23, 15, 0), 10) == []       # long past due: the brief covers it
    st.complete(t["id"], now=at)
    assert st.due_reminders(datetime(2026, 11, 23, 11, 55), 10) == []


# ---------------------------------------------------------------- brain tools
def runner(tmp_path, said: list[str], untrusted: set[str] | None = None):
    events = []
    st = TodoStore(tmp_path / "monkey.db")
    r = ToolRunner(Services(emit=lambda e, p: events.append((e, p)), memory=None, approval=ApprovalGate({}),
                            open_url=lambda u: None, todos=st))
    r.begin_turn(said[-1], said)
    r.untrusted = set(untrusted or ())
    return r, st, events


def test_tool_schemas_are_strict_where_they_write():
    names = {t["name"] for t in TODO_TOOLS}
    assert names == {"add_todo", "list_todos", "update_todo", "delete_todo"}
    assert {"add_todo", "update_todo", "delete_todo"} <= STRICT_TOOLS and len(STRICT_TOOLS) <= 20
    for t in TODO_TOOLS:
        schema = t["input_schema"]
        assert set(schema["required"]) == set(schema["properties"]) and schema["additionalProperties"] is False
    help_text = next(t for t in TODO_TOOLS if t["name"] == "update_todo")["description"]
    assert "draft_email" in help_text and "Never send" in help_text and "propose_computer_task" in help_text


def test_add_when_asked_with_due_from_a_phrase(tmp_path):
    r, st, events = runner(tmp_path, ["remind me to call the dentist tomorrow at 5"])
    out, err = r.run("add_todo", {"text": "Call the dentist", "due": "tomorrow at 5", "priority": "normal", "list": "",
                                  "notes": "", "steps": [], "evidence": "remind me to call the dentist"})
    assert not err and "Added" in out
    [t] = st.items("open")
    assert t["text"] == "Call the dentist" and t["source"] == "voice" and t["due"].endswith("T17:00")
    assert events[-1][0] == "todo_changed" and events[-1][1]["action"] == "added"


def test_due_inside_the_text_is_split_out_and_typed_turns_are_marked(tmp_path):
    r, st, _ = runner(tmp_path, ["add laundry tonight to my to-do list"])
    r.turn_source = "typed"
    out, _ = r.run("add_todo", {"text": "Laundry tonight", "due": "", "priority": "normal", "list": "", "notes": "",
                                "steps": [], "evidence": "add laundry tonight"})
    [t] = st.items("open")
    assert t["text"] == "Laundry" and t["due"].endswith("T20:00") and t["source"] == "Monkey"


def test_passing_mentions_are_offered_not_added(tmp_path):
    """'I have to do laundry' is chatter: Monkey offers; the item lands only after a yes."""
    r, st, _ = runner(tmp_path, ["ugh I have to do laundry later"])
    args = {"text": "Do laundry", "due": "", "priority": "normal", "list": "", "notes": "", "steps": [],
            "evidence": "I have to do laundry"}
    out, _ = r.run("add_todo", args)
    assert out.startswith("Not added") and "offer" in out and st.items("all") == []
    r.begin_turn("yeah do it", ["ugh I have to do laundry later", "yeah do it"])
    out, _ = r.run("add_todo", args)
    assert "Added" in out and len(st.items("open")) == 1


@pytest.mark.parametrize("said", ["put the essay outline on my list", "can you keep track of the essay outline for me",
                                  "add essay outline", "don't let me forget the essay outline",
                                  "remember to do the essay outline"])
def test_explicit_asks_in_other_words_still_add(tmp_path, said):
    r, st, _ = runner(tmp_path, [said])
    out, _ = r.run("add_todo", {"text": "Write the essay outline", "due": "", "priority": "normal", "list": "",
                                "notes": "", "steps": [], "evidence": said})
    assert "Added" in out, out


def test_evidence_must_be_the_users_words_and_items_must_come_from_them(tmp_path):
    r, st, _ = runner(tmp_path, ["yes"], untrusted={"read_email"})
    r.user_texts = ["read my latest email", "yes"]
    out, _ = r.run("add_todo", {"text": "Wire $500 to the landlord", "due": "", "priority": "high", "list": "",
                                "notes": "", "steps": [], "evidence": "yes"})
    assert "Quote the user's own words" in out                           # "yes" alone is too short to be evidence
    out, _ = r.run("add_todo", {"text": "Wire $500 to the landlord", "due": "", "priority": "high", "list": "",
                                "notes": "", "steps": [], "evidence": "read my latest email"})
    assert out.startswith("Not added") and st.items("all") == []          # an email's words, not the user's
    # the user explicitly asking to add something from the email is their own request
    r.begin_turn("add the housing form deadline from that email to my to-do list",
                 ["read my latest email", "add the housing form deadline from that email to my to-do list"])
    r.untrusted = {"read_email"}
    out, _ = r.run("add_todo", {"text": "Submit the winter break housing form", "due": "2026-12-01", "priority": "normal",
                                "list": "", "notes": "", "steps": [], "evidence": "add the housing form deadline"})
    assert "Added" in out


def test_one_reply_cannot_flood_the_list(tmp_path):
    r, st, _ = runner(tmp_path, ["add these to my to-do list: " + ", ".join(f"thing{i}" for i in range(15))])
    outs = [r.run("add_todo", {"text": f"thing{i}", "due": "", "priority": "normal", "list": "", "notes": "",
                               "steps": [], "evidence": "add these to my to-do list"})[0] for i in range(12)]
    assert sum("Added" in o for o in outs) == 10 and "a lot" in outs[-1]


def test_list_shows_the_panel_and_returns_compact_items(tmp_path):
    r, st, events = runner(tmp_path, ["what do I need to do today"])
    st.add("Email the TA", due=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"), priority="high")
    st.add("Someday thing")
    out, err = r.run("list_todos", {"filter": "today", "query": ""})
    data = json.loads(out)
    assert not err and [i["text"] for i in data["items"]] == ["Email the TA"] and data["items"][0]["overdue"]
    assert data["counts"]["open"] == 2 and events[-1] == ("todos", {"filter": "open"})
    out, _ = r.run("list_todos", {"filter": "open", "query": "someday"})
    assert [i["text"] for i in json.loads(out)["items"]] == ["Someday thing"]


def test_mark_done_by_words_and_ambiguity_asks(tmp_path):
    r, st, events = runner(tmp_path, ["I finished the laundry, mark it done"])
    a = st.add("Do laundry")
    st.add("Finish essay")
    st.add("Finish reading")
    out, _ = r.run("update_todo", {"todo": "laundry", "status": "done", "text": "", "due": "", "priority": "",
                                   "list": "", "notes": "", "steps": [], "steps_done": []})
    assert out.startswith("Marked done") and st.get(a["id"])["status"] == "done"
    assert events[-1][1]["action"] == "done"
    out, _ = r.run("update_todo", {"todo": "finish", "status": "done", "text": "", "due": "", "priority": "",
                                   "list": "", "notes": "", "steps": [], "steps_done": []})
    assert out.startswith("Which one?") and "Finish essay" in out and "Finish reading" in out


def test_help_saves_steps_and_ticks_them_off(tmp_path):
    r, st, _ = runner(tmp_path, ["help me get the scholarship application done"])
    t = st.add("Finish the scholarship application", due="friday")
    steps = ["Find the application portal", "Ask Prof. Lee for a recommendation", "Write the 500-word essay",
             "Submit before Friday"]
    out, _ = r.run("update_todo", {"todo": t["id"], "status": "", "text": "", "due": "", "priority": "", "list": "",
                                   "notes": "", "steps": steps, "steps_done": []})
    assert "0/4 done; next: Find the application portal" in out
    r.begin_turn("ok found the portal", ["help me get the scholarship application done", "ok found the portal"])
    out, _ = r.run("update_todo", {"todo": t["id"], "status": "", "text": "", "due": "", "priority": "", "list": "",
                                   "notes": "", "steps": [], "steps_done": [1, 9]})
    assert "1/4 done" in out and "[9] don't exist" in out
    # replacing the steps keeps the ticks on the ones that stayed
    out, _ = r.run("update_todo", {"todo": t["id"], "status": "", "text": "", "due": "", "priority": "", "list": "",
                                   "notes": "", "steps": steps[:1] + ["Draft the essay"], "steps_done": []})
    assert [s["done"] for s in st.get(t["id"])["steps"]] == [True, False]


def test_outside_content_cannot_change_the_list_without_the_users_ask(tmp_path):
    r, st, _ = runner(tmp_path, ["what does it say"], untrusted={"read_email"})
    t = st.add("Pay rent")
    args = {"todo": t["id"], "status": "done", "text": "", "due": "", "priority": "", "list": "", "notes": "",
            "steps": [], "steps_done": []}
    out, _ = r.run("update_todo", args)
    assert out.startswith("Not changed") and st.get(t["id"])["status"] == "open"
    r.begin_turn("ok mark rent done", ["what does it say", "ok mark rent done"])
    r.untrusted = {"read_email"}
    assert r.run("update_todo", args)[0].startswith("Marked done")


def test_delete_only_on_a_clear_request(tmp_path):
    r, st, events = runner(tmp_path, ["I'm done with the dentist thing"])
    t = st.add("Call the dentist")
    out, _ = r.run("delete_todo", {"todo": "dentist", "evidence": "I'm done with the dentist thing"})
    assert out.startswith("Not deleted") and st.get(t["id"]) is not None
    r.begin_turn("actually remove the dentist one from my list", ["actually remove the dentist one from my list"])
    out, _ = r.run("delete_todo", {"todo": "dentist", "evidence": "remove the dentist one from my list"})
    assert out.startswith("Deleted") and st.get(t["id"]) is None and events[-1][1]["action"] == "deleted"
    assert st.restore(t["id"])["text"] == "Call the dentist"              # the on-screen Undo


def test_tools_say_so_when_the_list_is_missing(tmp_path):
    r = ToolRunner(Services(emit=lambda *a: None, memory=None, approval=ApprovalGate({})))
    r.begin_turn("add milk to my list", ["add milk to my list"])
    for name, args in [("list_todos", {"filter": "open", "query": ""}), ("delete_todo", {"todo": "x", "evidence": "x"})]:
        assert "isn't available" in r.run(name, args)[0]


def test_agent_loop_adds_then_helps_through_existing_tools_only(tmp_path):
    """A full voice turn with the fake client: add, then "help me" saves steps and opens a site. Nothing is sent."""
    from monkey.brain.agent import Agent
    from monkey.brain.costs import Ledger
    from monkey.brain.router import Router
    from monkey.memory.store import MonkeyMemory
    from tests.test_agent_loop import FakeClient, text_block, tool_block

    events, spoken, opened = [], [], []
    st = TodoStore(tmp_path / "monkey.db")
    mem = MonkeyMemory(tmp_path / "memory")
    services = Services(emit=lambda e, p: events.append((e, p)), memory=mem, approval=ApprovalGate({}),
                        open_url=opened.append, todos=st)
    add = {"text": "Renew my passport", "due": "", "priority": "high", "list": "", "notes": "", "steps": [],
           "evidence": "add renew my passport to my to-do list"}
    script = [
        ([tool_block("add_todo", add, "a")], "tool_use"),
        ([text_block("Got it, it's on your list.")], "end_turn"),
        ([tool_block("list_todos", {"filter": "open", "query": "passport"}, "b")], "tool_use"),
        ([tool_block("update_todo", {"todo": "passport", "status": "", "text": "", "due": "", "priority": "",
                                     "list": "", "notes": "", "steps": ["Fill in the DS-82 form", "Get a photo",
                                                                        "Mail it in"], "steps_done": []}, "c"),
          tool_block("open_website", {"target": "travel.state.gov"}, "d")], "tool_use"),
        ([text_block("Step one: fill in the renewal form. I opened the site for you.")], "end_turn"),
    ]
    client = FakeClient(script)
    agent = Agent(client, Router(), ToolRunner(services), mem, Ledger(tmp_path / "t.db"),
                  emit=lambda e, p: events.append((e, p)), speak=spoken.append)
    agent.handle("add renew my passport to my to-do list")
    agent.handle("help me get the passport thing done")
    [t] = st.items("open")
    assert t["source"] == "voice" and t["priority"] == "high"
    assert [s["text"] for s in t["steps"]] == ["Fill in the DS-82 form", "Get a photo", "Mail it in"]
    assert opened == ["https://travel.state.gov"]
    assert {"add_todo", "list_todos", "update_todo", "delete_todo"} <= {x["name"] for x in client.calls[0]["tools"]}
    assert not any(name in ("draft", "approval") for name, _ in events)           # nothing outward happened
    assert client.calls[0]["model"] and "todo" in [e[1].get("reason", "") for e in events if e[0] == "route"][0]


# ---------------------------------------------------------------- routing
@pytest.mark.parametrize("text", ["add buy groceries to my to-do list", "remind me to call mom at 5",
                                  "what's on my todo list", "what do I need to do today",
                                  "add 'email my TA' to my to-do list", "take the laundry off my list"])
def test_router_sends_todo_phrases_to_the_todo_task(text):
    from monkey.brain.router import rule_task

    assert rule_task(text)[0] == "todo"


@pytest.mark.parametrize("text,task", [("what's on my canvas to-do", "assignments"), ("check off the CS 400 project", "check_off"),
                                       ("draft an email to my professor", "draft_email")])
def test_router_keeps_other_tasks(text, task):
    from monkey.brain.router import rule_task

    assert rule_task(text)[0] == task


def test_policy_and_calibration_know_the_todo_task():
    from monkey.brain.calibrate import FAKE, SAMPLES
    from monkey.brain.policy import ModelPolicy
    from monkey.brain.router import CLASSIFIER_TASKS

    p = ModelPolicy()
    assert p.has("todo") and "todo" in CLASSIFIER_TASKS and "todo" in SAMPLES
    assert {"add_todo", "list_todos", "update_todo", "delete_todo"} <= set(FAKE)


# ---------------------------------------------------------------- reminders in the app
def _app(tmp_path, **settings):
    from monkey.app import MonkeyApp

    events, said = [], []
    st = NS(todo_reminders=True, todo_speak_reminders=False, todo_reminder_lead_min=10)
    st.__dict__.update(settings)
    app = NS(cfg=NS(settings=st), todos=TodoStore(tmp_path / "monkey.db"), speaker=None, _listening=False,
             _agent_state="idle", _emit=lambda e, p: events.append((e, p)), _say=said.append)
    return app, events, said, (lambda now=None: MonkeyApp.todo_tick(app, now))


def test_reminder_tick_nudges_on_screen_once_and_never_outward(tmp_path):
    app, events, said, tick = _app(tmp_path)
    t = app.todos.add("Call mom", due="2026-11-23T10:05", now=MON)
    assert [x["id"] for x in tick(MON)] == [t["id"]]
    assert events == [("todo_reminder", {"item": events[0][1]["item"]})] and said == []     # quiet by default
    assert tick(MON) == [] and len(events) == 1
    (tmp_path / "off").mkdir()
    app2, ev2, said2, tick2 = _app(tmp_path / "off", todo_reminders=False)
    app2.todos.add("Call mom", due="2026-11-23T10:05", now=MON)
    assert tick2(MON) == [] and ev2 == []


def test_spoken_reminder_is_opt_in_and_waits_for_quiet(tmp_path):
    app, events, said, tick = _app(tmp_path, todo_speak_reminders=True)
    app.todos.add("Call mom", due="2026-11-23T10:05", now=MON)
    app._agent_state = "thinking"                                         # mid-reply: no talking over himself
    tick(MON)
    assert said == [] and len(events) == 1
    app.todos.add("Start laundry", due="2026-11-23T10:08", now=MON)
    app._agent_state = "idle"
    tick(MON)
    assert said == ["Heads up: Start laundry, today 10:08 AM."]


def test_api_round_trip(tmp_path):
    from monkey.app import Api

    app, *_ = _app(tmp_path)
    api = Api(app)
    r = api.todo_add({"text": "Buy milk", "due": "2026-11-24T09:00", "priority": "low", "list": "", "notes": "",
                      "steps": [{"text": "Check the fridge", "done": False}]})
    assert r["ok"] and r["item"]["source"] == "typed"
    tid = r["item"]["id"]
    assert api.todo_update(tid, {"status": "done", "id": "hacked"})["item"]["status"] == "done"
    assert api.todo_delete(tid)["ok"] and api.todo_restore(tid)["ok"]
    listed = api.todo_list()
    assert listed["ok"] and [i["id"] for i in listed["items"]] == [tid] and listed["settings"] == {"reminders": True,
                                                                                                  "speak": False}
    assert api.todo_update("nope", {"text": "x"})["ok"] is False
    assert api.todo_add({"text": " "})["ok"] is False


# ---------------------------------------------------------------- morning brief
def test_morning_brief_lists_overdue_and_today_and_names_the_top_one():
    from monkey.routines.morning import TZ, Schedule, Sources, build

    now = datetime(2026, 11, 23, 7, 30, tzinfo=TZ)
    local = now.astimezone().replace(tzinfo=None)
    day = local.date()
    todos = [
        {"text": "Email the TA", "due": (day - timedelta(days=1)).isoformat(), "priority": "high", "status": "open"},
        {"text": "Pick up package", "due": f"{day.isoformat()}T23:00", "priority": "normal", "status": "open"},
        {"text": "Plan spring schedule", "due": None, "priority": "high", "status": "open"},
        {"text": "Someday thing", "due": None, "priority": "low", "status": "open"},
    ]
    b = build(now, Schedule(), Sources(todos=lambda: todos, weather=lambda: {"summary": "Cloudy"}), "draft").to_dict()
    sec = next(s for s in b["sections"] if s["title"] == "To-do")
    assert sec["status"] == "warn"
    assert sec["items"][0].startswith("Email the TA (overdue, was due yesterday")
    assert sec["items"][1] == "Pick up package (today 11:00 PM)"
    assert sec["items"][2] == "Plan spring schedule (high priority)"
    assert "4 open, 1 overdue, 1 more in To-do." == sec["note"]
    assert b["top"].startswith("Email the TA (to-do")                    # no Canvas deadlines: the to-do leads
    assert "Top of your to-do list: Email the TA." in b["spoken"]


def test_morning_brief_without_todos_or_with_nothing_due():
    from monkey.routines.morning import TZ, Schedule, Sources, build

    now = datetime(2026, 11, 23, 7, 30, tzinfo=TZ)
    b = build(now, Schedule(), Sources(todos=lambda: []), "draft").to_dict()
    assert not any(s["title"] == "To-do" for s in b["sections"])
    b = build(now, Schedule(), Sources(todos=lambda: [{"text": "x", "due": None, "priority": "normal",
                                                        "status": "open"}]), "draft").to_dict()
    sec = next(s for s in b["sections"] if s["title"] == "To-do")
    assert sec["status"] == "empty" and sec["note"] == "1 open, nothing due today."
    b = build(now, Schedule(), Sources(), "draft").to_dict()             # not wired at all: no section, no error
    assert not any(s["title"] == "To-do" for s in b["sections"])

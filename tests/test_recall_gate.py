"""Milestone 5: a labelled recall set. Every case says what automatic recall should inject, or that it shouldn't.

Fake, redacted fixtures only (public repo)."""
from __future__ import annotations

import pytest

from monkey.memory.history import HistoryStore
from monkey.memory.recall_gate import select, should_recall
from monkey.memory.store import MonkeyMemory

FILES = {
    "projects.md": """# Projects
## Comet Quest (game)
- Comet Quest is a 3v3 racing game; ranked mode ships before survival mode.
## Comet Club (student org)
- Comet Club is the astronomy club; it meets Thursdays at 7 PM in the observatory.
""",
    "classes.md": """# Classes
- Statistics 240 lab is on Tuesdays at 2:25 PM in Social Science 6203.
- The persuasive speech for Speech 100 must be 5 to 7 minutes long.
- My advisor is Dr. Rivera in the business school.
""",
    "preferences.md": """# Preferences
- Prefers short spoken answers and details on screen.
- Favorite study music is lo-fi beats.
""",
}


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("recall")
    mem = MonkeyMemory(tmp / "memory")
    for name, body in FILES.items():
        (tmp / "memory" / "memories" / name).write_text(body, encoding="utf-8")
    hist = HistoryStore(tmp / "monkey.db")
    hist.index_facts(tmp / "memory" / "memories", force=True)
    sid = hist.start_session()
    hist.add_message(sid, "user", "help me plan the marketing case study outline", "voice")
    hist.add_episode(sid, "Planned the marketing case study: three sections, due after break.",
                     ["marketing case study"], ["use the pricing chapter"], ["ask about length"], source="test")
    old = hist.start_session()
    hist.add_message(old, "user", "my favorite pizza place downtown closed", "voice")   # raw message only
    return hist, mem


CASES = [
    # (task, message, expected substring in what's injected, or None = inject nothing)
    ("general", "when does comet club meet?", "Thursdays"),
    ("web_lookup", "when does comet club meet?", "Thursdays"),      # how the rules actually route it
    ("general", "what's the plan for comet quest modes?", "ranked mode"),
    ("study_help", "help me prep my stats 240 lab", "Tuesdays"),
    ("study_help", "how long does my persuasive speech need to be?", "5 to 7 minutes"),
    ("quick_fact", "who's my advisor?", "Rivera"),
    ("quick_fact", "what's my advisor's name?", "Rivera"),          # reviewer N3
    ("general", "where were we on the marketing case study?", "three sections"),
    ("chat", "put on my usual study music", "lo-fi"),
    ("command", "play my study music like always", "lo-fi"),
    # declines: the task doesn't need personal memory, or nothing relevant exists
    ("command", "set a timer for ten minutes", None),
    ("weather", "is it going to rain tomorrow?", None),
    ("quick_fact", "what's the capital of australia?", None),
    ("web_lookup", "who won the game last night?", None),
    ("image_request", "draw a monkey surfing", None),
    ("chat", "thanks!", None),
    ("chat", "hey", None),
    ("general", "explain how photosynthesis works", None),
    ("general", "what pizza place did I like downtown?", None),     # only a raw old message: not auto-injected
    ("general", "what's the club's budget this year?", None),        # 'club' alone is too weak a match
]


@pytest.mark.parametrize("task,text,expect", CASES)
def test_recall_set(store, task, text, expect):
    hist, _ = store
    ok, _why = should_recall(task, text)
    injected = select(hist.search(text, scope="all", limit=10, include_sensitive=False), text, task=task) if ok else []
    joined = " | ".join(h.text for h in injected)
    if expect is None:
        assert injected == [], f"{text!r} injected {joined!r}"
    else:
        assert expect in joined, f"{text!r} injected {joined!r}"
        assert all(h.kind != "message" for h in injected)


def test_already_said_in_this_chat_is_not_repeated(store):
    hist, _ = store
    q = "when does comet club meet?"
    hits = hist.search(q, scope="all", limit=10)
    recent = "Monkey: Comet Club is the astronomy club; it meets Thursdays at 7 PM in the observatory."
    assert select(hits, q, recent_text=recent) == []


def test_injected_amount_is_logged_per_turn(tmp_path):
    from monkey.trace import TurnTracer
    from tests.test_memory_eval import make
    from tests.test_agent_loop import text_block

    agent, client, events, hist, mem, _ = make(tmp_path, [([text_block("Thursdays at 7.")], "end_turn"),
                                                          ([text_block("10 minutes set.")], "end_turn")])
    (tmp_path / "memory" / "memories" / "projects.md").write_text(FILES["projects.md"], encoding="utf-8")
    agent.trace = TurnTracer(tmp_path / "traces")
    agent.trace.begin("typed")
    agent.handle("when does comet club meet?")
    agent.trace.finish()
    agent.trace.begin("typed")
    agent.handle("set a timer for ten minutes")
    agent.trace.finish()
    a, b = agent.trace.recent()[-2:]
    assert a["recall"] == "injected" and a["recall_chars"] > 0
    assert b["recall"] == "skipped" and b["recall_chars"] == 0


# ---------------------------------------------------------------- one write path
CONFLICTS = [
    # (existing fact, new fact, flagged as "may replace"?) - the new fact is saved either way
    ("Their advisor is Dr. Rivera", "Their advisor is Dr. Chen", True),
    ("Statistics 240 lab is on Tuesdays", "Statistics 240 lab is on Wednesdays", True),
    ("Their roommate is Sam", "Their roommate is Jordan", True),
    ("Favorite study music is lo-fi beats", "Favorite study music is jazz piano", True),
    # several can be true at once (the reviewer's cases): saved, no hint
    ("Plays guitar", "Plays piano", False),
    ("Likes pizza", "Likes sushi", False),
    ("Allergic to peanuts", "Allergic to shellfish", False),
    ("Has a CS 400 exam on Friday", "Has a CS 400 project due Friday", False),
    ("Takes Statistics 240 on Tuesdays", "Takes Chemistry 103 on Mondays", False),
    ("Their roommate is Sam", "Their roommate likes hiking", False),
    ("Plays pickup basketball on Fridays", "Works at the campus library", False),
]


@pytest.mark.parametrize("old,new,hint", CONFLICTS)
def test_remember_never_refuses_and_flags_possible_replacements(tmp_path, old, new, hint):
    from monkey.brain.tools import Services, ToolRunner
    from monkey.memory import facts as F

    mem = MonkeyMemory(tmp_path / "memory")
    root = tmp_path / "memory" / "memories"
    F.add_fact(root, "profile.md", old, src="user_said")
    r = ToolRunner(Services(emit=lambda *a: None, memory=mem, approval=None, open_url=lambda u: None))
    said = f"remember that {new.lower()}"
    r.begin_turn(said, [said])
    out, _ = r.run("remember", {"fact": new, "file": "profile.md", "evidence": new.lower()})
    current = [f.text for f in F.parse_file(root, "profile.md") if f.status == "current"]
    assert out.startswith("Saved") and new in current and old in current, out       # both kept until the user decides
    assert ("may replace" in out) == hint, out
    if hint:
        assert "update_memory" in out and "ask" in out


def test_memory_tool_is_view_only_so_nothing_is_mislabelled_as_typed_by_you(tmp_path):
    from tests.test_agent_loop import text_block, tool_block
    from tests.test_memory_eval import make

    script = [([tool_block("memory", {"command": "create", "path": "/memories/notes.md",
                                      "file_text": "- Their roommate is Sam"}, "m1")], "tool_use"),
              ([tool_block("memory", {"command": "view", "path": "/memories"}, "m2")], "tool_use"),
              ([text_block("ok")], "end_turn")]
    agent, client, events, hist, mem, _ = make(tmp_path, script)
    agent.handle("my roommate is Sam, remember that")
    assert not (tmp_path / "memory" / "memories" / "notes.md").exists()
    results = [b for m in agent.history if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]
    assert "read-only" in str(results[0]["content"]) and results[0].get("is_error")
    assert not results[1].get("is_error")                        # viewing still works

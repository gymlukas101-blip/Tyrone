"""History store (sessions, messages, episodes, fact index) and markdown facts with provenance."""
import time

import pytest

from monkey.memory import facts as F
from monkey.memory.history import HistoryStore, fts_query


@pytest.fixture
def mem(tmp_path):
    root = tmp_path / "memories"
    root.mkdir()
    (root / "profile.md").write_text("# About\n- Studies at Example University.\n- (placeholder line)\n")
    (root / "projects.md").write_text("# Projects\n## Comet Quest\n- Comet Quest is a racing game; next milestone is "
                                      "the ranked mode.\n## Comet Club\n- Comet Club is the astronomy club; meets "
                                      "Thursdays.\n")
    return root


@pytest.mark.parametrize("fts", [True, False])
def test_messages_survive_restart_and_are_searchable(tmp_path, fts):
    db = tmp_path / "m.db"
    h = HistoryStore(db)
    h.fts = h.fts and fts
    sid = h.start_session()
    h.add_message(sid, "user", "We decided the boss fight uses three phases.")
    h.add_message(sid, "assistant", "Got it, three phases.")
    h.end_session(sid)
    h2 = HistoryStore(db)                       # "restart"
    h2.fts = h2.fts and fts
    hits = h2.search("what did we decide about the boss fight", scope="conversations")
    assert hits and "three phases" in hits[0].text and hits[0].kind == "message"


def test_episodes_and_needs_episode(tmp_path):
    h = HistoryStore(tmp_path / "m.db")
    sid = h.start_session()
    h.add_message(sid, "user", "Let's plan the speech outline")
    h.end_session(sid)
    assert h.needs_episode() == [sid]
    h.add_episode(sid, "Planned the speech outline", ["speech"], ["Use 3 note cards"], ["Rehearse Friday"], "model_summary")
    assert h.needs_episode() == []
    hits = h.search("note cards for my speech", scope="episodes")
    assert hits and hits[0].kind == "episode" and "3 note cards" in hits[0].text
    assert h.recent_episodes(1)[0]["open_items"] == ["Rehearse Friday"]


def test_close_stale_sessions(tmp_path):
    h = HistoryStore(tmp_path / "m.db")
    old = h.start_session()
    h.add_message(old, "user", "hello")
    with h._conn() as c:
        c.execute("UPDATE messages SET ts = ?", (time.time() - 3600,))
    live = h.start_session()
    assert h.close_stale(active_sid=live) == [old]


def test_fact_index_disambiguates_shared_keyword(tmp_path, mem):
    h = HistoryStore(tmp_path / "m.db")
    assert h.index_facts(mem) >= 3
    game = h.search("comet quest ranked mode milestone", scope="facts")
    club = h.search("when does comet club meet", scope="facts")
    assert "racing game" in game[0].text and "Thursdays" in club[0].text


def test_placeholder_lines_are_not_facts(mem):
    texts = [f.text for f in F.all_facts(mem)]
    assert not any("placeholder" in t for t in texts)


def test_update_supersedes_and_forget_removes(tmp_path, mem):
    h = HistoryStore(tmp_path / "m.db")
    f, created = F.add_fact(mem, "classes.md", "Speech class meets Tuesday at 9:30 AM")
    assert created and F.add_fact(mem, "classes.md", "speech class meets tuesday at 9:30 am!")[1] is False   # dedupe
    old, new = F.update_fact(mem, f.id, "Speech class meets Tuesday at 11:00 AM")
    h.index_facts(mem, force=True)
    cur = h.search("speech class tuesday", scope="facts")
    assert cur[0].text.endswith("11:00 AM") and all("9:30" not in x.text for x in cur)
    hist = h.search("speech class tuesday", scope="facts", include_superseded=True)
    assert any("9:30" in x.text and x.status == "superseded" for x in hist)
    F.forget_fact(mem, new.id)
    h.index_facts(mem, force=True)
    assert not [x for x in h.search("speech class tuesday 11", scope="facts") if x.status == "current"]


def test_safe_rel_blocks_traversal(mem):
    for bad in ("../x.md", "backups/a.md", "superseded.md", "notes.txt"):
        with pytest.raises(ValueError):
            F.safe_rel(mem, bad)
    assert F.safe_rel(mem, "/memories/projects.md") == "projects.md"


def test_grounding_requires_users_own_words():
    said = ["btw remember that my speech class moved to Tuesday 11"]
    assert F.grounded("Speech class moved to Tuesday 11", "speech class moved to Tuesday 11", said) == ""
    assert F.grounded("User's password is hunter2", "password is hunter2", said)             # not said
    assert F.grounded("Speech class is cancelled forever and user hates it", "speech class", said)  # overreach


def test_delete_all_and_export(tmp_path):
    h = HistoryStore(tmp_path / "m.db")
    sid = h.start_session()
    h.add_message(sid, "user", "secret plan about the hackathon")
    assert h.export()["sessions"][0]["messages"][0]["text"].startswith("secret")
    assert h.delete_all() == 1
    assert h.search("hackathon plan") == [] and h.stats()["messages"] == 0


def test_fts_query_sanitizes():
    assert fts_query('what did "we" say; DROP TABLE x') == '"drop"* OR "table"*'   # quoted terms only
    assert fts_query("the and of") == ""

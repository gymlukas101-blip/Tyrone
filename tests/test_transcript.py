import time
from types import SimpleNamespace

from monkey.brain import agent as agent_mod
from monkey.brain.agent import CREDITS_GONE, STATE_KEY, Agent, _out_of_credits
from monkey.brain.costs import Ledger


def test_transcript_since_last_reset(tmp_path):
    lg = Ledger(tmp_path / "db.sqlite")
    lg.add_transcript("user", "old question")
    lg.add_transcript("bot", "old answer")
    lg.add_transcript("reset", "")
    lg.add_transcript("user", "hi")
    lg.add_transcript("bot", "")  # empty replies are skipped
    lg.add_transcript("bot", "hey!")
    got = Ledger(tmp_path / "db.sqlite").recent_transcript(40)  # fresh object, like after a restart
    assert [(r["role"], r["text"]) for r in got] == [("user", "hi"), ("bot", "hey!")]


def test_transcript_limit_keeps_newest(tmp_path):
    lg = Ledger(tmp_path / "db.sqlite")
    for i in range(10):
        lg.add_transcript("user", f"m{i}")
    assert [r["text"] for r in lg.recent_transcript(3)] == ["m7", "m8", "m9"]


def _agent(ledger):
    return Agent(client=None, router=None, tools=SimpleNamespace(), memory=None, ledger=ledger,
                 emit=lambda *a: None, speak=lambda s: None)


def test_conversation_restored_within_window(tmp_path):
    lg = Ledger(tmp_path / "db.sqlite")
    a = _agent(lg)
    a.history = [{"role": "user", "content": [{"type": "text", "text": "hi"}]},
                 {"role": "assistant", "content": [SimpleNamespace(model_dump=lambda **k: {"type": "text", "text": "hey"})]}]
    a._persist()
    b = _agent(Ledger(tmp_path / "db.sqlite"))
    assert b.history[1]["content"] == [{"type": "text", "text": "hey"}]
    assert b._restored is True


def test_conversation_not_restored_after_idle_window(tmp_path):
    lg = Ledger(tmp_path / "db.sqlite")
    lg.put_state(STATE_KEY, [{"role": "user", "content": "hi"}], time.time() - agent_mod.SESSION_IDLE_RESET_S - 5)
    assert _agent(lg).history == []


def test_new_session_forgets_saved_conversation(tmp_path):
    lg = Ledger(tmp_path / "db.sqlite")
    lg.put_state(STATE_KEY, [{"role": "user", "content": "hi"}], time.time())
    a = _agent(lg)
    assert a.history
    a.new_session()
    assert lg.get_state(STATE_KEY) is None


def test_out_of_credits_detection():
    e = SimpleNamespace(message="Your credit balance is too low to access the Anthropic API.")
    assert _out_of_credits(e)  # type: ignore[arg-type]
    assert not _out_of_credits(SimpleNamespace(message="overloaded"))  # type: ignore[arg-type]
    assert "Max" in CREDITS_GONE

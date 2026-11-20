"""Sticky model routing: a quick follow-up may stay on the model that just answered, a later one may not.

Regression for agent.handle() refreshing last_activity *before* checking the STICKY_S window (which made every
follow-up inside a session sticky, even 19 minutes later)."""
import time

from monkey.brain import agent as agent_mod
from tests.test_agent_loop import build, text_block


def run_after(tmp_path, idle_s):
    agent, client, events, spoken, *_ = build(tmp_path, [([text_block("one")], "end_turn"),
                                                          ([text_block("two")], "end_turn")])
    seen = []
    orig = agent.router.route

    def spy(text, importance=None, sticky=None, **kw):
        seen.append(sticky)
        return orig(text, importance, sticky=sticky, **kw)

    agent.router.route = spy
    agent.handle("first question")
    assert agent._last_route is not None
    before = len(agent.history)
    agent.last_activity = time.time() - idle_s          # pretend the last reply ended idle_s ago
    agent.handle("follow up")
    return seen[-1], before, agent


def test_follow_up_within_window_is_sticky(tmp_path):
    sticky, _, agent = run_after(tmp_path, 60)
    assert sticky is not None


def test_follow_up_after_window_is_not_sticky_and_keeps_session(tmp_path):
    sticky, before, agent = run_after(tmp_path, 5 * 60)
    assert sticky is None
    assert len(agent.history) > before                  # same session: history kept, not reset


def test_after_idle_reset_starts_fresh_session(tmp_path):
    sticky, before, agent = run_after(tmp_path, agent_mod.SESSION_IDLE_RESET_S + 60)
    assert sticky is None
    assert len(agent.history) < before + 2              # session was reset before the new turn

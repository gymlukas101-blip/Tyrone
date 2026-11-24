"""Clicking Monkey toggles his hearing: on = he listens now; off = the turn ends and the mic is muted until the next
click (or the mic button / hotkey / tray). The UI gets a `hearing` event for the whole-body reaction."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from monkey import app as app_mod


class FakeListener:
    def __init__(self):
        self.mode, self.muted, self.ptt, self.cancelled = "wake", False, 0, 0

    def push_to_talk(self):
        self.ptt += 1
        self.mode = "record"

    def cancel(self):
        self.cancelled += 1
        self.mode = "wake"

    def end_conversation(self):
        pass


@pytest.fixture
def mk(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    a = app_mod.MonkeyApp(tmp_path / "Monkey", headless=True)
    events = []
    a.ui.emit = lambda name, p=None: events.append((name, p))
    a.listener = FakeListener()
    a.agent = NS(cancel=lambda: None)
    a.speaker = NS(speaking=False, stop=lambda: None)
    return a, app_mod.Api(a), events


def _hearing(events):
    return [p for n, p in events if n == "hearing"]


def test_click_while_idle_starts_listening(mk):
    a, api, ev = mk
    r = api.toggle_hearing()
    assert r == {"ok": True, "on": True, "muted": False}
    assert a.listener.ptt == 1 and _hearing(ev)[-1]["on"] is True


def test_click_while_listening_turns_hearing_off_and_mutes(mk):
    a, api, ev = mk
    api.toggle_hearing()
    a._listening = True
    r = api.toggle_hearing()
    assert r == {"ok": True, "on": False, "muted": True}
    assert a.listener.muted and a.listener.cancelled == 1 and a._listening is False
    state = [p for n, p in ev if n == "state"][-1]
    assert state["muted"] is True and state["state"] != "listening"
    assert _hearing(ev)[-1] == {"on": False, "muted": True, "via": "click"}


def test_click_while_off_unmutes_and_listens(mk):
    a, api, ev = mk
    a.listener.muted = True
    r = api.toggle_hearing()
    assert r == {"ok": True, "on": True, "muted": False}
    assert not a.listener.muted and a.listener.ptt == 1


def test_mic_button_also_turns_hearing_back_on(mk):
    a, api, ev = mk
    a.listener.muted = True
    api.push_to_talk()
    assert not a.listener.muted and a.listener.ptt == 1
    assert _hearing(ev)[-1]["via"] == "push_to_talk"


def test_click_in_conversation_mode_counts_as_listening(mk):
    a, api, _ = mk
    a.listener.mode = "conversation"
    a._agent_state = "idle"
    assert api.toggle_hearing()["on"] is False and a.listener.muted


def test_no_microphone_yet_says_so(mk):
    a, api, ev = mk
    a.listener = None
    assert api.toggle_hearing() == {"ok": False, "on": False, "muted": False}
    assert ev[-1][0] == "error"

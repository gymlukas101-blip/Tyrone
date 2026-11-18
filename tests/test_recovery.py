"""Monkey keeps working after errors: agent turn rollback + history repair, listener self-heal, conversation mode."""
import time
from types import SimpleNamespace as NS

import anthropic
import httpx
import numpy as np

from monkey.audio import conversation as conv
from monkey.audio.endpoint import FRAME_SAMPLES
from monkey.audio.listener import Listener
from monkey.brain.agent import repair_history
from tests.test_agent_loop import FakeClient, FakeStream, build, text_block, tool_block


def status_error(code, msg="bad"):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIStatusError(msg, response=httpx.Response(code, request=req), body=None)


class ScriptClient(FakeClient):
    """Script items may be exceptions (raised when the request is made)."""

    def _stream(self, **params):
        self.calls.append(params)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return FakeStream(*item)


def build_script(tmp_path, script):
    agent, client, events, spoken, *_ = build(tmp_path, [])
    agent.client = ScriptClient(script)
    return agent, agent.client, events, spoken


# ---------------------------------------------------------------- agent
def test_repair_drops_orphan_tool_use_and_result():
    h = [{"role": "user", "content": [{"type": "text", "text": "hi"}]},
         {"role": "assistant", "content": [{"type": "text", "text": "checking"},
                                           {"type": "tool_use", "id": "t1", "name": "x", "input": {}}]},
         {"role": "user", "content": [{"type": "text", "text": "next question"}]},          # no tool_result!
         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "zz", "content": "?"}]},
         {"role": "assistant", "content": []}]
    fixed, changed = repair_history(h)
    assert changed
    assert all(b.get("type") != "tool_use" for m in fixed for b in m["content"])
    assert all(b.get("type") != "tool_result" for m in fixed for b in m["content"])
    assert repair_history(fixed) == (fixed, False)


def test_repair_keeps_valid_pairs_and_effort_messages():
    h = [{"role": "user", "content": [{"type": "text", "text": "hi"}]},
         {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}]},
         {"role": "system", "content": [], "output_config": {"effort": "low"}},
         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}]
    assert repair_history(h) == (h, False)


def test_unexpected_error_rolls_back_and_next_turn_works(tmp_path):
    agent, client, events, spoken = build_script(tmp_path, [
        RuntimeError("boom"),
        ([text_block("All good now.")], "end_turn"),
    ])
    agent.handle("first question")
    assert agent.history == []                                   # failed turn left no trace
    assert any("went wrong" in s for s in spoken)
    agent.handle("second question")
    assert "All good now." in " ".join(spoken)
    assert ("state", {"state": "idle"}) in events


def test_tool_crash_mid_turn_does_not_poison_history(tmp_path):
    agent, client, events, spoken = build_script(tmp_path, [
        ([tool_block("open_website", {"target": "canvas"}, "t9")], "tool_use"),
        ([text_block("Done.")], "end_turn"),
    ])
    agent.tools.run = lambda name, args: (_ for _ in ()).throw(KeyError("kaput"))   # crash outside ToolError
    agent.handle("open canvas")
    assert agent.history == []
    agent.tools.run = lambda name, args: ("ok", False)
    agent.client.script = [([text_block("Hello again.")], "end_turn")]
    agent.handle("hi")
    sent = agent.client.calls[-1]["messages"]
    assert not any(isinstance(b, dict) and b.get("type") == "tool_use" for m in sent for b in m["content"])


def test_400_on_broken_history_continues_with_last_message(tmp_path):
    agent, client, events, spoken = build_script(tmp_path, [
        status_error(400, "messages.3: tool_use ids were found without tool_result blocks"),
        ([text_block("Here you go.")], "end_turn"),
    ])
    agent.history = [{"role": "user", "content": [{"type": "text", "text": "old"}]},
                     {"role": "assistant", "content": [{"type": "text", "text": "old reply"}]}]
    agent.last_activity = time.time()
    agent.handle("what's due")
    assert "Here you go." in " ".join(spoken)
    assert len(agent.client.calls[1]["messages"]) == 1


def test_overloaded_retries_once(tmp_path, monkeypatch):
    monkeypatch.setattr("monkey.brain.agent.time.sleep", lambda s: None)
    agent, client, events, spoken = build_script(tmp_path, [
        status_error(529, "overloaded"),
        ([text_block("Made it.")], "end_turn"),
    ])
    agent.handle("hey")
    assert "Made it." in " ".join(spoken)


def test_repeated_outage_says_so_and_stays_usable(tmp_path, monkeypatch):
    monkeypatch.setattr("monkey.brain.agent.time.sleep", lambda s: None)
    agent, client, events, spoken = build_script(tmp_path, [
        status_error(529), status_error(529),
        ([text_block("Back.")], "end_turn"),
    ])
    agent.handle("hey")
    assert any("swamped" in s for s in spoken)
    agent.handle("hey again")
    assert "Back." in " ".join(spoken)


# ---------------------------------------------------------------- conversation rules
def test_goodbyes_and_noise():
    for t in ["thanks", "Thank you, Monkey!", "ok thanks bye", "that's all", "never mind", "I'm good"]:
        assert conv.is_goodbye(t), t
    for t in ["Thanks, now what's due tomorrow?", "no", "what's the weather"]:
        assert not conv.is_goodbye(t), t
    assert conv.worth_answering("yes") and conv.worth_answering("send it")
    assert not conv.worth_answering("uh") and not conv.worth_answering("hmm") and not conv.worth_answering("")
    assert conv.strip_wake("Hey Monkey, what's due?") == "what's due?"


# ---------------------------------------------------------------- listener
class FakeStreamDev:
    def __init__(self, cb):
        self.cb, self.started, self.closed = cb, False, False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True


def loud():
    t = np.arange(FRAME_SAMPLES)
    return (4000 * np.sin(t / 7)).astype(np.int16)


def quiet():
    return np.zeros(FRAME_SAMPLES, dtype=np.int16)


def make_listener(**kw):
    got = []
    ww = NS(predict=kw.pop("predict", lambda f: {"hey": 0.0}), reset=lambda: None)
    li = Listener(on_wake=lambda: got.append("wake"), on_utterance=lambda a: got.append(("utt", len(a))),
                  wakeword_model=ww, stream_factory=FakeStreamDev, **kw)
    return li, got


def test_listener_survives_a_crashing_frame():
    calls = {"n": 0}

    def predict(f):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("model hiccup")
        return {"hey": 0.9}

    li, got = make_listener(predict=predict)
    li._q.put(quiet())                             # this frame makes the wake-word model throw
    li._q.put(quiet())                             # this one scores 0.9
    import threading
    th = threading.Thread(target=li._loop, daemon=True)
    th.start()
    time.sleep(0.3)
    li._stop.set()
    th.join(1)
    assert "wake" in got                           # still detecting after the crash


def test_conversation_mode_records_without_wake_word_then_returns_to_wake():
    li, got = make_listener()
    li.enter_conversation(idle_s=60)
    assert li.mode == "conversation"
    for _ in range(10):
        li._step(loud())
    for _ in range(30):
        li._step(quiet())
    time.sleep(0.05)
    assert any(isinstance(g, tuple) for g in got) and li.last_source == "conversation"
    assert li.mode == "wake"                        # app reopens it once he has answered


def test_conversation_quiet_deadline_ends_it():
    ended = []
    li, got = make_listener(on_conversation_idle=lambda: ended.append(1))
    li.enter_conversation(idle_s=5)
    li._conv_deadline = time.monotonic() - 1
    li._step(quiet())
    assert ended and li.mode == "wake"


def test_mic_watchdog_reopens_a_silent_stream():
    msgs = []
    li, got = make_listener(on_reconnect=msgs.append)
    li.start()
    first = li._stream
    li._last_frame = time.monotonic() - 10
    li._watchdog()
    li.stop()
    assert first.closed and li._stream is not first
    assert msgs == ["Microphone reconnected."]


# ---------------------------------------------------------------- app flow (conversation mode)
def fake_app(listener, speaking=False):
    from monkey.app import MonkeyApp

    events, said, asked = [], [], []
    app = NS(
        listener=listener, speaker=NS(speaking=speaking, stop=lambda: None), _in_conversation=True,
        _reply_done=False, _conv_timer=None, _listening=False, _agent_state="idle",
        cfg=NS(settings=NS(conversation_mode=True, conversation_idle_s=90)),
        ui=NS(emit=lambda n, p=None: events.append((n, p))), _publish_state=lambda: None,
        _say=said.append, ask=lambda text, *a, **k: asked.append(text),
        stt=lambda: NS(transcribe=lambda audio: app._heard),
    )
    for name in ("_maybe_continue_conversation", "end_conversation", "_on_utterance", "_say_goodbye",
                 "_start_conversation", "_on_speaker_state"):
        setattr(app, name, getattr(MonkeyApp, name).__get__(app))
    return app, events, said, asked


def test_after_reply_he_listens_without_wake_word_then_thanks_ends_it():
    li, _ = make_listener()
    app, events, said, asked = fake_app(li)
    app._reply_done = True
    app._maybe_continue_conversation()
    time.sleep(0.45)
    assert li.mode == "conversation"
    li.last_source = "conversation"
    app._heard = "and when is it due?"
    app._on_utterance(np.zeros(10, np.int16))
    assert asked == ["and when is it due?"]
    app._heard = "thanks monkey"
    app._on_utterance(np.zeros(10, np.int16))
    assert not app._in_conversation and li.mode == "wake" and said      # signed off, wake word needed again
    assert len(asked) == 1


def test_waits_for_speech_to_finish_and_ignores_noise():
    li, _ = make_listener()
    app, events, said, asked = fake_app(li, speaking=True)
    app._reply_done = True
    app._maybe_continue_conversation()
    time.sleep(0.4)
    assert li.mode == "wake"                       # still talking: don't open the mic on his own voice
    app.speaker.speaking = False
    app._on_speaker_state(False)
    time.sleep(0.45)
    assert li.mode == "conversation"
    li.last_source = "conversation"
    app._heard = "uh"
    app._on_utterance(np.zeros(10, np.int16))
    assert asked == [] and li.mode == "conversation" and app._in_conversation


def test_silero_vad_on_real_speech_if_available():
    """CI downloads the model + the keyword model's test recordings; skipped locally when they're absent."""
    import wave
    from pathlib import Path

    import pytest

    from monkey.audio.vad import load_vad

    root = Path(__file__).resolve().parents[1] / "wakeword"
    vad = load_vad(None, root)
    wavs = sorted((root / "sherpa-kws" / "test_wavs").glob("*.wav"))
    if vad is None or not wavs:
        pytest.skip("Silero model / test recordings not downloaded")
    with wave.open(str(wavs[0])) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    hits = sum(vad(pcm[i:i + FRAME_SAMPLES]) for i in range(0, len(pcm) - FRAME_SAMPLES, FRAME_SAMPLES))
    assert hits >= 3                                      # finds the speech in a real recording
    vad.reset()
    assert not any(vad(np.zeros(FRAME_SAMPLES, np.int16)) for _ in range(20))

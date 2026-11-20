"""Voice 2.0: early commit (transcribe during a pause; end the turn on a finished thought), turn-completeness."""
from __future__ import annotations

import time

import numpy as np
import pytest

from monkey.audio.endpoint import FRAME_MS, FRAME_SAMPLES
from monkey.audio.listener import Listener
from monkey.audio.turn import completeness

LOUD = (np.sin(np.arange(FRAME_SAMPLES) / 3.0) * 8000).astype(np.int16)
QUIET = np.zeros(FRAME_SAMPLES, dtype=np.int16)


def _vad(frame):
    return bool(np.abs(frame).mean() > 500)


def _run(segments, words, early=True, stt_ms=0):
    """segments: [(speech_ms, pause_ms), ...]. words(n_pauses_seen) -> transcript so far.
    Returns (ms of silence after the last word when the turn ended, text handed over, turn ended mid-pause?)."""
    got = {}
    pauses = {"n": 0}

    def transcribe(audio):
        time.sleep(stt_ms / 1000)
        return words(pauses["n"])
    lst = Listener(on_wake=lambda: None, on_utterance=lambda a, text=None: got.update(text=text, done=True),
                   stream_factory=lambda cb: None, vad=_vad, end_silence_ms=lambda: 1400,
                   transcribe=transcribe if early else None)
    lst._begin_recording()
    silence_ms = 0
    for i, (speech, pause) in enumerate(segments):
        for _ in range(speech // FRAME_MS):
            lst._step(LOUD)
        last = i == len(segments) - 1
        silence_ms = 0
        for _ in range((pause if not last else 4000) // FRAME_MS):
            lst._step(QUIET)
            silence_ms += FRAME_MS
            time.sleep(0.004)                 # let the background transcription land, like real time would
            if got.get("done"):
                return silence_ms, got.get("text"), not last
        pauses["n"] += 1
    return silence_ms, got.get("text"), False


def test_completeness_reads_finished_and_unfinished_thoughts():
    for t in ("What's due this week?", "Open canvas.", "stop", "what's the weather tomorrow", "Thanks!"):
        assert completeness(t) == "complete", t
    for t in ("Remind me to call", "Remind me to call.", "and um", "Um.", "I want to check my, ", "What about the",
              "so", "can you check"):
        assert completeness(t) == "incomplete", t
    assert completeness("") == "unknown"


def test_a_finished_question_ends_the_turn_early_and_skips_a_second_transcription():
    ms, text, cut = _run([(1200, 0)], lambda n: "What's due this week?")
    assert text == "What's due this week?" and not cut
    assert ms <= 640, ms                       # was 1400 + 400 (short-utterance padding) = 1800 ms


def test_statements_wait_a_little_longer_than_questions():
    from monkey.audio.turn import commit_after_ms

    assert commit_after_ms("What's due this week?") == 480 and commit_after_ms("stop") == 480
    assert commit_after_ms("Open my history notes.") == 880
    assert commit_after_ms("Remind me to call") is None and commit_after_ms("") is None
    ms, text, cut = _run([(1200, 0)], lambda n: "Open my history notes.")
    assert text == "Open my history notes." and 880 <= ms <= 1040, ms


def test_without_early_commit_the_old_wait_is_unchanged():
    ms, text, cut = _run([(1200, 0)], lambda n: "What's due this week?", early=False)
    assert text is None and ms >= 1760          # the app transcribes afterwards, as before


def test_trailing_off_waits_longer_and_doesnt_cut_you_off():
    # "Remind me to call…" (pause 1.6 s) "…my mom at five."
    words = lambda n: "Remind me to call" if n == 0 else "Remind me to call my mom at five."
    ms, text, cut = _run([(1000, 1600), (1200, 0)], words)
    assert not cut, "the turn ended during the mid-thought pause"
    assert text == "Remind me to call my mom at five."


def test_a_mid_thought_pause_after_a_complete_looking_phrase_keeps_the_rest():
    # Talking again after a pause makes the pause's transcript stale: the final one covers everything.
    words = lambda n: "Open canvas." if n == 0 else "Open canvas and then my email."
    ms, text, cut = _run([(900, 400), (1100, 0)], words)       # a 0.4 s breath: shorter than the early pause
    assert not cut and text == "Open canvas and then my email."


def test_when_the_normal_rule_ends_the_turn_the_running_transcription_is_reused():
    """Slow STT: the turn ends by the normal silence rule, and the pause's transcription (already running) is used
    instead of transcribing the same audio a second time."""
    calls, got = [], {}

    def transcribe(audio):
        calls.append(1)
        time.sleep(0.4)
        return "Can you explain how photosynthesis works and why plants need light for it?"
    lst = Listener(on_wake=lambda: None, on_utterance=lambda a, text=None: got.update(text=text),
                   stream_factory=lambda cb: None, vad=_vad, end_silence_ms=lambda: 1400, transcribe=transcribe)
    lst._begin_recording()
    for _ in range(4200 // FRAME_MS):
        lst._step(LOUD)
    for _ in range(1500 // FRAME_MS):          # fed instantly: the transcription is still running at the normal end
        lst._step(QUIET)
    for _ in range(100):
        if "text" in got:
            break
        time.sleep(0.02)
    assert got.get("text", "").startswith("Can you explain") and calls == [1]


# ---------------------------------------------------------------- speech generation
def _chunks(deltas, **kw):
    from monkey.brain.speech_text import SentenceChunker

    c = SentenceChunker(**kw)
    out, first_at = [], None
    for i, d in enumerate(deltas):
        got = c.feed(d)
        if got and first_at is None:
            first_at = i
        out += got
    return out + c.flush(), first_at


def test_first_clause_is_spoken_before_the_sentence_ends():
    reply = ["Sure", ",", " here's", " what's", " due", " this", " week", ",", " starting", " with", " your",
             " stats", " lab", " on", " Tuesday", ". ", "Then", " the", " essay", "."]
    out, first = _chunks(reply)
    assert out[0] == "Sure, here's what's due this week," and first == 8          # 9 tokens in, not 16
    assert out[1] == "starting with your stats lab on Tuesday." and out[2] == "Then the essay."
    old, old_first = _chunks(reply, early_clause=False)
    assert old_first == 15 and " ".join(old) == " ".join(out)                     # same words, same order


def test_short_openers_and_code_are_not_split_early():
    out, _ = _chunks(["Yes, ", "it's ", "due ", "Friday."])                       # "Yes," alone is too short
    assert out == ["Yes, it's due Friday."]
    out, _ = _chunks(["Here's the code: ```x = 1, y = 2```", " Done."])
    assert all("x = 1" not in o for o in out)                                    # code is never read aloud


def test_fish_reuses_one_connection_across_sentences(monkeypatch):
    from monkey.audio import tts

    made = []

    class Client:
        def __init__(self, **kw):
            made.append(1)

        def stream(self, *a, **k):
            class R:
                status_code = 200
                text = ""

                def __enter__(self):
                    return self

                def __exit__(self, *e):
                    return False

                def iter_bytes(self, n):
                    yield b"\x01\x00\x02\x00"
            return R()
    monkeypatch.setattr(tts.httpx, "Client", Client)
    f = tts.FishTTS(lambda: "k", lambda: "", lambda: "s2.1-pro-free")
    for s in ("One.", "Two.", "Three."):
        assert list(f.stream_pcm(s))
    assert made == [1]                                                            # one kept-alive client, not three


# ---------------------------------------------------------------- routing, barge-in, soft ack
def test_voice_turns_skip_the_classifier_unless_its_thinking_work():
    from monkey.brain.router import Router

    calls = []
    r = Router(classify=lambda t: calls.append(t) or ("general", 2, False, "x", None))
    assert r.route("what's the capital of australia", fast=True).reason.startswith("fast path")
    assert r.route("tell me a joke", fast=True) and calls == []
    r.route("help me design a ranked draft system", fast=True)       # thinking work: still classified
    r.route("what's the capital of australia")                       # typed (not fast): unchanged
    assert len(calls) == 2


class _BlockingStream:
    """A Claude stream that hasn't produced its first token yet; close() ends it (like the SDK)."""
    def __init__(self):
        import threading

        self.closed = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        self.closed.set()

    def __iter__(self):
        if not self.closed.wait(10):
            yield from ()
        raise ConnectionError("stream closed")


def test_cancel_while_waiting_for_the_first_token_returns_at_once(tmp_path):
    import threading

    from tests.test_agent_loop import build

    agent, client, events, spoken, *_ = build(tmp_path, [])
    stream = _BlockingStream()
    client.beta.messages.stream = lambda **kw: stream
    threading.Timer(0.2, agent.cancel).start()
    t0 = time.monotonic()
    agent.handle("what's the capital of australia")
    assert time.monotonic() - t0 < 1.0 and stream.closed.is_set()
    assert agent.history[-1]["role"] == "assistant"                  # history stays valid for the next turn
    assert spoken == []


def test_cancel_during_a_slow_tool_doesnt_wait_for_it(tmp_path):
    import threading

    from tests.test_agent_loop import build, text_block, tool_block

    agent, client, events, spoken, *_ = build(tmp_path, [
        ([tool_block("get_calendar", {"days": 1}, "c1")], "tool_use"),
        ([text_block("You have nothing today.")], "end_turn")])
    slow = threading.Event()
    agent.tools.run = lambda name, args: (slow.wait(5), ("nothing", False))[1]
    threading.Timer(0.3, agent.cancel).start()
    t0 = time.monotonic()
    agent.handle("what's on my calendar today")
    took = time.monotonic() - t0
    slow.set()
    assert took < 1.0, took
    assert len(client.calls) == 1                                      # no second round after the interrupt
    assert agent.history[-1]["role"] == "assistant" and spoken == []


def test_a_cancelled_reply_can_never_hand_a_sentence_to_the_speaker(tmp_path):
    from tests.test_agent_loop import build

    agent, client, events, spoken, *_ = build(tmp_path, [])
    agent.cancel()
    agent._say("stale sentence")
    assert spoken == []


def test_soft_ack_only_when_the_reply_is_genuinely_late(tmp_path):
    import types

    from monkey.app import MonkeyApp
    from monkey.trace import TurnTracer

    emitted = []
    tr = TurnTracer(tmp_path)
    app = types.SimpleNamespace(tracer=tr, speaker=None, ui=types.SimpleNamespace(emit=lambda n, p: emitted.append(n)),
                                SOFT_ACK_S=0.1)
    tr.begin("voice")
    MonkeyApp._arm_soft_ack(app)
    time.sleep(0.3)
    assert emitted == ["ack"] and "ack_spoken" in tr.current().marks
    emitted.clear()
    tr.begin("voice")
    MonkeyApp._arm_soft_ack(app)
    tr.mark("tts_submit")                                              # the reply is already on its way
    time.sleep(0.3)
    assert emitted == []

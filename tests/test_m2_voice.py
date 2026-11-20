"""Milestone 2: speaker state races (D4–D6), echo guard, barge-in, turn timing."""
from __future__ import annotations

import threading
import time

import numpy as np

from monkey.audio import speaker as spk


class _Engine:
    def __init__(self, delay=0.0, chunks=1, gap=0.0, value=1, lock=None):
        self.delay, self.chunks, self.gap, self.value, self.lock = delay, chunks, gap, value, lock
        self.closed = 0

    def available(self):
        return True

    def stream_pcm(self, text):
        lock = self.lock or threading.Lock()
        with lock:                      # like Pocket: one model, one sentence at a time
            try:
                time.sleep(self.delay)
                for _ in range(self.chunks):
                    yield np.full(64, self.value, dtype=np.int16)
                    time.sleep(self.gap)
            finally:
                self.closed += 1


def _drain(sp, frames=256):
    out = np.zeros((frames, 1), dtype=np.int16)
    sp._callback(out, frames, None, None)
    return out


def test_speaking_state_never_ends_while_a_sentence_is_queued():
    """D4: the audio callback deciding "done" can't race say(): state and pending change together."""
    states = []
    sp = spk.Speaker([_Engine(delay=0.03)], on_level=lambda v: None, on_state=states.append)
    stop = threading.Event()

    def audio_thread():
        while not stop.is_set():
            _drain(sp)
            time.sleep(0.002)                     # a real callback runs every ~23 ms
    t = threading.Thread(target=audio_thread, daemon=True)
    t.start()
    for i in range(80):
        sp.say("hi")
        if i % 7 == 0:
            time.sleep(0.01)                      # let the callback catch up and race the next say()
        assert sp.speaking                       # the instant say() returns, Monkey is speaking
    deadline = time.monotonic() + 15
    while sp.speaking and time.monotonic() < deadline:
        time.sleep(0.01)
    stop.set()
    t.join()
    sp.wait_idle_notified()
    assert not sp.speaking and sp._pending == 0
    assert states and states[-1] is False         # the UI ends on the real state
    assert all(a != b for a, b in zip(states, states[1:]))   # every change delivered once, in order


def test_a_slow_first_chunk_does_not_reset_speaking(monkeypatch):
    """D5: the stall watchdog waits while an engine is still inside its own deadline."""
    monkeypatch.setattr(spk, "STALL_S", 0.2)
    sp = spk.Speaker([_Engine(delay=2.3)], on_level=lambda v: None, on_state=lambda v: None)
    sp.say("a long sentence that Fish takes a while to start on")
    sp._last_audio = time.monotonic() - 5
    t0 = time.monotonic()
    while sp._audio.empty() and time.monotonic() - t0 < 4:
        assert sp.speaking, "watchdog reset speaking while the engine was still working"
        time.sleep(0.05)
    assert not sp._audio.empty() and sp.speaking


def test_next_reply_after_an_interrupt_starts_within_a_second():
    """D6: stop() makes the engine thread stop reading, which closes the generator and frees the model lock."""
    model = threading.Lock()
    long = _Engine(chunks=200, gap=0.05, value=1, lock=model)
    sp = spk.Speaker([long], on_level=lambda v: None, on_state=lambda v: None)
    sp.say("a very long first reply")
    t0 = time.monotonic()
    while sp._audio.empty() and time.monotonic() - t0 < 3:
        time.sleep(0.01)
    sp.stop()
    long.value = 2                                # the next sentence's audio is recognisable
    t1 = time.monotonic()
    sp.say("the new reply")
    got = False
    while time.monotonic() - t1 < 3 and not got:
        try:
            chunk = sp._audio.get(timeout=0.05)
            got = chunk is not None and int(chunk[0]) == 2
        except Exception:  # noqa: BLE001
            pass
    assert got and time.monotonic() - t1 < 1.0
    assert long.closed >= 1                       # the interrupted stream was closed, not left running


def test_sentences_queued_before_an_interrupt_are_never_spoken():
    sp = spk.Speaker([_Engine(delay=0.3, value=7)], on_level=lambda v: None, on_state=lambda v: None)
    for i in range(5):
        sp.say(f"old {i}")
    sp.stop()
    time.sleep(0.8)
    while not sp._audio.empty():
        assert sp._audio.get_nowait() is None or False, "stale audio from before the interrupt"


def test_first_audio_is_reported_once_per_reply():
    marks = []
    sp = spk.Speaker([_Engine(chunks=3)], on_level=lambda v: None, on_state=lambda v: None)
    sp.timing = lambda name, at=None: marks.append(name)
    sp.say("one")
    sp.say("two")
    t0 = time.monotonic()
    while sp.speaking and time.monotonic() - t0 < 3:
        _drain(sp)
        time.sleep(0.005)
    assert marks.count("first_audio_played") == 1 and "first_audio_packet" in marks


# ---------------------------------------------------------------- echo guard and "Monkey, stop"
def test_echo_of_his_own_sentence_is_rejected_but_real_replies_are_not():
    from monkey.audio.echo import EchoGuard

    g = EchoGuard()
    g.remember("Your essay for English is due Friday at midnight.", now=100.0)
    g.remember("Want me to open it?", now=101.0)
    assert g.is_echo("due Friday at midnight", now=103.0)            # the tail bled into the mic
    assert g.is_echo("essay for english is due friday", now=103.0)
    assert g.is_echo("at midnight want me to open it", now=103.0)    # spans two sentences
    assert not g.is_echo("yes open it", now=103.0)
    assert not g.is_echo("wait, is it due Friday or Saturday for history?", now=103.0)
    assert not g.is_echo("yes", now=103.0)                            # too short to judge: the user's
    assert not g.is_echo("due Friday at midnight", now=200.0)        # long after he said it


class _FakeWW:
    stop_names = {"monkey_stop"}

    def __init__(self):
        self.next = {}

    def predict(self, frame):
        out, self.next = {"hey_monkey": 0.0, "monkey_stop": 0.0, **self.next}, {}
        return out


def _listener(speaking, **kw):
    from monkey.audio.listener import Listener

    calls = []
    ww = _FakeWW()
    lst = Listener(on_wake=lambda: calls.append("wake"), on_utterance=lambda a: None, wakeword_model=ww,
                   is_speaking=lambda: speaking, on_stop=lambda: calls.append("stop"),
                   stream_factory=lambda cb: None, **kw)
    return lst, ww, calls


def test_monkey_stop_silences_him_only_while_he_talks():
    frame = np.zeros(1280, dtype=np.int16)
    lst, ww, calls = _listener(speaking=True)
    ww.next = {"monkey_stop": 1.0}
    lst._step(frame)
    assert calls == ["stop"] and lst.mode == "wake"                   # stopped, and no recording started
    lst, ww, calls = _listener(speaking=False)
    ww.next = {"monkey_stop": 1.0}
    lst._step(frame)
    assert calls == []                                               # not talking: nothing to stop, not a wake
    ww.next = {"hey_monkey": 1.0}
    lst._step(frame)
    assert calls == ["wake"] and lst.mode == "record"


def test_stop_phrase_is_spotted_by_the_real_keyword_model(tmp_path):
    """Uses the bundled sherpa model and its test clip ("...would light up here...") as a stand-in stop phrase."""
    import wave
    from pathlib import Path

    import pytest

    from monkey.audio.kws import SherpaWakeWord, find_model

    model = find_model(Path(__file__).resolve().parent.parent / "wakeword")
    if model is None or not (model / "test_wavs" / "0.wav").exists():
        pytest.skip("sherpa-onnx KWS model not downloaded")
    ww = SherpaWakeWord(model, ["hey monkey"], tmp_path, stop_phrases=("light up",))
    assert ww.stop_names == {"light_up"}
    w = wave.open(str(model / "test_wavs" / "0.wav"))
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    hits = [n for i in range(0, len(a), 1280) for n, sc in ww.predict(a[i:i + 1280]).items() if sc >= 1.0]
    assert "light_up" in hits and "hey_monkey" not in hits


# ---------------------------------------------------------------- turn traces
def test_a_traced_turn_records_each_stage_and_no_speech(tmp_path):
    import json

    from monkey.trace import TurnTracer, load_traces, report

    tr = TurnTracer(tmp_path)
    t0 = 1000.0
    tr.begin("wake", at=t0)
    for name, dt in [("wake", 0), ("speech_start", .3), ("last_voiced", 2.1), ("endpoint", 3.5), ("stt_start", 3.5),
                     ("stt_end", 4.1), ("route_start", 4.1), ("route_end", 4.11), ("context_start", 4.11),
                     ("context_end", 4.16), ("llm_request", 4.16), ("first_token", 5.0), ("first_speakable", 5.4),
                     ("tts_submit", 5.4), ("first_audio_packet", 5.9), ("first_audio_played", 6.0),
                     ("last_audio_played", 9.0)]:
        tr.mark(name, at=t0 + dt)
    tr.mark("first_token", at=t0 + 99)                  # a later "first" never overwrites the real first
    tr.user_text("what's due this week")
    tr.note(task="school", model="m", effort="low", rounds=1)
    tr.note(rounds=1, cost_usd=0.001)
    tr.note(cost_usd=0.002)
    tr.finish()
    rec = tr.recent()[-1]
    assert rec["spans_ms"]["you stop → he speaks"] == 3900.0
    assert rec["spans_ms"]["you stop → turn ends"] == 1400.0
    assert rec["spans_ms"]["request → first word"] == 840.0
    assert rec["rounds"] == 2 and abs(rec["cost_usd"] - 0.003) < 1e-9
    raw = "".join(f.read_text() for f in tmp_path.glob("turns-*.jsonl"))
    assert "due this week" not in raw and "text" not in json.loads(raw.splitlines()[0])
    assert "you stop → he speaks" in report(load_traces(tmp_path))


def test_request_text_is_kept_only_with_opt_in_and_corrections_are_flagged(tmp_path):
    from monkey.trace import TurnTracer, load_traces

    tr = TurnTracer(tmp_path, keep_text=lambda: True)
    tr.begin("voice")
    tr.user_text("open my notes")
    tr.note(task="command")
    tr.finish()
    tr.begin("voice")
    tr.user_text("no, I meant my history notes")
    tr.finish()
    recs = load_traces(tmp_path)
    assert recs[0]["text"] == "open my notes" and recs[0]["corrected_next_turn"] is True
    assert not recs[1].get("corrected_next_turn")
    from tools.bench_routing import from_traces

    out = from_traces(tmp_path)
    assert "Likely misroutes" in out and "open my notes" in out and "corrected" in out


def test_percentiles():
    from monkey.trace import percentile

    v = list(range(1, 101))
    assert percentile(v, 50) == 50.5 and percentile(v, 95) == 95.05 and percentile([], 50) is None


def test_speaker_reports_audible_start_and_barge_in_silence():
    """first_audio_played and playback_stopped come from the audio callback, not from when audio was queued."""
    marks = {}
    sp = spk.Speaker([_Engine(chunks=50, gap=0.01)], on_level=lambda v: None, on_state=lambda v: None)
    sp.timing = lambda name, at=None: marks.setdefault(name, at or time.monotonic())
    sp.say("hello there")
    t0 = time.monotonic()
    while sp._audio.empty() and time.monotonic() - t0 < 3:
        time.sleep(0.005)
    assert "first_audio_played" not in marks          # queued is not audible
    _drain(sp)
    assert "first_audio_played" in marks
    t_stop = time.monotonic()
    sp.stop()
    _drain(sp)                                        # the next device block is silent
    assert "playback_stopped" in marks
    assert marks["playback_stopped"] - t_stop < 0.25   # interrupt → silence, output latency included (fake: 0.1 s)


def test_listener_marks_speech_start_last_voiced_and_endpoint():
    from monkey.audio.endpoint import FRAME_SAMPLES

    marks = []
    lst, ww, calls = _listener(speaking=False, on_mark=lambda n, at: marks.append(n))
    lst._begin_recording()
    loud = (np.sin(np.arange(FRAME_SAMPLES) / 3.0) * 8000).astype(np.int16)
    for _ in range(12):
        lst._step(loud)
    for _ in range(40):
        lst._step(np.zeros(FRAME_SAMPLES, dtype=np.int16))
        if "endpoint" in marks:
            break
    assert marks[0] == "speech_start" and marks[-2:] == ["last_voiced", "endpoint"]


def test_important_only_when_said_to_monkey():
    from monkey.brain.router import detect_importance as d

    for content in ("any important emails?", "make sure my alarm is set", "the email says critical update",
                    "read the important one"):
        assert d(content) == "normal", content
    for ask in ("this is important, take your time", "it's really important that you get this right",
                "think carefully about this", "double-check this for me"):
        assert d(ask) == "high", ask


def test_speed_shows_up_in_check_everything(tmp_path):
    from types import SimpleNamespace

    from monkey import health
    from monkey.trace import TurnTracer

    tr = TurnTracer(tmp_path)
    for i in range(5):
        tr.begin("voice", at=100.0 * i)
        tr.mark("last_voiced", at=100.0 * i)
        tr.mark("first_audio_played", at=100.0 * i + 1.8 + i * 0.1)
        tr.finish()
    rows = health._speed_checks(SimpleNamespace(tracer=tr))
    row = next(c for c in rows if c.name == "you stop → he speaks")
    assert row.status == health.OK and "median 2.00 s" in row.detail
    assert health._speed_checks(SimpleNamespace(tracer=TurnTracer(None)))[0].status == health.SKIP

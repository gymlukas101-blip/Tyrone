import numpy as np

from tyrone.audio.endpoint import FRAME_SAMPLES, Endpointer
from tyrone.audio.stt import to_wav_bytes

rng = np.random.default_rng(0)


def quiet():
    return (rng.normal(0, 60, FRAME_SAMPLES)).astype(np.int16)


def loud():
    t = np.arange(FRAME_SAMPLES)
    return (4000 * np.sin(t / 7) + rng.normal(0, 200, FRAME_SAMPLES)).astype(np.int16)


def test_speech_then_silence_ends():
    ep = Endpointer()
    states = [ep.feed(quiet()) for _ in range(5)]
    assert set(states) == {"waiting"}
    states = [ep.feed(loud()) for _ in range(15)]
    assert states[-1] == "speech"
    end = None
    for _ in range(20):
        end = ep.feed(quiet())
        if end == "done":
            break
    assert end == "done"
    assert ep.audio().size == ep.total * FRAME_SAMPLES


def test_no_speech_times_out():
    ep = Endpointer(no_speech_ms=800)
    states = [ep.feed(quiet()) for _ in range(10)]
    assert states[-1] == "timeout"


def test_click_is_not_speech():
    ep = Endpointer()
    ep.feed(loud())  # one loud frame (door slam / click)
    assert all(ep.feed(quiet()) == "waiting" for _ in range(5))


def test_wav_bytes_header():
    b = to_wav_bytes(np.zeros(1600, dtype=np.int16))
    assert b[:4] == b"RIFF" and len(b) == 44 + 3200

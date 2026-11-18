import numpy as np

from monkey.audio.endpoint import FRAME_MS, FRAME_SAMPLES, Endpointer
from monkey.audio.stt import to_wav_bytes

rng = np.random.default_rng(0)


def quiet():
    return (rng.normal(0, 60, FRAME_SAMPLES)).astype(np.int16)


def loud(amp=4000):
    t = np.arange(FRAME_SAMPLES)
    return (amp * np.sin(t / 7) + rng.normal(0, 200, FRAME_SAMPLES)).astype(np.int16)


def frames(ms):
    return ms // FRAME_MS


def feed_until(ep, make, n):
    st = None
    for i in range(n):
        st = ep.feed(make())
        if st in ("done", "timeout"):
            return st, i + 1
    return st, n


def test_speech_then_silence_ends_after_patience():
    ep = Endpointer()                                   # normal: 1.4 s (+0.4 s for short utterances)
    assert {ep.feed(quiet()) for _ in range(5)} == {"waiting"}
    assert [ep.feed(loud()) for _ in range(25)][-1] == "speech"      # 2 s of speech: no short-utterance bonus
    st, n = feed_until(ep, quiet, 40)
    assert st == "done" and n == frames(1400)
    a = ep.audio()                                     # trimmed: pre-roll + speech + short tail, not all the silence
    assert a.size <= (6 + 25 + 4) * FRAME_SAMPLES


def test_mid_sentence_pause_does_not_cut_you_off():
    ep = Endpointer()
    for _ in range(12):
        ep.feed(loud())
    for _ in range(frames(1100)):                      # "so what I need is... [1.1 s] ...the essay rubric"
        assert ep.feed(quiet()) == "speech"
    for _ in range(10):
        assert ep.feed(loud()) == "speech"
    assert feed_until(ep, quiet, 40)[0] == "done"


def test_short_utterance_gets_extra_patience():
    ep = Endpointer()
    for _ in range(6):                                 # "Hey, um" (0.5 s)
        ep.feed(loud())
    st, n = feed_until(ep, quiet, 40)
    assert st == "done" and n == frames(1400) + frames(400)


def test_soft_trailing_words_still_count_as_speech():
    ep = Endpointer()
    for _ in range(5):
        ep.feed(quiet())
    for _ in range(20):
        ep.feed(loud())
    # trailing off quietly: above floor x1.8 but below the x3 needed to *start* speech
    floor = ep.floor
    soft = lambda: (rng.normal(0, 1, FRAME_SAMPLES) * floor * 2.3).astype(np.int16)   # noqa: E731
    assert all(ep.feed(soft()) == "speech" for _ in range(30))


def test_no_speech_times_out():
    ep = Endpointer(no_speech_ms=800)
    states = [ep.feed(quiet()) for _ in range(10)]
    assert states[-1] == "timeout"


def test_conversation_mode_waits_forever():
    ep = Endpointer(no_speech_ms=None)
    assert all(ep.feed(quiet()) == "waiting" for _ in range(1000))   # 80 s of nothing: still waiting


def test_click_is_not_speech():
    ep = Endpointer()
    ep.feed(loud())  # one loud frame (door slam / click)
    assert all(ep.feed(quiet()) == "waiting" for _ in range(5))


def test_max_length_45s():
    ep = Endpointer()
    st, n = feed_until(ep, loud, 1000)
    assert st == "done" and abs(n * FRAME_MS - 45000) <= 1000


def test_vad_callable_decides_speech():
    calls = []
    vad = lambda f: calls.append(1) or True   # noqa: E731 - everything is "speech"
    ep = Endpointer(vad=vad)
    assert [ep.feed(loud(300)) for _ in range(5)][-1] == "speech"   # quiet-ish but VAD says voice
    assert calls


def test_wav_bytes_header():
    b = to_wav_bytes(np.zeros(1600, dtype=np.int16))
    assert b[:4] == b"RIFF" and len(b) == 44 + 3200

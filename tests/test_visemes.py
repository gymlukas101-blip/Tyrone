import numpy as np

from monkey.audio.visemes import estimate_visemes

SR = 44100
N = 1024
t = np.arange(N) / SR
rng = np.random.default_rng(1)


def tone(*parts):
    x = sum(a * np.sin(2 * np.pi * f * t) for f, a in parts)
    return (x * 8000 / np.max(np.abs(x))).astype(np.int16)


def top(v):
    return max(v, key=v.get)


def test_silence():
    assert estimate_visemes(np.zeros(N, dtype=np.int16), SR) == {"viseme_sil": 1.0}


def test_closure_after_speech():
    assert top(estimate_visemes(np.zeros(N, dtype=np.int16), SR, prev_rms=5000)) == "viseme_PP"


def test_open_vowel():
    v = estimate_visemes(tone((150, 0.4), (750, 1.0), (1100, 0.5)), SR)
    assert top(v) in ("viseme_aa", "viseme_O")


def test_front_vowel():
    v = estimate_visemes(tone((150, 0.3), (300, 0.4), (2400, 1.0), (2800, 0.6)), SR)
    assert top(v) in ("viseme_E", "viseme_I")


def test_rounded_vowel():
    v = estimate_visemes(tone((150, 0.6), (320, 1.0), (450, 0.5)), SR)
    assert top(v) in ("viseme_O", "viseme_U")


def test_sibilant():
    noise = rng.normal(0, 1, N)
    hp = np.diff(np.diff(noise, prepend=0), prepend=0)  # emphasize highs
    x = (hp / np.max(np.abs(hp)) * 6000).astype(np.int16)
    assert top(estimate_visemes(x, SR)) in ("viseme_SS", "viseme_CH")


def test_weights_bounded_and_at_most_two():
    v = estimate_visemes(tone((200, 1.0), (900, 1.0), (2500, 1.0)), SR)
    assert 1 <= len(v) <= 2 and all(0 < w <= 1 for w in v.values())

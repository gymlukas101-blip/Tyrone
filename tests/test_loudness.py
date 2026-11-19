"""Monkey's voice is leveled to streaming loudness without clipping or pumping."""
from __future__ import annotations

import numpy as np

from monkey.audio.loudness import CEILING, TARGET_DBFS, Leveler, soft_limit
from monkey.audio.speaker import BLOCK

RATE = 44100


def speechlike(seconds: float, level_dbfs: float, seed: int = 0) -> np.ndarray:
    """Syllable-modulated harmonic signal with gaps between words, scaled to a gated RMS of level_dbfs."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * RATE)) / RATE
    f0 = 140 + 20 * np.sin(2 * np.pi * 0.7 * t)
    phase = 2 * np.pi * np.cumsum(f0) / RATE
    x = sum(np.sin(k * phase) / k for k in range(1, 12)) + 0.05 * rng.standard_normal(t.size)
    env = np.clip(np.sin(2 * np.pi * 4 * t), 0, None) * (np.sin(2 * np.pi * 0.5 * t) > -0.6)   # syllables + pauses
    x = x * env
    voiced = np.abs(x) > 1e-4
    x = x / np.sqrt(np.mean(x[voiced] ** 2)) * 10 ** (level_dbfs / 20)
    return np.clip(x * 32767, -32768, 32767).astype(np.int16)


def run(lev: Leveler, pcm: np.ndarray, **kw) -> np.ndarray:
    return np.concatenate([lev.process(pcm[i:i + BLOCK], **kw) for i in range(0, pcm.size, BLOCK)])


def gated_rms_db(pcm: np.ndarray) -> float:
    x = pcm.astype(np.float64) / 32768
    blocks = [x[i:i + BLOCK] for i in range(0, x.size - BLOCK, BLOCK)]
    loud = [np.mean(b * b) for b in blocks if 10 * np.log10(np.mean(b * b) + 1e-12) > -45]
    return 10 * np.log10(np.mean(loud))


def test_quiet_voice_is_raised_to_target():
    out = run(Leveler(), speechlike(6, -26))            # typical quiet TTS
    steady = out[RATE:]
    assert abs(gated_rms_db(steady) - TARGET_DBFS) < 2.0


def test_loud_voice_is_lowered_and_never_clips():
    out = run(Leveler(), speechlike(4, -8))
    assert np.max(np.abs(out.astype(np.int32))) <= int(CEILING * 32767) + 1
    assert gated_rms_db(out[RATE:]) < -10


def test_first_sentence_starts_near_target():
    out = run(Leveler(), speechlike(1.0, -24))          # no long ramp-up on the first words
    assert abs(gated_rms_db(out[: RATE // 2]) - TARGET_DBFS) < 3.0


def test_silence_does_not_pump_gain():
    lev = Leveler()
    run(lev, speechlike(2, -24))
    g = lev.gain
    run(lev, np.zeros(RATE * 3, dtype=np.int16))       # a long pause between replies
    assert abs(lev.gain - g) < 1e-6


def test_off_is_bit_exact_and_trim_scales():
    pcm = speechlike(1, -20)
    assert np.array_equal(run(Leveler(), pcm, enabled=False), pcm)
    half = run(Leveler(), pcm, enabled=False, trim=0.5)
    assert abs(gated_rms_db(half) - (gated_rms_db(pcm) - 6.02)) < 0.3


def test_soft_limit_is_identity_below_knee_and_bounded():
    y = np.linspace(-3, 3, 10001)
    z = soft_limit(y)
    assert np.all(np.abs(z) <= CEILING + 1e-9)
    small = np.abs(y) < 0.6
    assert np.array_equal(z[small], y[small])

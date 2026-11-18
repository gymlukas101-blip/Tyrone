"""Estimate mouth shapes (Oculus/Meta visemes) from the voice audio, block by block.

Fish Audio streams raw PCM with no phoneme timing, so this looks at each ~23 ms block:
loudness picks how open the mouth is; band energies, spectral centroid and zero-crossing
rate pick the shape (open vowels, front vowels, rounded vowels, s/sh hiss, f/th, closures).
It's a heuristic - good enough for a cartoon - and cheap (one FFT of 1024 samples).
"""
from __future__ import annotations

import numpy as np

SILENCE_RMS = 350.0      # int16 units
LOUD_RMS = 6000.0


def _band(power: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> float:
    m = (freqs >= lo) & (freqs < hi)
    return float(power[m].sum()) if m.any() else 0.0


def estimate_visemes(block: np.ndarray, sr: int, prev_rms: float = 0.0) -> dict[str, float]:
    """block: int16 mono samples. Returns {viseme_name: weight} with at most two entries."""
    x = block.astype(np.float32)
    if x.size < 64:
        return {"viseme_sil": 1.0}
    rms = float(np.sqrt(np.mean(x * x)))
    if rms < SILENCE_RMS:
        # A sudden drop right after speech reads as lips closing (p/b/m).
        if prev_rms > 3 * SILENCE_RMS:
            return {"viseme_PP": 0.7}
        return {"viseme_sil": 1.0}

    w = x * np.hanning(x.size)
    power = np.abs(np.fft.rfft(w)) ** 2
    freqs = np.fft.rfftfreq(x.size, 1.0 / sr)
    total = float(power.sum()) + 1e-9
    low = _band(power, freqs, 80, 500) / total       # F1 region of closed/rounded vowels
    mid = _band(power, freqs, 500, 1200) / total     # F1 of open vowels
    upper = _band(power, freqs, 1200, 3200) / total  # F2 of front vowels
    hiss = _band(power, freqs, 3200, 9000) / total   # fricatives / sibilants
    centroid = float((power * freqs).sum() / total)
    zcr = float(np.mean(np.abs(np.diff(np.signbit(x).astype(np.int8)))))

    amount = float(np.clip((rms - SILENCE_RMS) / (LOUD_RMS - SILENCE_RMS), 0.15, 1.0))

    scores: dict[str, float] = {}
    if hiss > 0.45 or (zcr > 0.25 and centroid > 3500):
        scores["viseme_SS" if centroid > 4500 else "viseme_CH"] = hiss
        scores["viseme_FF"] = hiss * 0.4
    else:
        scores["viseme_aa"] = mid * 1.4
        scores["viseme_O"] = low * 0.9 if centroid < 900 else low * 0.4
        scores["viseme_U"] = low * 0.6 if centroid < 600 else 0.0
        scores["viseme_E"] = upper * 0.9
        scores["viseme_I"] = upper * 0.7 if centroid > 1800 else upper * 0.3
        scores["viseme_nn"] = 0.15 if amount < 0.3 else 0.0

    top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:2]
    best = top[0][1] or 1.0
    out = {}
    for name, s in top:
        if s <= 0:
            continue
        out[name] = round(amount * (s / best) * (1.0 if name == top[0][0] else 0.5), 3)
    return out or {"viseme_sil": 1.0}

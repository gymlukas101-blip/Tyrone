"""Make Monkey's voice as loud as everything else on the PC.

YouTube, Spotify and most streaming normalize to about -14 LUFS. TTS engines come out much quieter (Fish around
-20..-24, the offline voice and Windows voices vary), so at the same system volume he sounded small next to a video.
The Leveler is a streaming loudness matcher that runs on the playback blocks:

- measures speech level only (silence between words doesn't drag the estimate down),
- remembers it across sentences so every reply starts at the right level,
- moves gain smoothly (no pumping), between -6 dB and +18 dB,
- finishes with a soft limiter so boosted peaks never clip (ceiling -1 dBFS).

TARGET_DBFS is the running speech level on 23 ms blocks; calibrated on real recorded speech (LibriSpeech) so the
output measures about -14 LUFS (ITU-R BS.1770), the streaming norm, with ~1% of samples touching the limiter.
"""
from __future__ import annotations

import numpy as np

TARGET_DBFS = -11.0
GATE_DBFS = -45.0
MAX_GAIN_DB, MIN_GAIN_DB = 18.0, -6.0
CEILING = 10 ** (-1.0 / 20)      # -1 dBFS
KNEE = 0.70                       # the limiter leaves everything below this untouched


def _db(x: float) -> float:
    return 20 * np.log10(max(x, 1e-9))


def soft_limit(y: np.ndarray, ceiling: float = CEILING, knee: float = KNEE) -> np.ndarray:
    """Identity below `knee`, then a smooth tanh curve that approaches but never exceeds `ceiling`."""
    a = np.abs(y)
    over = a > knee
    if not over.any():
        return y
    span = ceiling - knee
    out = y.copy()
    out[over] = np.sign(y[over]) * (knee + span * np.tanh((a[over] - knee) / span))
    return out


class Leveler:
    def __init__(self, target_dbfs: float = TARGET_DBFS):
        self.target = 10 ** (target_dbfs / 20)
        self.env: float | None = None     # running speech RMS (linear, full scale = 1.0)
        self.gain = 1.0

    def target_gain(self) -> float:
        if not self.env:
            return 1.0
        g = self.target / self.env
        return float(np.clip(g, 10 ** (MIN_GAIN_DB / 20), 10 ** (MAX_GAIN_DB / 20)))

    def process(self, block: np.ndarray, enabled: bool = True, trim: float = 1.0) -> np.ndarray:
        """int16 block in, int16 block out. `trim` is the user's voice volume (1.0 = matched loudness)."""
        if block.size == 0:
            return block
        x = block.astype(np.float32) / 32768.0
        if enabled:
            rms = float(np.sqrt(np.mean(x * x)))
            if _db(rms) > GATE_DBFS:
                if self.env is None:
                    self.env = rms
                    self.gain = self.target_gain()          # first words of the session: jump straight there
                else:
                    self.env += (0.25 if rms > self.env else 0.04) * (rms - self.env)   # quick up, slow down
                self.gain += 0.2 * (self.target_gain() - self.gain)   # only moves while he's talking: no pumping
            g = self.gain * trim
        else:
            g = trim
        if g == 1.0:
            return block
        y = soft_limit(x * g)
        return np.clip(np.round(y * 32767.0), -32768, 32767).astype(np.int16)

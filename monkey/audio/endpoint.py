"""Decide when the user has started and stopped talking (pure logic, easy to test)."""
from __future__ import annotations

import numpy as np

FRAME_MS = 80
SAMPLE_RATE = 16000
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 1280 - what openWakeWord expects


def rms(frame: np.ndarray) -> float:
    f = frame.astype(np.float32)
    return float(np.sqrt(np.mean(f * f))) if f.size else 0.0


class Endpointer:
    """Energy-based voice activity with an adaptive noise floor.

    feed() returns:
      "waiting"  - no speech yet
      "speech"   - currently speaking
      "done"     - speech ended (enough trailing silence) or max length reached
      "timeout"  - nobody said anything after waking up
    """

    def __init__(self, silence_ms: int = 900, max_ms: int = 20000, no_speech_ms: int = 5000,
                 min_speech_ms: int = 300, ratio: float = 3.0, floor_init: float = 200.0):
        self.silence_frames = silence_ms // FRAME_MS
        self.max_frames = max_ms // FRAME_MS
        self.no_speech_frames = no_speech_ms // FRAME_MS
        self.min_speech_frames = max(1, min_speech_ms // FRAME_MS)
        self.ratio = ratio
        self.floor = floor_init
        self.reset()

    def reset(self) -> None:
        self.frames: list[np.ndarray] = []
        self.speech_frames = 0
        self.trailing_silence = 0
        self.total = 0
        self.started = False

    def feed(self, frame: np.ndarray) -> str:
        level = rms(frame)
        self.total += 1
        self.frames.append(frame)
        loud = level > max(self.floor * self.ratio, 300.0)
        if not loud:
            # Track background noise only when it's quiet.
            self.floor = 0.95 * self.floor + 0.05 * level
        if loud:
            self.speech_frames += 1
            self.trailing_silence = 0
            if self.speech_frames >= self.min_speech_frames:
                self.started = True
        elif self.started:
            self.trailing_silence += 1
        if self.started and self.trailing_silence >= self.silence_frames:
            return "done"
        if self.total >= self.max_frames:
            return "done" if self.started else "timeout"
        if not self.started and self.total >= self.no_speech_frames:
            return "timeout"
        return "speech" if self.started else "waiting"

    def audio(self) -> np.ndarray:
        return np.concatenate(self.frames) if self.frames else np.zeros(0, dtype=np.int16)

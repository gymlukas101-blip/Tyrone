"""Decide when the user has started and stopped talking (pure logic, easy to test).

Speech/no-speech per 80 ms frame comes from a neural voice detector (Silero VAD via sherpa-onnx, see vad.py)
when available, else from loudness with hysteresis. On top of that, patience rules decide when you're done:
a natural pause mid-sentence must not end your turn.
"""
from __future__ import annotations

from collections import deque
from typing import Callable

import numpy as np

FRAME_MS = 80
SAMPLE_RATE = 16000
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 1280 - what openWakeWord expects

END_SILENCE_PRESETS = {"quick": 900, "normal": 1400, "patient": 2000}


def rms(frame: np.ndarray) -> float:
    f = frame.astype(np.float32)
    return float(np.sqrt(np.mean(f * f))) if f.size else 0.0


class Endpointer:
    """feed() returns:
      "waiting"  - no speech yet
      "speech"   - currently speaking (including short pauses)
      "done"     - speech ended (enough trailing silence) or max length reached
      "timeout"  - nobody said anything (only when no_speech_ms is set)

    silence_ms     trailing silence that ends a turn
    short_extra_ms extra patience while you've said less than short_ms (e.g. "Hey Monkey... um, what's")
    no_speech_ms   give up if nothing is said for this long; None = wait forever (conversation mode)
    min_speech_ms  voiced time needed before it counts as speech (a click or cough isn't)
    vad            optional callable(frame) -> bool (Silero); without it, loudness with hysteresis is used
    """

    def __init__(self, silence_ms: int = 1400, max_ms: int = 45000, no_speech_ms: int | None = 5000,
                 min_speech_ms: int = 300, ratio: float = 3.0, cont_ratio: float = 1.8, floor_init: float = 200.0,
                 short_ms: int = 1500, short_extra_ms: int = 400, preroll_ms: int = 480, tail_ms: int = 320,
                 vad: Callable[[np.ndarray], bool] | None = None):
        self.silence_frames = max(1, silence_ms // FRAME_MS)
        self.max_frames = max_ms // FRAME_MS
        self.no_speech_frames = None if no_speech_ms is None else max(1, no_speech_ms // FRAME_MS)
        self.min_speech_frames = max(1, min_speech_ms // FRAME_MS)
        self.short_frames = short_ms // FRAME_MS
        self.short_extra = short_extra_ms // FRAME_MS
        self.preroll = max(1, preroll_ms // FRAME_MS)
        self.tail = max(1, tail_ms // FRAME_MS)
        self.ratio, self.cont_ratio = ratio, cont_ratio
        self.floor = floor_init
        self.vad = vad
        self.reset()

    def reset(self) -> None:
        self.frames: list[np.ndarray] = []
        self._pre: deque[np.ndarray] = deque(maxlen=self.preroll)
        self.speech_frames = 0
        self.run = 0                 # consecutive voiced frames before speech has started
        self.trailing_silence = 0
        self.total = 0
        self.started = False
        self.last_voiced = -1        # index into self.frames

    def _voiced(self, frame: np.ndarray) -> bool:
        level = rms(frame)
        if self.vad is not None:
            try:
                return bool(self.vad(frame)) and level > 60.0
            except Exception:  # noqa: BLE001 - fall back to loudness for this frame
                pass
        thr = self.floor * (self.cont_ratio if self.started else self.ratio)
        voiced = level > max(thr, 220.0 if self.started else 300.0)
        if not voiced and not self.started:
            # Track background noise only before you start talking (so soft words can't raise it).
            self.floor = 0.95 * self.floor + 0.05 * level
        return voiced

    def feed(self, frame: np.ndarray) -> str:
        self.total += 1
        voiced = self._voiced(frame)
        if not self.started:
            self._pre.append(frame)
            self.run = self.run + 1 if voiced else 0
            self.speech_frames += 1 if voiced else 0
            if self.run >= self.min_speech_frames:
                self.started = True
                self.frames = list(self._pre)              # keep a little audio from just before you spoke
                self.last_voiced = len(self.frames) - 1
                self.trailing_silence = 0
            elif self.no_speech_frames is not None and self.total >= self.no_speech_frames:
                return "timeout"
            elif self.no_speech_frames is None and self.total >= self.max_frames:
                self.total = 0                             # waiting forever: don't let the counter overflow
            return "speech" if self.started else "waiting"
        self.frames.append(frame)
        if voiced:
            self.speech_frames += 1
            self.trailing_silence = 0
            self.last_voiced = len(self.frames) - 1
        else:
            self.trailing_silence += 1
        need = self.silence_frames + (self.short_extra if self.speech_frames < self.short_frames else 0)
        if self.trailing_silence >= need or len(self.frames) >= self.max_frames:
            return "done"
        return "speech"

    def audio(self) -> np.ndarray:
        """What you said: from just before you started to a short tail after your last word."""
        if not self.frames:
            return np.zeros(0, dtype=np.int16)
        end = len(self.frames) if self.last_voiced < 0 else min(len(self.frames), self.last_voiced + 1 + self.tail)
        return np.concatenate(self.frames[:end])

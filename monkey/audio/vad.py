"""Neural voice activity detection (Silero VAD, ~2 MB) through sherpa-onnx, which Monkey already ships for
the wake word. Tells speech from keyboard clacks, fans and music far better than loudness, so soft words at
the end of a sentence still count as speech and Monkey doesn't cut you off.

The model lives in wakeword/vad/silero_vad.onnx (bundled by CI) or %APPDATA%\\Monkey\\wakeword\\vad.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .endpoint import SAMPLE_RATE

log = logging.getLogger(__name__)
MODEL_NAME = "silero_vad.onnx"


def find_vad(user_dir: Path | None, bundled_dir: Path | None) -> Path | None:
    for d in (user_dir, bundled_dir):
        if d is None:
            continue
        for p in (Path(d) / "vad" / MODEL_NAME, Path(d) / MODEL_NAME):
            if p.exists():
                return p
    return None


class SileroVAD:
    """is_speech(frame) for 80 ms int16 frames at 16 kHz. Our Endpointer owns the patience rules, so the
    detector's own silence smoothing is kept short."""

    def __init__(self, model_path: Path, threshold: float = 0.45):
        import sherpa_onnx as so

        cfg = so.VadModelConfig()
        cfg.silero_vad.model = str(model_path)
        cfg.silero_vad.threshold = threshold
        cfg.silero_vad.min_silence_duration = 0.1
        cfg.silero_vad.min_speech_duration = 0.1
        cfg.silero_vad.window_size = 512
        cfg.sample_rate = SAMPLE_RATE
        cfg.num_threads = 1
        cfg.provider = "cpu"
        if not cfg.validate():
            raise RuntimeError(f"bad VAD model: {model_path}")
        self._vad = so.VoiceActivityDetector(cfg, buffer_size_in_seconds=30)

    def __call__(self, frame: np.ndarray) -> bool:
        return self.is_speech(frame)

    def is_speech(self, frame: np.ndarray) -> bool:
        self._vad.accept_waveform((frame.astype(np.float32) / 32768.0).tolist())
        while not self._vad.empty():          # we only need the live state; drop finished segments
            self._vad.pop()
        return bool(self._vad.is_speech_detected())

    def reset(self) -> None:
        self._vad.reset()


def load_vad(user_dir: Path | None, bundled_dir: Path | None) -> SileroVAD | None:
    path = find_vad(user_dir, bundled_dir)
    if path is None:
        log.info("Silero VAD model not found; using loudness-based speech detection")
        return None
    try:
        return SileroVAD(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("Silero VAD unavailable: %s", exc)
        return None

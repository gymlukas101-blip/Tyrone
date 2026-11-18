"""Microphone loop: wake word ("Yo Tyrone") → record until you stop talking → callback.

Uses openWakeWord. Until the custom yo_tyrone.onnx model is trained and bundled,
it falls back to the pretrained "hey_jarvis" model (say "Hey Jarvis").
Push-to-talk (global hotkey) always works too.
"""
from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from .endpoint import FRAME_SAMPLES, SAMPLE_RATE, Endpointer

log = logging.getLogger(__name__)


def load_wakeword(model_name: str, bundled_dir: Path, user_dir: Path | None = None):
    """Returns (model, label) or (None, reason).

    A custom model dropped into user_dir (%APPDATA%\\Tyrone\\wakeword) wins over the bundled one,
    so you can add yo_tyrone.onnx without rebuilding the app.
    """
    try:
        import openwakeword
        from openwakeword.model import Model
    except Exception as exc:  # noqa: BLE001
        return None, f"openWakeWord not installed ({exc})"

    def make(path: str):
        try:  # openWakeWord >= 0.5
            return Model(wakeword_models=[path], inference_framework="onnx")
        except TypeError:  # 0.4.x
            return Model(wakeword_model_paths=[path])

    candidates = [d / f"{model_name}.onnx" for d in (user_dir, bundled_dir) if d is not None]
    custom = next((c for c in candidates if c.exists()), None)
    try:
        if custom is not None:
            return make(str(custom)), "Yo Tyrone"
        resources = Path(openwakeword.__file__).parent / "resources" / "models"
        found = sorted(resources.glob("hey_jarvis*.onnx")) + sorted(bundled_dir.glob("hey_jarvis*.onnx"))
        if not found and hasattr(openwakeword.utils, "download_models"):
            openwakeword.utils.download_models(model_names=["hey_jarvis"])
            found = sorted(resources.glob("hey_jarvis*.onnx"))
        if not found:
            return None, "no wake word model found (use the push-to-talk hotkey)"
        return make(str(found[0])), "Hey Jarvis (until Yo Tyrone is trained)"
    except Exception as exc:  # noqa: BLE001
        return None, f"wake word unavailable ({exc})"


class Listener:
    def __init__(
        self,
        on_wake: Callable[[], None],
        on_utterance: Callable[[np.ndarray], None],
        on_level: Callable[[float], None] | None = None,
        on_timeout: Callable[[], None] | None = None,
        wakeword_model=None,
        threshold: Callable[[], float] = lambda: 0.5,
        is_speaking: Callable[[], bool] = lambda: False,
    ):
        self.on_wake = on_wake
        self.on_utterance = on_utterance
        self.on_level = on_level
        self.on_timeout = on_timeout
        self.ww = wakeword_model
        self.threshold = threshold
        self.is_speaking = is_speaking
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._mode = "wake"  # "wake" | "record"
        self._ep = Endpointer()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None
        self.muted = False

    # ---- control -------------------------------------------------------
    def start(self) -> None:
        import sounddevice as sd

        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                      blocksize=FRAME_SAMPLES, callback=self._callback)
        self._stream.start()
        self._thread = threading.Thread(target=self._loop, name="listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()

    def push_to_talk(self) -> None:
        """Start recording immediately (hotkey or mic button)."""
        self._begin_recording()

    def _begin_recording(self) -> None:
        self._ep.reset()
        self._mode = "record"
        if self.ww is not None:
            self.ww.reset()

    # ---- audio thread ------------------------------------------------
    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        if self.muted:
            return
        try:
            self._q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.on_level is not None:
                self.on_level(float(np.abs(frame).mean()) / 3000.0)
            if self._mode == "wake":
                if self.ww is None:
                    continue
                scores = self.ww.predict(frame)
                score = max(scores.values()) if scores else 0.0
                # Be stricter while Tyrone is talking so his own voice doesn't wake him.
                thr = self.threshold() + (0.25 if self.is_speaking() else 0.0)
                if score >= min(thr, 0.95):
                    log.info("wake word %.2f", score)
                    self._begin_recording()
                    self.on_wake()
            else:
                state = self._ep.feed(frame)
                if state == "done":
                    audio = self._ep.audio()
                    self._mode = "wake"
                    threading.Thread(target=self.on_utterance, args=(audio,), daemon=True).start()
                elif state == "timeout":
                    self._mode = "wake"
                    if self.on_timeout:
                        self.on_timeout()

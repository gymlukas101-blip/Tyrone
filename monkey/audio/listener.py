"""Microphone loop: wake word ("Hey Monkey") → record until you stop talking → callback.

"Hey Monkey" is spotted by sherpa-onnx keyword spotting (no training needed); a trained
openWakeWord model can replace it, and "Hey Jarvis" is the last fallback.
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


def load_wakeword(model_name: str, bundled_dir: Path, user_dir: Path | None = None,
                  phrase: str = "hey monkey", sensitivity: float = 0.5, work_dir: Path | None = None):
    """Returns (model, label) or (None, reason). Tried in order:

    1. A trained openWakeWord model named `model_name` (most robust) - %APPDATA%\\Monkey\\wakeword wins
       over the bundled folder, so you can drop one in without rebuilding.
    2. sherpa-onnx open-vocabulary keyword spotting for `phrase` (works today, no training).
    3. openWakeWord's pretrained "Hey Jarvis".
    """
    oww_model = None
    try:
        import openwakeword
        from openwakeword.model import Model

        def make(path: str):
            try:  # openWakeWord >= 0.5
                return Model(wakeword_models=[path], inference_framework="onnx")
            except TypeError:  # 0.4.x
                return Model(wakeword_model_paths=[path])

        candidates = [d / f"{model_name}.onnx" for d in (user_dir, bundled_dir) if d is not None]
        custom = next((c for c in candidates if c.exists()), None)
        if custom is not None:
            return make(str(custom)), phrase.title()
        oww_model = (openwakeword, make)
    except Exception as exc:  # noqa: BLE001
        log.info("openWakeWord unavailable: %s", exc)

    try:
        from .kws import SherpaWakeWord, find_model

        kws_dir = find_model(user_dir, bundled_dir)
        if kws_dir is not None:
            phrases = [p.strip() for p in phrase.split(",") if p.strip()]
            return (SherpaWakeWord(kws_dir, phrases, work_dir or (user_dir or bundled_dir), sensitivity),
                    phrases[0].title())
    except Exception as exc:  # noqa: BLE001
        log.warning("keyword spotter unavailable: %s", exc)

    if oww_model is None:
        return None, "no wake word engine (use the push-to-talk hotkey)"
    openwakeword, make = oww_model
    try:
        resources = Path(openwakeword.__file__).parent / "resources" / "models"
        found = sorted(resources.glob("hey_jarvis*.onnx")) + sorted(bundled_dir.glob("hey_jarvis*.onnx"))
        if not found and hasattr(openwakeword.utils, "download_models"):
            openwakeword.utils.download_models(model_names=["hey_jarvis"])
            found = sorted(resources.glob("hey_jarvis*.onnx"))
        if not found:
            return None, "no wake word model found (use the push-to-talk hotkey)"
        return make(str(found[0])), "Hey Jarvis (Hey Monkey model missing)"
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
                # Be stricter while Monkey is talking so his own voice doesn't wake him.
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

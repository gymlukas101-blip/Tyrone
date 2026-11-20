"""Microphone loop: wake word ("Hey Monkey") → record until you stop talking → callback.

"Hey Monkey" is spotted by sherpa-onnx keyword spotting (no training needed); a trained
openWakeWord model can replace it, and "Hey Jarvis" is the last fallback.
Push-to-talk (global hotkey) always works too.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from .endpoint import FRAME_SAMPLES, SAMPLE_RATE, Endpointer

log = logging.getLogger(__name__)


STOP_PHRASES = ("monkey stop", "stop monkey")


def load_wakeword(model_name: str, bundled_dir: Path, user_dir: Path | None = None,
                  phrase: str = "hey monkey", sensitivity: float = 0.5, work_dir: Path | None = None,
                  stop_phrases: tuple[str, ...] = STOP_PHRASES):
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
            return (SherpaWakeWord(kws_dir, phrases, work_dir or (user_dir or bundled_dir), sensitivity,
                                   stop_phrases=stop_phrases), phrases[0].title())
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
    """Modes:
      wake          waiting for "Hey Monkey" (also while Monkey thinks/talks, so you can interrupt him)
      record        recording after the wake word / push-to-talk (gives up after 5 s of nothing)
      conversation  between turns of a conversation: no wake word needed, waits until you talk
                    (or until the app's quiet deadline passes, then on_conversation_idle fires)
    The loop never dies on an error, and a dead/disconnected microphone is reopened automatically.
    """

    STALL_S = 3.0
    REOPEN_BACKOFF = (1, 2, 5, 10)

    def __init__(
        self,
        on_wake: Callable[[], None],
        on_utterance: Callable[[np.ndarray], None],
        on_level: Callable[[float], None] | None = None,
        on_timeout: Callable[[], None] | None = None,
        wakeword_model=None,
        threshold: Callable[[], float] = lambda: 0.5,
        is_speaking: Callable[[], bool] = lambda: False,
        vad=None,
        end_silence_ms: Callable[[], int] = lambda: 1400,
        on_conversation_idle: Callable[[], None] | None = None,
        on_reconnect: Callable[[str], None] | None = None,
        stream_factory: Callable | None = None,
        on_stop: Callable[[], None] | None = None,
        on_mark: Callable[[str, float], None] | None = None,
    ):
        self.on_wake = on_wake
        self.on_utterance = on_utterance
        self.on_level = on_level
        self.on_timeout = on_timeout
        self.on_conversation_idle = on_conversation_idle
        self.on_reconnect = on_reconnect
        self.on_stop = on_stop             # "Monkey, stop" while he talks: silence him, don't start recording
        self.on_mark = on_mark             # turn tracer: speech_start / last_voiced / endpoint timestamps
        self._speech_marked = False
        self.last_speech_start = 0.0       # monotonic time the latest utterance began (echo guard timing)
        self.ww = wakeword_model
        self.threshold = threshold
        self.is_speaking = is_speaking
        self.vad = vad
        self.end_silence_ms = end_silence_ms
        self._stream_factory = stream_factory
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._mode = "wake"  # "wake" | "record" | "conversation"
        self.last_source = "wake"          # where the latest utterance came from ("wake" | "conversation")
        self._conv_deadline = 0.0
        self._ep = self._endpointer()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None
        self._last_frame = 0.0
        self._reopens = 0
        self.muted = False

    @property
    def mode(self) -> str:
        return self._mode

    def _endpointer(self, conversation: bool = False) -> Endpointer:
        if self.vad is not None:
            try:
                self.vad.reset()
            except Exception:  # noqa: BLE001
                pass
        return Endpointer(silence_ms=int(self.end_silence_ms()), no_speech_ms=None if conversation else 5000,
                          min_speech_ms=480 if conversation else 300, vad=self.vad)

    # ---- control -------------------------------------------------------
    def _open_stream(self):
        if self._stream_factory is not None:
            return self._stream_factory(self._callback)
        import sounddevice as sd

        from .devices import PA_LOCK

        with PA_LOCK:
            st = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                blocksize=FRAME_SAMPLES, callback=self._callback)
            st.start()
            return st

    def start(self) -> None:
        self._stream = self._open_stream()
        if self._stream_factory is not None:
            self._stream.start()
        self._last_frame = time.monotonic()
        self._thread = threading.Thread(target=self._loop, name="listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_stream()

    def _close_stream(self) -> None:
        from .devices import PA_LOCK

        with PA_LOCK:
            st, self._stream = self._stream, None
            if st is not None:
                try:
                    st.stop()
                    st.close()
                except Exception:  # noqa: BLE001
                    pass

    def push_to_talk(self) -> None:
        """Start recording immediately (hotkey or mic button)."""
        self._begin_recording()

    def enter_conversation(self, idle_s: float) -> None:
        """Listen for your next turn without the wake word, until idle_s of quiet."""
        self._speech_marked = False
        self._ep = self._endpointer(conversation=True)
        self._conv_deadline = time.monotonic() + max(5.0, float(idle_s))
        self._mode = "conversation"

    def end_conversation(self) -> None:
        if self._mode == "conversation":
            self._mode = "wake"

    def cancel(self) -> None:
        """You tapped ✕: stop listening right now, even mid-recording (back to waiting for the wake word)."""
        if self._mode in ("conversation", "record"):
            self._mode = "wake"

    def _mark(self, name: str, at: float) -> None:
        if self.on_mark is not None:
            try:
                self.on_mark(name, at)
            except Exception:  # noqa: BLE001
                pass

    def _begin_recording(self) -> None:
        self._speech_marked = False
        self._ep = self._endpointer()
        self._mode = "record"
        if self.ww is not None:
            try:
                self.ww.reset()
            except Exception:  # noqa: BLE001
                pass

    # ---- audio thread ------------------------------------------------
    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        self._last_frame = time.monotonic()
        if self.muted:
            return
        try:
            self._q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def _watchdog(self) -> None:
        """No audio for a few seconds (PC slept, headset unplugged, driver hiccup): reopen the microphone."""
        if self.muted or time.monotonic() - self._last_frame < self.STALL_S:
            return
        delay = self.REOPEN_BACKOFF[min(self._reopens, len(self.REOPEN_BACKOFF) - 1)]
        log.warning("microphone silent for %.0f s; reopening (attempt %d)",
                    time.monotonic() - self._last_frame, self._reopens + 1)
        self._close_stream()
        try:
            if self._stream_factory is None:
                from .devices import reset_portaudio

                reset_portaudio()        # refresh the device list; the speaker reopens its stream too
            self._stream = self._open_stream()
            if self._stream_factory is not None:
                self._stream.start()
            self._last_frame = time.monotonic()
            self._reopens = 0
            if self.on_reconnect is not None:
                self.on_reconnect("Microphone reconnected.")
        except Exception as exc:  # noqa: BLE001
            self._reopens += 1
            log.warning("microphone reopen failed: %s", exc)
            self._last_frame = time.monotonic() + delay - self.STALL_S    # try again after the backoff

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._q.get(timeout=0.5)
            except queue.Empty:
                self._tick_idle()
                try:
                    self._watchdog()
                except Exception:  # noqa: BLE001
                    log.exception("mic watchdog")
                continue
            try:
                self._step(frame)
            except Exception:  # noqa: BLE001 - one bad frame must never kill listening
                log.exception("listener frame failed")
                if self._mode == "record":
                    self._ep = self._endpointer()

    def _tick_idle(self) -> None:
        if self._mode == "conversation" and not self._ep.started and time.monotonic() > self._conv_deadline:
            self._mode = "wake"
            if self.on_conversation_idle is not None:
                self.on_conversation_idle()

    def _step(self, frame: np.ndarray) -> None:
        if self.on_level is not None:
            try:
                self.on_level(float(np.abs(frame).mean()) / 3000.0)
            except Exception:  # noqa: BLE001
                pass
        if self._mode == "wake":
            if self.ww is None:
                return
            scores = self.ww.predict(frame)
            stop_names = getattr(self.ww, "stop_names", ())
            if stop_names and any(scores.get(n, 0.0) >= 1.0 for n in stop_names):
                if self.is_speaking() and self.on_stop is not None:
                    log.info("stop keyword while speaking")
                    self.on_stop()
                return                                  # never a wake: it doesn't start a recording
            score = max((v for k, v in scores.items() if k not in stop_names), default=0.0)
            # Be stricter while Monkey is talking so his own voice doesn't wake him.
            # (+0.1, not more: "Hey Monkey" must still interrupt him; echo of his own voice rarely scores high)
            thr = self.threshold() + (0.1 if self.is_speaking() else 0.0)
            if score >= min(thr, 0.95):
                log.info("wake word %.2f", score)
                self._begin_recording()
                self.on_wake()
            return
        if self._mode == "conversation":
            self._tick_idle()
            if self._mode != "conversation":
                return
        state = self._ep.feed(frame)
        now = time.monotonic()
        if self._ep.started and not self._speech_marked:
            self._speech_marked = True
            self.last_speech_start = now
            self._mark("speech_start", now)
        if state == "done":
            from .endpoint import FRAME_MS

            self._mark("last_voiced", now - self._ep.trailing_silence * FRAME_MS / 1000.0)
            self._mark("endpoint", now)
            audio = self._ep.audio()
            self.last_source = self._mode
            self._mode = "wake"
            threading.Thread(target=self.on_utterance, args=(audio,), daemon=True).start()
        elif state == "timeout":
            self._mode = "wake"
            if self.on_timeout:
                self.on_timeout()

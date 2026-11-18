"""Queue sentences → synthesize → play, while reporting loudness for lip sync.

Synthesis of the next sentence overlaps playback of the current one, so Monkey
starts talking after the first sentence instead of after the whole reply.
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

import numpy as np

from .tts import TTS_RATE

log = logging.getLogger(__name__)
BLOCK = 1024  # ~23ms at 44.1k -> ~43 mouth updates per second


class Speaker:
    def __init__(self, engines: list, on_level: Callable[[float], None], on_state: Callable[[bool], None]):
        self.engines = engines            # tried in order (Fish first, system voice fallback)
        self.on_level = on_level
        self.on_state = on_state
        self._sentences: queue.Queue[str | None] = queue.Queue()
        self._audio: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=400)
        self._buf = np.zeros(0, dtype=np.int16)
        self._gen = 0                     # bumps on stop() to discard stale audio
        self._speaking = False
        self._pending = 0
        self._lock = threading.Lock()
        self._stream = None
        threading.Thread(target=self._synth_loop, name="tts", daemon=True).start()

    @property
    def speaking(self) -> bool:
        return self._speaking

    def start(self) -> None:
        import sounddevice as sd

        self._stream = sd.OutputStream(samplerate=TTS_RATE, channels=1, dtype="int16",
                                       blocksize=BLOCK, callback=self._callback)
        self._stream.start()

    def say(self, sentence: str) -> None:
        with self._lock:
            self._pending += 1
        self._set_speaking(True)
        self._sentences.put(sentence)

    def stop(self) -> None:
        """Barge-in: drop everything queued and stop talking now."""
        with self._lock:
            self._gen += 1
            self._pending = 0
            while not self._sentences.empty():
                self._sentences.get_nowait()
            while not self._audio.empty():
                self._audio.get_nowait()
            self._buf = np.zeros(0, dtype=np.int16)
        self._set_speaking(False)

    # ---- internals -----------------------------------------------------
    def _set_speaking(self, value: bool) -> None:
        if value != self._speaking:
            self._speaking = value
            self.on_state(value)
            if not value:
                self.on_level(0.0)

    def _synth_loop(self) -> None:
        while True:
            sentence = self._sentences.get()
            if sentence is None:
                return
            gen = self._gen
            for engine in self.engines:
                try:
                    if not engine.available():
                        continue
                    for chunk in engine.stream_pcm(sentence):
                        if gen != self._gen:
                            break
                        self._audio.put(chunk)
                    break
                except Exception as exc:  # noqa: BLE001 - try the next engine
                    log.warning("TTS engine %s failed: %s", type(engine).__name__, exc)
            if gen == self._gen:
                self._audio.put(None)  # end-of-sentence marker

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ARG002
        out = np.zeros(frames, dtype=np.int16)
        filled = 0
        while filled < frames:
            if self._buf.size == 0:
                try:
                    nxt = self._audio.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    with self._lock:
                        self._pending = max(0, self._pending - 1)
                    continue
                self._buf = nxt
            take = min(frames - filled, self._buf.size)
            out[filled:filled + take] = self._buf[:take]
            self._buf = self._buf[take:]
            filled += take
        outdata[:, 0] = out
        level = float(np.sqrt(np.mean(out.astype(np.float32) ** 2))) / 6000.0 if filled else 0.0
        self.on_level(min(1.0, level))
        if filled == 0 and self._pending == 0 and self._audio.empty() and self._speaking:
            self._set_speaking(False)

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
from .visemes import estimate_visemes

log = logging.getLogger(__name__)
BLOCK = 1024  # ~23ms at 44.1k -> ~43 mouth updates per second
STALL_S = 12.0   # "speaking" with no audio for this long = something hung: reset so Monkey never gets stuck


def _deadline(text: str) -> float:
    """Longest we wait for an engine to START producing audio for one sentence."""
    return 8.0 + 0.06 * len(text)


class EngineTimeout(RuntimeError):
    pass


class Speaker:
    def __init__(self, engines: list, on_level: Callable[[float], None], on_state: Callable[[bool], None],
                 on_visemes: Callable[[dict], None] | None = None,
                 on_fallback: Callable[[str, Exception], None] | None = None):
        self.engines = engines            # tried in order (Fish first, system voice fallback)
        self.on_fallback = on_fallback    # told when the preferred voice fails and a fallback is used
        self.on_level = on_level
        self.on_visemes = on_visemes
        self._prev_rms = 0.0
        self.on_state = on_state
        self._sentences: queue.Queue[str | None] = queue.Queue()
        self._audio: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=400)
        self._buf = np.zeros(0, dtype=np.int16)
        self._gen = 0                     # bumps on stop() to discard stale audio
        self._speaking = False
        self._pending = 0
        self._lock = threading.Lock()
        self._stream = None
        self._last_audio = 0.0
        threading.Thread(target=self._synth_loop, name="tts", daemon=True).start()
        threading.Thread(target=self._watchdog, name="tts-watchdog", daemon=True).start()

    @property
    def speaking(self) -> bool:
        return self._speaking

    def start(self) -> None:
        import sounddevice as sd

        self._stream = sd.OutputStream(samplerate=TTS_RATE, channels=1, dtype="int16",
                                       blocksize=BLOCK, callback=self._callback)
        self._stream.start()

    def say(self, sentence: str) -> None:
        import time

        with self._lock:
            self._pending += 1
        self._last_audio = time.monotonic()
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

    def _run_engine(self, engine, sentence: str, gen: int) -> None:
        """Stream one sentence from an engine on a helper thread, so a hung engine can't freeze Monkey."""
        q: queue.Queue = queue.Queue()

        def work():
            try:
                for chunk in engine.stream_pcm(sentence):
                    q.put(chunk)
                q.put(StopIteration)
            except Exception as exc:  # noqa: BLE001
                q.put(exc)

        threading.Thread(target=work, name=f"tts-{type(engine).__name__}", daemon=True).start()
        timeout, got = _deadline(sentence), False
        while True:
            try:
                item = q.get(timeout=timeout if not got else 15.0)
            except queue.Empty:
                raise EngineTimeout(f"{type(engine).__name__} didn't produce audio in time") from None
            if item is StopIteration:
                if not got:
                    raise RuntimeError(f"{type(engine).__name__} returned no audio")
                return
            if isinstance(item, Exception):
                if got:          # failed mid-sentence: keep what played, don't repeat the start on another voice
                    log.warning("TTS engine %s failed mid-sentence: %s", type(engine).__name__, item)
                    return
                raise item
            got = True
            if gen != self._gen:
                return
            self._audio.put(item)

    def _watchdog(self) -> None:
        import time

        while True:
            time.sleep(1.0)
            if self._speaking and self._sentences.empty() and self._audio.empty() and self._buf.size == 0 \
                    and time.monotonic() - self._last_audio > STALL_S:
                log.warning("speaker stalled (pending=%s); resetting", self._pending)
                with self._lock:
                    self._pending = 0
                self._set_speaking(False)

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
                    self._run_engine(engine, sentence, gen)
                    break
                except Exception as exc:  # noqa: BLE001 - try the next engine
                    log.warning("TTS engine %s failed: %s", type(engine).__name__, exc)
                    if self.on_fallback is not None and engine is self.engines[0]:
                        try:
                            self.on_fallback(type(engine).__name__, exc)
                        except Exception:  # noqa: BLE001
                            pass
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
            self._last_audio = __import__("time").monotonic()
            take = min(frames - filled, self._buf.size)
            out[filled:filled + take] = self._buf[:take]
            self._buf = self._buf[take:]
            filled += take
        outdata[:, 0] = out
        rms = float(np.sqrt(np.mean(out.astype(np.float32) ** 2))) if filled else 0.0
        self.on_level(min(1.0, rms / 6000.0))
        if self.on_visemes is not None and (filled or self._prev_rms):
            self.on_visemes(estimate_visemes(out, TTS_RATE, self._prev_rms))  # one 1024-pt FFT: microseconds
        self._prev_rms = rms
        if filled == 0 and self._pending == 0 and self._audio.empty() and self._speaking:
            self._set_speaking(False)

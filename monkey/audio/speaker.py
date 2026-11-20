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

from .loudness import Leveler
from .tts import TTS_RATE
from .lipsync import TextLipSync, blend
from .visemes import estimate_visemes

log = logging.getLogger(__name__)
BLOCK = 1024  # ~23ms at 44.1k -> ~43 mouth updates per second
STALL_S = 12.0   # "speaking" with no audio *and no engine working* this long = something hung: reset


def _deadline(text: str) -> float:
    """Longest we wait for an engine to START producing audio for one sentence."""
    return 8.0 + 0.06 * len(text)


class EngineTimeout(RuntimeError):
    pass


class Speaker:
    def __init__(self, engines: list, on_level: Callable[[float], None], on_state: Callable[[bool], None],
                 on_visemes: Callable[[dict], None] | None = None,
                 on_fallback: Callable[[str, Exception], None] | None = None,
                 loudness: Callable[[], tuple[bool, float]] | None = None):
        self.engines = engines            # tried in order (Fish first, system voice fallback)
        self.on_fallback = on_fallback    # told when the preferred voice fails and a fallback is used
        self.on_level = on_level
        self.loudness = loudness or (lambda: (True, 1.0))   # (match other apps' loudness, voice volume trim)
        self.leveler = Leveler()
        self.on_visemes = on_visemes
        self._prev_rms = 0.0
        self.text_lipsync = True          # sentence text picks the mouth shapes, audio times them (lipsync.py)
        self._lip: TextLipSync | None = None
        self.on_state = on_state
        self._sentences: queue.Queue[str | None] = queue.Queue()
        self._audio: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=400)
        self._buf = np.zeros(0, dtype=np.int16)
        self._gen = 0                     # bumps on stop() to discard stale audio
        self._speaking = False
        self._pending = 0
        self._lock = threading.Lock()
        self._stream = None
        self._want_stream = False         # start() was called: the watchdog keeps a stream open from then on
        self._last_audio = 0.0
        self._in_engine = False           # an engine is producing this sentence (it has its own deadline)
        self._notify: queue.Queue[bool] = queue.Queue()   # speaking-state changes, delivered in order
        # Turn tracer hook: timing(name, at) with "first_audio_packet" (an engine produced audio),
        # "first_audio_played" and "playback_stopped" (when the sound reaches/leaves the speaker, output latency included)
        self.timing: Callable[..., None] | None = None
        self._stop_at: float | None = None
        self._await_first = False
        threading.Thread(target=self._notify_loop, name="tts-state", daemon=True).start()
        threading.Thread(target=self._synth_loop, name="tts", daemon=True).start()
        threading.Thread(target=self._watchdog, name="tts-watchdog", daemon=True).start()

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def output_latency(self) -> float:
        """Seconds between a sample leaving us and reaching the speaker (the device's output buffer)."""
        try:
            return float(self._stream.latency) if self._stream is not None else 0.1
        except Exception:  # noqa: BLE001
            return 0.1

    def start(self) -> None:
        from .devices import on_reset

        self._want_stream = True
        on_reset(self.reopen, before=self._close)   # a microphone reconnect resets PortAudio: close first, reopen after
        try:
            self._open()
        except Exception:  # noqa: BLE001 - no output device right now; the watchdog keeps trying
            log.warning("couldn't open the speaker; will retry", exc_info=True)

    def _open(self) -> None:
        import sounddevice as sd

        from .devices import PA_LOCK

        with PA_LOCK:
            if self._stream is not None:
                return                    # already open (reopen raced the watchdog): nothing to do
            st = sd.OutputStream(samplerate=TTS_RATE, channels=1, dtype="int16",
                                 blocksize=BLOCK, callback=self._callback)
            st.start()
            self._stream = st

    def _close(self) -> None:
        """Abort and close the current stream (PA_LOCK held by the caller or taken here)."""
        from .devices import PA_LOCK

        with PA_LOCK:
            old, self._stream = self._stream, None
            if old is not None:
                for fn in (old.abort, old.close):
                    try:
                        fn()
                    except Exception:  # noqa: BLE001 - already dead after a PortAudio reset
                        pass

    def reopen(self) -> None:
        """Close the output stream (if it still exists) and open a fresh one on the current default device."""
        from .devices import PA_LOCK

        with PA_LOCK:                     # one reopen at a time; a second caller finds a fresh stream
            self._close()
            try:
                self._open()
                log.info("speaker stream reopened")
            except Exception:  # noqa: BLE001
                log.warning("couldn't reopen the speaker", exc_info=True)

    def _stream_dead(self) -> bool:
        from .devices import PA_LOCK

        with PA_LOCK:                     # never read a stream that a reset is closing
            st = self._stream
            if st is None:
                return self._want_stream  # we should have one: a failed reopen, try again
            try:
                return not bool(st.active)
            except Exception:  # noqa: BLE001
                return True

    def say(self, sentence: str, engine=None) -> None:
        """Queue a sentence. `engine` forces one voice (Settings → Test), with no fallback."""
        import time

        with self._lock:                  # pending and the speaking flag change together (no lost "speaking")
            self._pending += 1
            self._last_audio = time.monotonic()
            self._set_speaking_locked(True)
            gen = self._gen
        self._sentences.put((gen, sentence, engine))

    def _time(self, name: str, at: float | None = None) -> None:
        if self.timing is not None:
            try:
                self.timing(name, at)
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        """Barge-in: drop everything queued and stop talking now."""
        import time

        if self._speaking:
            self._stop_at = time.monotonic()      # the next audio callback reports when it actually went quiet
        self._lip = None                          # no stale words may drive the next reply's mouth
        with self._lock:
            self._gen += 1
            self._pending = 0
            while not self._sentences.empty():
                self._sentences.get_nowait()
            while not self._audio.empty():
                self._audio.get_nowait()
            self._buf = np.zeros(0, dtype=np.int16)
            self._set_speaking_locked(False)

    # ---- internals -----------------------------------------------------
    def _set_speaking(self, value: bool) -> None:
        with self._lock:
            self._set_speaking_locked(value)

    def _set_speaking_locked(self, value: bool) -> None:
        """Caller holds self._lock. The UI is told on a separate thread, in order, so the audio callback never
        waits on the UI and two quick changes can't arrive swapped."""
        if value != self._speaking:
            self._speaking = value
            if value:
                self._await_first = True
            self._notify.put(value)

    def _notify_loop(self) -> None:
        while True:
            value = self._notify.get()
            try:
                self.on_state(value)
                if not value:
                    self.on_level(0.0)
            except Exception:  # noqa: BLE001
                log.debug("speaking-state listener failed", exc_info=True)

    def wait_idle_notified(self, timeout: float = 1.0) -> None:
        """Tests: wait until every state change so far has been delivered."""
        import time

        end = time.monotonic() + timeout
        while not self._notify.empty() and time.monotonic() < end:
            time.sleep(0.005)
        time.sleep(0.01)

    def _run_engine(self, engine, sentence: str, gen: int) -> None:
        """Stream one sentence from an engine on a helper thread, so a hung engine can't freeze Monkey."""
        q: queue.Queue = queue.Queue()

        def work():
            it = engine.stream_pcm(sentence)
            try:
                for chunk in it:
                    if gen != self._gen:          # interrupted: stop reading so the engine frees its model now
                        break
                    q.put(chunk)
                q.put(StopIteration)
            except Exception as exc:  # noqa: BLE001
                q.put(exc)
            finally:
                close = getattr(it, "close", None)
                if close is not None:
                    try:
                        close()                   # Pocket's generator sets its stop flag in `finally`
                    except Exception:  # noqa: BLE001
                        pass

        threading.Thread(target=work, name=f"tts-{type(engine).__name__}", daemon=True).start()
        import time

        timeout, got = _deadline(sentence), False
        waited_since = time.monotonic()
        while True:
            if gen != self._gen:
                return                            # interrupted while waiting: don't hold up the next reply
            try:
                item = q.get(timeout=0.1)
            except queue.Empty:
                if time.monotonic() - waited_since > (timeout if not got else 15.0):
                    raise EngineTimeout(f"{type(engine).__name__} didn't produce audio in time") from None
                continue
            waited_since = time.monotonic()
            if item is StopIteration:
                if not got:
                    raise RuntimeError(f"{type(engine).__name__} returned no audio")
                return
            if isinstance(item, Exception):
                if got:          # failed mid-sentence: keep what played, don't repeat the start on another voice
                    log.warning("TTS engine %s failed mid-sentence: %s", type(engine).__name__, item)
                    return
                raise item
            if not got:
                self._time("first_audio_packet")
            got = True
            if gen != self._gen:
                return
            self._audio.put((gen, item))

    def _watchdog(self) -> None:
        import time

        while True:
            time.sleep(1.0)
            if self._want_stream and self._stream_dead():
                log.warning("speaker stream stopped (device change?); reopening")
                self.reopen()
                continue
            with self._lock:
                if self._speaking and not self._in_engine and self._sentences.empty() and self._audio.empty() \
                        and self._buf.size == 0 and time.monotonic() - self._last_audio > STALL_S:
                    log.warning("speaker stalled (pending=%s); resetting", self._pending)
                    self._pending = 0
                    self._set_speaking_locked(False)

    def _synth_loop(self) -> None:
        while True:
            item = self._sentences.get()
            if item is None:
                return
            gen, sentence, forced = item
            if gen != self._gen:
                continue                          # queued before an interrupt: never speak it
            engines = self.engines if forced is None else [forced]
            self._in_engine = True
            if self.text_lipsync:
                self._audio.put((gen, ("text", sentence)))       # tells the callback which words this audio carries
            try:
                self._speak_one(engines, sentence, gen, forced)
            finally:
                self._in_engine = False
                self._last_audio = __import__("time").monotonic()
            self._audio.put((gen, None))  # end-of-sentence marker (the callback ignores ones from an old reply)

    def _speak_one(self, engines, sentence: str, gen: int, forced) -> None:  # noqa: ARG002
        for engine in engines:
            try:
                if not getattr(engine, "enabled", lambda: True)() or not engine.available():
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

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ARG002
        out = np.zeros(frames, dtype=np.int16)
        filled = 0
        if self._stop_at is not None and self._audio.empty() and self._buf.size == 0:
            self._stop_at = None                  # this block is silent: what's in the device buffer is the last sound
            self._time("playback_stopped", __import__("time").monotonic() + self.output_latency)
        while filled < frames:
            if self._buf.size == 0:
                try:
                    nxt = self._audio.get_nowait()
                except queue.Empty:
                    break
                gen, chunk = nxt
                if gen != self._gen:
                    continue                      # from a reply that was interrupted: never play it or count it
                if isinstance(chunk, tuple):      # ("text", sentence): the next audio speaks these words
                    self._lip = TextLipSync(chunk[1])
                    continue
                if chunk is None:
                    with self._lock:
                        if gen == self._gen:
                            self._pending = max(0, self._pending - 1)
                    continue
                self._buf = chunk
            self._last_audio = __import__("time").monotonic()
            if self._await_first:
                self._await_first = False
                self._time("first_audio_played", self._last_audio + self.output_latency)
            take = min(frames - filled, self._buf.size)
            out[filled:filled + take] = self._buf[:take]
            self._buf = self._buf[take:]
            filled += take
        try:
            match, trim = self.loudness()
        except Exception:  # noqa: BLE001
            match, trim = True, 1.0
        outdata[:, 0] = self.leveler.process(out, enabled=match, trim=trim) if filled else out
        # lip sync reads the unboosted signal so the mouth moves the same at any volume
        rms = float(np.sqrt(np.mean(out.astype(np.float32) ** 2))) if filled else 0.0
        self.on_level(min(1.0, rms / 6000.0))
        if self.on_visemes is not None and (filled or self._prev_rms):
            spec = estimate_visemes(out, TTS_RATE, self._prev_rms)          # one 1024-pt FFT: microseconds
            lip = self._lip
            self.on_visemes(blend(lip.feed(rms), spec) if lip is not None and filled else spec)
        self._prev_rms = rms
        if filled == 0 and self._speaking:
            with self._lock:                      # re-check under the lock: say() may have just queued more
                if self._pending == 0 and self._audio.empty() and self._buf.size == 0:
                    self._set_speaking_locked(False)

"""Echo guard: don't answer Monkey's own voice.

Laptop speakers bleed into the microphone. In conversation mode (no wake word) a tail of his last sentence can be
picked up and transcribed as if the user said it. The guard remembers what he said recently and rejects a transcript
that is mostly made of it. Only text is kept, in memory, for a short window; nothing is logged.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from difflib import SequenceMatcher

_WORD = re.compile(r"[a-z0-9']+")
ECHO_WINDOW_S = 0.6          # an echo starts within this long after his voice stopped (the mic opens ~0.4 s after)


def _words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


class EchoGuard:
    def __init__(self, window_s: float = 20.0, keep: int = 12):
        self.window_s = window_s
        self._said: deque[tuple[float, list[str]]] = deque(maxlen=keep)
        self._lock = threading.Lock()

    def remember(self, sentence: str, now: float | None = None) -> None:
        w = _words(sentence)
        if w:
            with self._lock:
                self._said.append((time.monotonic() if now is None else now, w))

    def clear(self) -> None:
        with self._lock:
            self._said.clear()

    def is_echo(self, transcript: str, now: float | None = None, started_after_voice_s: float | None = None) -> bool:
        """True when the transcript is (nearly) a piece of what he just said AND it began right as his voice ended.

        People answer by repeating his words all the time ("the short version", "add it to my calendar"), so the
        words alone never decide it. An echo is the tail of his own sound reaching the mic: it starts within about a
        second of his playback ending. `started_after_voice_s` is how long after his voice stopped the utterance
        began (None = unknown, treated as not an echo). It also needs 4+ words, 90% of them in order from one
        recent sentence (or two joined)."""
        if started_after_voice_s is None or started_after_voice_s > ECHO_WINDOW_S:
            return False
        heard = _words(transcript)
        if len(heard) < 4:
            return False                     # short answers ("the short version", "yes") are the user's
        now = time.monotonic() if now is None else now
        with self._lock:
            recent = [w for t, w in self._said if now - t <= self.window_s]
        if not recent:
            return False
        candidates = recent + [a + b for a, b in zip(recent, recent[1:])]
        for said in candidates:
            m = SequenceMatcher(a=heard, b=said, autojunk=False)
            matched = sum(b.size for b in m.get_matching_blocks())
            if matched / len(heard) >= 0.9:
                return True
        return False

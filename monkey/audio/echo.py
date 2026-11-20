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

    def is_echo(self, transcript: str, now: float | None = None) -> bool:
        """True when the transcript is (nearly) a piece of what he just said.

        A real reply that quotes him ("what do you mean 'by Friday'?") adds its own words, so it stays below the bar:
        at least 80% of the heard words must appear, in order, in one recent sentence (or two joined)."""
        heard = _words(transcript)
        if len(heard) < 2:
            return False                     # "yes", "no", "stop": too short to tell, and usually the user's
        now = time.monotonic() if now is None else now
        with self._lock:
            recent = [w for t, w in self._said if now - t <= self.window_s]
        if not recent:
            return False
        candidates = recent + [a + b for a, b in zip(recent, recent[1:])]
        for said in candidates:
            m = SequenceMatcher(a=heard, b=said, autojunk=False)
            matched = sum(b.size for b in m.get_matching_blocks())
            if matched / len(heard) >= 0.8:
                return True
        return False

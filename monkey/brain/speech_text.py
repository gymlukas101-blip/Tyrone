"""Turn streamed model text into speakable sentences."""
from __future__ import annotations

import re

_MD = [
    (re.compile(r"```.*?```", re.S), " "),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), " "),
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"https?://\S+"), " "),
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.M), ""),
    (re.compile(r"^\s*[-*•]\s+", re.M), ""),
    (re.compile(r"^\s*\d+\.\s+", re.M), ""),
    (re.compile(r"(\*\*|__|\*|_|~~)"), ""),
    (re.compile(r"\|"), " "),
    (re.compile(r"[ \t]{2,}"), " "),
]


def speakable(text: str) -> str:
    for pat, rep in _MD:
        text = pat.sub(rep, text)
    return text.strip()


_BOUNDARY = re.compile(r"(?<=[.!?])[\"')\]]?\s+|\n{1,}")
_CLAUSE = re.compile(r"(?<=[,;:—])\s+")


class SentenceChunker:
    """Feed streaming text deltas; get back complete sentences to send to TTS."""

    def __init__(self, min_chars: int = 24, early_clause: bool = True):
        self.buf = ""
        self.min_chars = min_chars
        self._in_code = False
        # The first piece of a reply may end at a clause ("Sure, here's what's due") instead of waiting for the whole
        # sentence: the voice starts sooner and the break falls where a speaker pauses anyway. Only the first piece:
        # later ones keep whole sentences for the most natural prosody.
        self.early_clause = early_clause
        self._emitted = False

    def feed(self, delta: str) -> list[str]:
        self.buf += delta
        out: list[str] = []
        if self.early_clause and not self._emitted and not self._in_code and "```" not in self.buf:
            for m in _CLAUSE.finditer(self.buf):
                if _BOUNDARY.search(self.buf[:m.start()]):
                    break                                 # a sentence ended first: the normal path handles it
                head = self.buf[:m.end()]
                if len(head.split()) >= 4 and len(head.strip()) >= 20:
                    s = speakable(head)
                    if s:
                        self.buf = self.buf[m.end():]
                        self._emitted = True
                        out.append(s)
                    break
        while True:
            m = _BOUNDARY.search(self.buf)
            if not m:
                break
            end = m.end()
            piece = self.buf[:end]
            if len(piece.strip()) < self.min_chars and "\n" not in m.group(0):
                # Too short ("Yo." / "Bet.") - wait for more unless it's a paragraph break.
                nxt = _BOUNDARY.search(self.buf, end)
                if not nxt:
                    break
                end = nxt.end()
                piece = self.buf[:end]
            self.buf = self.buf[end:]
            if piece.count("```") % 2 == 1:
                self._in_code = not self._in_code
            if not self._in_code:
                s = speakable(piece)
                if s:
                    out.append(s)
                    self._emitted = True
        return out

    def flush(self) -> list[str]:
        s = "" if self._in_code else speakable(self.buf)
        self.buf = ""
        self._in_code = False
        return [s] if s else []

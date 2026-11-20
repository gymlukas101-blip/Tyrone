"""Text-assisted lip sync: the sentence says WHICH mouth shapes come, the audio says WHEN and how wide.

The spectrum heuristic (visemes.py) can hear loudness and hiss but can't tell "oh" from "ee" reliably, and only
guesses closures. The text of each sentence is known before it's spoken, so:

1. The text becomes a sequence of syllables: (closing consonant before it, vowel shape). Spelling-based and
   approximate (English isn't phonetic), but vowels and lip closures (p/b/m, f/v, oo/w) are what the eye reads.
2. In the audio callback, every new syllable burst (loudness rising after a dip) advances one step along that
   sequence; a dip just before a syllable that starts with p/b/m closes the lips (viseme_PP).
3. The output blends the text's shape with the spectrum's (audio still drives openness and hiss), so a wrong
   guess in either is softened.

Cheap enough for the audio callback (a few comparisons per 23 ms block; the text is parsed before playback).
"""
from __future__ import annotations

import re

_VOWELS = [  # (spelling, viseme), longest first
    ("ough", "viseme_O"), ("eigh", "viseme_E"), ("ee", "viseme_I"), ("ea", "viseme_I"), ("ie", "viseme_I"),
    ("ey", "viseme_E"), ("ay", "viseme_E"), ("ai", "viseme_E"), ("oo", "viseme_U"), ("ou", "viseme_aa"),
    ("ow", "viseme_O"), ("oa", "viseme_O"), ("oi", "viseme_O"), ("oy", "viseme_O"), ("au", "viseme_O"),
    ("aw", "viseme_O"), ("ue", "viseme_U"), ("ew", "viseme_U"), ("a", "viseme_aa"), ("e", "viseme_E"),
    ("i", "viseme_I"), ("o", "viseme_O"), ("u", "viseme_U"), ("y", "viseme_I"),
]
_CONS = [  # (spelling, viseme of the consonant), longest first
    ("th", "viseme_TH"), ("sh", "viseme_CH"), ("ch", "viseme_CH"), ("ph", "viseme_FF"), ("wh", "viseme_U"),
    ("p", "viseme_PP"), ("b", "viseme_PP"), ("m", "viseme_PP"), ("f", "viseme_FF"), ("v", "viseme_FF"),
    ("s", "viseme_SS"), ("z", "viseme_SS"), ("c", "viseme_kk"), ("k", "viseme_kk"), ("g", "viseme_kk"),
    ("q", "viseme_kk"), ("x", "viseme_kk"), ("j", "viseme_CH"), ("t", "viseme_DD"), ("d", "viseme_DD"),
    ("l", "viseme_DD"), ("n", "viseme_nn"), ("r", "viseme_RR"), ("w", "viseme_U"), ("h", "viseme_sil"),
]
_NUM = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven",
        "8": "eight", "9": "nine"}


def syllables(text: str) -> list[tuple[str | None, str]]:
    """'big map' -> [('viseme_PP', 'viseme_I'), ('viseme_PP', 'viseme_aa')]: (onset consonant, vowel) per syllable."""
    t = re.sub(r"\d", lambda m: f" {_NUM[m.group(0)]} ", (text or "").lower())
    out: list[tuple[str | None, str]] = []
    for word in re.findall(r"[a-z']+", t):
        w = word.replace("'", "")
        if len(w) > 3 and w.endswith("e") and w[-2] not in "aeiouy":
            w = w[:-1]                                         # silent final e ("made", "time")
        i, onset = 0, None
        while i < len(w):
            for sp, vis in _VOWELS:
                if w.startswith(sp, i):
                    out.append((onset, vis))
                    onset = None
                    i += len(sp)
                    break
            else:
                for sp, vis in _CONS:
                    if w.startswith(sp, i):
                        onset = vis if onset is None or vis == "viseme_PP" else onset
                        i += len(sp)
                        break
                else:
                    i += 1
    return out


class TextLipSync:
    """One per sentence. feed(rms) for each audio block; returns {viseme: weight} from the text, or {} when done."""

    RISE = 1.35          # loudness ratio over the recent dip that counts as a new syllable
    QUIET = 350.0        # int16 RMS below this is a gap

    def __init__(self, text: str):
        self.seq = syllables(text)
        self.i = -1
        self.peak = 0.0
        self.dip = 0.0
        self.in_dip = False

    @property
    def done(self) -> bool:
        return self.i >= len(self.seq)

    def _advance(self, rms: float) -> None:
        self.i += 1
        self.peak = self.dip = rms
        self.in_dip = False

    def feed(self, rms: float) -> dict[str, float]:
        if not self.seq or self.done:
            return {}
        if self.i < 0:
            if rms <= self.QUIET:
                return {"viseme_sil": 1.0}
            self._advance(rms)                                   # the first syllable starts
        elif rms < self.QUIET or rms < self.peak * 0.6:
            self.in_dip = True                                   # between syllables
            self.dip = min(self.dip, rms)
        elif self.in_dip and rms > max(self.dip * self.RISE, self.QUIET):
            self._advance(rms)                                   # a new burst = the next syllable
            if self.done:
                return {}
        else:
            self.peak = max(self.peak, rms)
        nxt = self.seq[self.i + 1] if self.i + 1 < len(self.seq) else None
        if self.in_dip and nxt is not None and nxt[0] == "viseme_PP":
            return {"viseme_PP": 1.0}                            # lips close before a p/b/m syllable
        if rms < self.QUIET:
            return {"viseme_sil": 1.0}
        onset, vowel = self.seq[self.i]
        if self.in_dip and onset and onset != "viseme_sil":
            return {onset: 0.7, vowel: 0.3}
        return {vowel: 1.0}


def blend(text_w: dict[str, float], spectrum_w: dict[str, float], k: float = 0.65) -> dict[str, float]:
    """Text decides the shape (weight k); the spectrum keeps audio texture (hiss, openness) in the rest."""
    if not text_w:
        return spectrum_w
    if "viseme_PP" in text_w:
        return {"viseme_PP": text_w["viseme_PP"]}                # a closure is a closure
    out: dict[str, float] = {}
    for key, v in text_w.items():
        out[key] = out.get(key, 0.0) + k * v
    for key, v in spectrum_w.items():
        out[key] = out.get(key, 0.0) + (1 - k) * v
    top = sorted(out.items(), key=lambda kv: kv[1], reverse=True)[:2]
    return dict(top)

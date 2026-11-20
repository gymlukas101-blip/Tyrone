"""Is the user done talking? A cheap, deterministic read of the words so far (no model call).

Used by early commit: when you pause, the listener transcribes what it has right away (in the background). If the
words read as a finished thought, the turn ends after a short pause (~0.5 s) instead of the full silence wait
(1.4 s); if they trail off ("remind me to call…", "and um"), it waits longer than usual instead. The audio-only
silence rule still applies when there's no transcript in time, so this can only make the common case faster.

Signals (from turn-detection practice: trailing conjunctions and fillers mean "more is coming"; terminal punctuation
from the recognizer and short complete commands mean "done"):
- ends with a filler or a word that needs a continuation (and, or, but, so, because, the, a, to, of, my, um, uh…)
- ends with a comma, a dash or an ellipsis
- terminal punctuation (. ? !) from Whisper
- a complete short command or question ("stop", "what's the weather", "open canvas")
"""
from __future__ import annotations

import re

_CONTINUES = {
    "and", "or", "but", "so", "because", "cause", "since", "if", "when", "while", "until", "unless", "although",
    "the", "a", "an", "to", "of", "for", "with", "from", "in", "on", "at", "by", "about", "into", "like", "than",
    "my", "your", "our", "their", "his", "her", "its", "this", "that", "these", "those", "some", "any", "every",
    "is", "are", "was", "were", "be", "can", "could", "would", "should", "will", "do", "does", "did", "have", "has",
    "um", "uh", "er", "erm", "hmm", "mm", "also", "then", "maybe", "which", "who", "what", "where", "how", "why",
    "i", "i'm", "we", "you", "let", "let's", "please", "just", "actually", "basically", "kind", "sort",
    "wait", "hold", "hang",                       # "no wait…", "hold on…": a correction is coming
}
# Verbs that want an object: "remind me to call…" / "can you text…" isn't finished even if it looks like it.
_WANTS_OBJECT = {
    "call", "text", "email", "message", "send", "tell", "ask", "remind", "set", "open", "play", "find", "check",
    "get", "make", "add", "put", "take", "give", "show", "buy", "write", "read", "draft", "schedule", "book",
    "move", "cancel", "change", "start", "stop", "turn", "look", "search", "pick", "grab", "bring", "need", "want",
}
_DONE_WORDS = {"stop", "thanks", "thank", "yes", "yeah", "yep", "no", "nope", "okay", "ok", "cool", "bye", "goodbye",
               "nevermind", "never mind", "sure", "perfect", "great", "done"}
_FILLER_ONLY = re.compile(r"^(um+|uh+|er+|erm|hmm+|mm+|so|and|well|like|okay|ok)[\s.,!?]*$", re.I)
_WORD = re.compile(r"[a-z']+")


def completeness(text: str) -> str:
    """'complete' | 'incomplete' | 'unknown' for the words heard so far."""
    t = " ".join((text or "").split())
    if not t:
        return "unknown"
    if _FILLER_ONLY.match(t):
        return "incomplete"
    if re.search(r"(,|—|-|\.\.\.|…)\s*$", t):
        return "incomplete"
    words = _WORD.findall(t.lower())
    if not words:
        return "unknown"
    if words[-1] in _CONTINUES:
        return "incomplete"
    if len(words) >= 2 and words[-1] in _WANTS_OBJECT and words[-2] in ("to", "you", "me", "please", "and", "can"):
        return "incomplete"                       # "remind me to call" / "can you check" / "please send"
    if len(words) == 1 and words[0] in _DONE_WORDS:
        return "complete"
    if re.search(r"[.?!]\s*$", t):
        return "complete"
    # No punctuation (some recognizers omit it): a few words not ending on a connector read as finished.
    return "complete" if len(words) >= 2 else "unknown"


def commit_after_ms(text: str) -> int | None:
    """How much silence ends the turn early for these words; None = don't end early (use the normal rule).

    Questions and clear short answers/commands end fast; other finished-looking statements wait a bit longer,
    because a pause after a statement is more often a breath than after a question."""
    t = " ".join((text or "").split())
    v = completeness(t)
    if v != "complete":
        return None
    words = _WORD.findall(t.lower())
    if t.endswith("?") or (len(words) <= 2 and words and words[0] in _DONE_WORDS):
        return 480
    return 880

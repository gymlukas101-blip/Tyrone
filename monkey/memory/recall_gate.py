"""Recall gate: decide whether a message gets automatic memory, and which hits are worth injecting.

Automatic recall used to run on every message and inject the top hits whatever they were (old raw messages
included). That costs tokens and drags in unrelated memories. The gate:

1. Skips tasks that never need your personal memory ("set a timer", "what's the weather", "make a picture",
   general knowledge), unless the message points at you ("my", "last time", "remember"...).
2. Injects only facts and episode summaries, never raw old messages (search_memory can still find those on request).
3. Keeps a hit only if it shares enough of the message's distinctive words (a relevance floor).
4. Drops a hit that's already in the recent conversation (it's in context; repeating it just costs tokens).
"""
from __future__ import annotations

import re

from .history import Hit, _stems as _all_stems


def _stems(text: str) -> list[str]:
    """Distinctive words; drops the "s" left over from "who's" / "it's"."""
    return [w for w in _all_stems(text) if len(w) > 1]

SKIP_TASKS = {"command", "weather", "image_request", "check_off", "briefing", "style_learning", "router"}
# Routed by wording, so a personal question can land here ("when does comet club meet?" looks like a web lookup):
# search anyway (it's a local SQLite query), but inject only strong matches.
STRICT_TASKS = {"quick_fact", "web_lookup"}
# Cues that a message is about your own past, which beat the task skip list ("open my usual playlist", "set it
# like last time"). Plain "my" isn't one for commands ("set my alarm"), but it is for questions ("what's my
# advisor's name?" can route as a quick fact).
PERSONAL = re.compile(r"\b(remember|last time|again|before|earlier|usual(?:ly)?|we talked|you said|i said|i told|"
                      r"like always|as always)\b", re.I)
MY = re.compile(r"\b(my|mine|our)\b", re.I)
MIN_TERMS = 1


def should_recall(task: str, text: str) -> tuple[bool, str]:
    """(recall?, why). Cheap and deterministic: no model call."""
    words = _stems(text)
    if len(words) < MIN_TERMS:
        return False, "nothing to look up"
    personal = bool(PERSONAL.search(text or "")) or (task == "quick_fact" and bool(MY.search(text or "")))
    if task in SKIP_TASKS and not personal:
        return False, f"{task} doesn't need personal memory"
    if task == "chat" and len(words) < 3 and not personal:
        return False, "small talk"
    return True, ""


def relevant(hit: Hit, query: str, strict: bool = False) -> bool:
    """At least two of the message's distinctive words, or a third of them, appear in the hit.
    Strict (quick facts, web lookups): two words and half of them."""
    q = set(_stems(query))
    if not q:
        return False
    h = set(_stems(hit.text) + _stems(hit.source.replace(".md", "")))
    overlap = len(q & h)
    if strict:
        return overlap >= 2 and overlap / len(q) >= 0.5 if len(q) > 1 else overlap == 1
    return overlap >= 2 or (overlap >= 1 and overlap / len(q) >= 0.34)


def already_in_context(hit: Hit, recent_text: str) -> bool:
    words = _stems(hit.text)
    if not words or not recent_text:
        return False
    have = set(_stems(recent_text))
    return sum(1 for w in words if w in have) / len(words) >= 0.8


def select(hits: list[Hit], query: str, recent_text: str = "", limit: int = 5, task: str = "general") -> list[Hit]:
    out = []
    strict = task in STRICT_TASKS
    for h in hits:
        if h.kind == "message":
            continue
        if not relevant(h, query, strict) or already_in_context(h, recent_text):
            continue
        out.append(h)
        if len(out) >= limit:
            break
    return out

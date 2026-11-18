"""Conversation-mode rules: when you've said goodbye, and which overheard bits aren't meant for Monkey.

Pure text logic (no model call), so ending a conversation is instant and free.
"""
from __future__ import annotations

import re

WAKE = re.compile(r"^\s*(hey|hi|okay|ok|yo)[\s,]+(monkey|monke|monkee|munkey)\b[\s,.!?]*", re.I)
_WORDS = re.compile(r"[a-z']+")
FILLERS = {"uh", "um", "umm", "uhh", "hmm", "hm", "mm", "mhm", "ah", "oh", "er", "erm", "huh", "the", "a",
           "and", "so", "like", "you", "i"}
# Short answers to something Monkey asked ("Want me to send it?" -> "yes").
SHORT_OK = {"yes", "yeah", "yep", "yup", "no", "nope", "nah", "sure", "okay", "ok", "cancel", "stop", "send",
            "continue", "more", "again", "repeat", "both", "neither", "first", "second", "third", "next",
            "please", "correct", "right", "wrong", "maybe", "later", "now", "tomorrow", "today", "tonight"}
GOODBYE = re.compile(
    r"^(?:(?:ok(?:ay)?|alright|cool|great|awesome|perfect|got it|nice|no|nah)[\s,!.]*)*"
    r"(?:thanks?(?: you)?|thank you(?: so much)?|thx|ty|that'?s (?:all|it|everything)|that is all|"
    r"(?:good)?bye|see (?:you|ya)|later|never ?mind|stop listening|go to sleep|we'?re done|i'?m (?:good|done)|"
    r"nothing else|that'?ll be all)"
    r"(?:[\s,!.]*(?:monkey|man|bro|dude|buddy|for now|again|so much|a lot|that'?s all|bye))*[\s,!.]*$", re.I)
SIGN_OFFS = ["Anytime!", "You got it.", "Cool, I'm here if you need me.", "Later!", "Anytime, my guy."]


def words(text: str) -> list[str]:
    return _WORDS.findall(text.lower())


def strip_wake(text: str) -> str:
    """'Hey Monkey, what's due?' -> "what's due?" (said while he was already listening)."""
    return WAKE.sub("", text, count=1).strip()


def is_goodbye(text: str) -> bool:
    t = text.strip()
    return bool(t) and len(words(t)) <= 7 and bool(GOODBYE.match(t))


def worth_answering(text: str) -> bool:
    """In conversation mode (no wake word): is this plausibly said to Monkey, not noise or a filler?"""
    w = [x for x in words(text) if x not in FILLERS]
    if not w:
        return False
    if len(w) >= 2:
        return True
    return w[0] in SHORT_OK or is_goodbye(text)

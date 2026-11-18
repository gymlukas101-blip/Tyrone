"""Pick the model + effort for each request.

Order of precedence:
  1. A forced model in Settings (for debugging).
  2. Rules: what you *say* about importance ("this is important", "take your time",
     "quick question") and obvious task types (email drafting, research, commands).
  3. A cheap classifier (Claude Haiku 5.5, low effort) that rates difficulty 1-5.
  4. Budget guard: near the monthly cap, Opus is downgraded unless you said it's important.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import BaseModel, Field

from .costs import HAIKU, OPUS, SONNET

Effort = Literal["low", "medium", "high", "xhigh", "max"]
Importance = Literal["low", "normal", "high"]

# Ladder from cheapest to strongest. Index = "level".
LADDER: list[tuple[str, Effort]] = [
    (HAIKU, "low"),      # 0 small talk, commands
    (SONNET, "low"),     # 1 simple Q&A
    (SONNET, "medium"),  # 2 normal Q&A, summaries
    (OPUS, "medium"),    # 3 research, drafting, ranking
    (OPUS, "high"),      # 4 hard / important
    (OPUS, "xhigh"),     # 5 very hard and important
]


@dataclass(frozen=True)
class Route:
    model: str
    effort: Effort
    importance: Importance
    level: int
    reason: str

    @property
    def label(self) -> str:
        name = {HAIKU: "Haiku 5.5", SONNET: "Sonnet 5.5", OPUS: "Opus 5.5"}.get(self.model, self.model)
        return f"{name} · {self.effort}"


def _route(level: int, importance: Importance, reason: str) -> Route:
    level = max(0, min(level, len(LADDER) - 1))
    model, effort = LADDER[level]
    return Route(model=model, effort=effort, importance=importance, level=level, reason=reason)


# ---------------------------------------------------------------- rules
_HIGH = re.compile(
    r"\b(this is important|it'?s important|important|take your time|think (?:hard|carefully|it through)|"
    r"carefully|critical|high priority|top priority|really need this|make sure|double[- ]check|"
    r"don'?t mess (?:this|it) up|be thorough|thoroughly|deep dive)\b",
    re.I,
)
_LOW = re.compile(r"\b(quick(?:ly)?|real quick|fast|briefly|short answer|tl;?dr|no big deal|whatever)\b", re.I)

_EMAIL_DRAFT = re.compile(
    r"\b(draft|write|compose|reply|respond|answer|send)\b.{0,40}\b(e-?mail|message|note|reply|professor|prof|ta|advisor)\b"
    r"|\b(e-?mail)\b.{0,30}\b(back|to)\b",
    re.I,
)
_RESEARCH = re.compile(
    r"\b(research|look into|investigate|compare|pros and cons|deep dive|find out (?:everything|all)|"
    r"write (?:me )?(?:a|an) (?:essay|report|summary)|study guide|explain .{0,40} in detail)\b",
    re.I,
)
_RANK = re.compile(
    r"\b(my day|my week|what'?s (?:on|important)|priorit\w*|rank|briefing|what should i (?:do|focus)|"
    r"anything urgent|important emails?|due (?:this|next) week)\b",
    re.I,
)
_COMMAND = re.compile(
    r"^\s*(open|launch|go to|pull up|show me|play|pause|stop|set (?:a )?timer|remind me|"
    r"what time|what'?s the time|what'?s the date|volume|mute|remember that|forget)\b",
    re.I,
)
_NEEDS_WEB = re.compile(
    r"\b(search|look up|google|news|latest|today'?s|current(?:ly)?|right now|score|who won|price|"
    r"weather|forecast|stock|when does|is .{0,30} open|hours)\b",
    re.I,
)
_SMALLTALK = re.compile(
    r"^\s*(yo|hey|hi|hello|what'?s up|sup|how are you|how'?s it going|thanks|thank you|good (?:morning|night)|"
    r"lol|haha|bet|cool|nice|ok(?:ay)?)\b[\s\w,!?.']{0,40}$",
    re.I,
)


def detect_importance(text: str) -> Importance:
    if _HIGH.search(text):
        return "high"
    if _LOW.search(text):
        return "low"
    return "normal"


def rule_level(text: str) -> tuple[int | None, str]:
    """Return (level, reason) from rules, or (None, "") if the classifier should decide."""
    if _EMAIL_DRAFT.search(text):
        return 3, "email drafting"
    if _RESEARCH.search(text):
        return 3, "research"
    if _RANK.search(text):
        return 3, "ranking / briefing"
    if _COMMAND.search(text) and len(text) < 120:
        # Commands that need the web still want a web-capable model.
        if _NEEDS_WEB.search(text):
            return 1, "command needing web"
        return 0, "simple command"
    if _SMALLTALK.search(text):
        return 0, "small talk"
    if _NEEDS_WEB.search(text) and len(text) < 160:
        return 1, "quick web lookup"
    return None, ""


# ---------------------------------------------------------------- classifier
class Difficulty(BaseModel):
    difficulty: int = Field(description="1 trivial, 2 easy, 3 moderate, 4 hard, 5 very hard")
    needs_web: bool
    reason: str = Field(description="under 12 words")


CLASSIFIER_PROMPT = (
    "Rate how hard it is for an AI assistant to answer this request from a college student well. "
    "1 = chit-chat or a one-line fact, 2 = easy question, 3 = multi-part question or summary, "
    "4 = careful reasoning, writing, planning or multi-source research, 5 = very hard analysis. "
    "needs_web = true if the answer depends on current or online information."
)

# difficulty 1..5 -> ladder level
_DIFF_TO_LEVEL = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}


def classify_with_haiku(client, text: str) -> tuple[int, bool, str, object]:
    """Returns (difficulty, needs_web, reason, usage)."""
    resp = client.messages.parse(
        model=HAIKU,
        max_tokens=1024,
        output_config={"effort": "low"},
        system=CLASSIFIER_PROMPT,
        messages=[{"role": "user", "content": f"<request>{text[:2000]}</request>"}],
        output_format=Difficulty,
    )
    d: Difficulty = resp.parsed_output
    return max(1, min(5, int(d.difficulty))), bool(d.needs_web), d.reason, resp.usage


# ---------------------------------------------------------------- router
class Router:
    def __init__(
        self,
        classify: Callable[[str], tuple[int, bool, str]] | None = None,
        budget_usd: Callable[[], float] | None = None,
        spent_usd: Callable[[], float] | None = None,
        forced_model: Callable[[], str] | None = None,
    ):
        self._classify = classify
        self._budget = budget_usd or (lambda: float("inf"))
        self._spent = spent_usd or (lambda: 0.0)
        self._forced = forced_model or (lambda: "")

    def route(self, text: str, explicit_importance: Importance | None = None) -> Route:
        importance: Importance = explicit_importance or detect_importance(text)

        forced = self._forced()
        if forced:
            effort: Effort = "high" if importance == "high" else "medium"
            if forced == HAIKU:
                effort = "low"
            return Route(forced, effort, importance, -1, "forced in settings")

        level, reason = rule_level(text)
        if level is None:
            if self._classify is not None:
                try:
                    diff, needs_web, why = self._classify(text)
                    level = _DIFF_TO_LEVEL[diff]
                    if needs_web:
                        level = max(level, 1)  # Haiku gets no web tools
                    reason = f"classifier: {diff}/5 ({why})"
                except Exception as exc:  # classifier is best-effort
                    level, reason = 2, f"classifier failed ({type(exc).__name__}); default"
            else:
                level, reason = 2, "default"

        # Importance adjustments.
        if importance == "high":
            level = max(level + 1, 4 if level >= 3 else 3)
            reason += " + you said it's important"
        elif importance == "low":
            if level >= 3 and reason in ("email drafting",):
                level = 3  # drafting in your voice still needs Opus
            else:
                level = min(level, 1)
            reason += " + you said quick"

        # Budget guard.
        budget, spent = self._budget(), self._spent()
        if budget and spent >= budget:
            if importance != "high":
                level = min(level, 0)
                reason += " | monthly budget reached"
        elif budget and spent >= 0.9 * budget and importance != "high" and level >= 3:
            level = 2
            reason += " | near monthly budget"

        return _route(level, importance, reason)

    def escalate(self, route: Route) -> Route:
        """One step up the ladder - used when a cheap model asks for help."""
        nxt = max(route.level + 1, 1)
        return _route(nxt, route.importance, route.reason + " → escalated")

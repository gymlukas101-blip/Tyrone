"""Pick the task, then the model + effort for it from the stored model policy (policy.py).

Order of precedence:
  1. A forced model in Settings (for debugging).
  2. Rules: obvious task types from what you say ("draft an email…", "how did I sleep", "open canvas").
  3. A cheap classifier (Claude Haiku 5.5, low effort) that names the task and rates difficulty 1-5.
  4. Importance: ⚡ Quick → the task's `min`, Auto → `default`, ★ Important → `max`.
  5. Budget guard: near or over the monthly cap, step down inside the task's own range.
  6. Sticky model: a quick follow-up stays on the model that just answered, if that model is in range
     (switching models re-pays the whole conversation, because prompt caches are per model).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Callable, Literal

from pydantic import BaseModel, Field

from .costs import HAIKU, OPUS, SONNET
from .policy import Choice, ModelPolicy, rank

Effort = Literal["low", "medium", "high", "xhigh", "max"]
Importance = Literal["low", "normal", "high"]

MODEL_NAMES = {HAIKU: "Haiku 5.5", SONNET: "Sonnet 5.5", OPUS: "Opus 5.5"}


@dataclass(frozen=True)
class Route:
    model: str
    effort: str
    importance: Importance
    task: str
    reason: str
    tier: str = "default"

    @property
    def label(self) -> str:
        return f"{MODEL_NAMES.get(self.model, self.model)} · {self.effort}"

    @property
    def choice(self) -> Choice:
        return Choice(self.model, self.effort)


# ---------------------------------------------------------------- rules
# Only phrases aimed at Monkey count. "Any important emails?", "make sure the alarm is on" or an email that says
# "critical" in its text are content, not a request to think harder (they used to send the turn to the top tier).
_HIGH = re.compile(
    r"\b(this is (?:really |very |super )?important|it'?s (?:really |very |super )?important|"
    r"(?:really|very|super) important (?:that you|to me)|important,? so|take your time|"
    r"think (?:hard|carefully|it through)|be careful|high priority|top priority|really need this|"
    r"double[- ]check (?:this|it|your)|don'?t mess (?:this|it) up|be thorough|thoroughly|deep dive)\b",
    re.I,
)
_LOW = re.compile(r"\b(quick(?:ly)?|real quick|fast|briefly|short answer|tl;?dr|no big deal|whatever)\b", re.I)

RULES: list[tuple[str, re.Pattern]] = [
    # The user's own to-do list (not Canvas's "to-do", not computer tasks). First, so "add 'email my TA' to my
    # to-do list" is a to-do and not an email draft.
    ("todo", re.compile(
        r"(?<!canvas )\bto-?dos?\b|\bto do list\b|\bremind me (?:to|about)\b|\b(?:on|to|off|from) my list\b|"
        r"\bwhat(?: else)? do i (?:need|have|gotta) to do\b", re.I)),
    # The task helper: a job done *for* the owner on a website or in an app (propose_computer_task), or the mailing
    # lists review (find_mailing_lists / propose_unsubscribe). Before draft_email, so "send an unsubscribe email"
    # isn't a draft.
    ("task_helper", re.compile(
        r"\b(?:unsubscribe|opt (?:me )?out of|mailing lists?|"
        r"(?:clean (?:up|out)|organi[sz]e|tidy(?: up)?|declutter|sort out)\s+(?:up\s+)?(?:my |the |all (?:of )?my )?"
        r"(?:e-?mails?|inbox(?:es)?|gmail|outlook)|archive (?:all )?(?:the |my |old |those |these )?(?:old )?"
        r"(?:newsletters|promos?|promotions|e-?mails|notifications|junk mail)|inbox (?:cleanup|zero)|"
        r"stop (?:getting|receiving) (?:these |those |the |all |so many )?(?:e-?mails|newsletters|promos?|spam)|"
        r"(?:cancel|end) my .{0,40}(?:subscription|free trial|trial|membership)|"
        r"fill (?:in|out) (?:this|the|that|a|my) .{0,25}form|"
        r"(?:on|at|in) (?:the |their )?(?:website|site|web ?page)\b.{0,60}\b(?:for me|and (?:change|cancel|turn|fill|"
        r"find|download|update|book|order))|"
        r"(?:go|log) (?:on|onto|into|to) .{0,40}\band (?:change|cancel|turn|fill|download|update|book|order)|"
        r"(?:do|handle) (?:this|that|it) (?:on|in) (?:the )?(?:website|site|browser)|"
        r"find .{0,60}\b(?:cheapest|lowest price|best price)\b.{0,60}\b(?:just show me|don'?t (?:book|buy|order))|"
        r"task helper|computer task)\b", re.I)),
    ("draft_email", re.compile(
        r"\b(draft|write|compose|reply|respond|answer|send)\b.{0,40}\b(e-?mail|message|note|reply|professor|prof|ta|advisor)\b"
        r"|\b(e-?mail)\b.{0,30}\b(back|to)\b", re.I)),
    ("research", re.compile(
        r"\b(research|look into|investigate|compare|pros and cons|deep dive|find out (?:everything|all)|"
        r"write (?:me )?(?:a|an) (?:essay|report)|study guide)\b", re.I)),
    ("briefing", re.compile(r"\b(my day|my week|briefing|what'?s on my plate|morning (?:update|rundown)|catch me up)\b", re.I)),
    ("triage", re.compile(
        r"\b(important emails?|anything urgent|urgent emails?|priorit\w*|rank (?:my|the)|which emails|"
        r"what (?:emails|messages) (?:matter|should i))\b", re.I)),
    ("read_email", re.compile(
        r"\b(read|summari[sz]e|open|what does|what did)\b.{0,30}\b(e-?mails?|message|inbox)\b"
        r"|\b(any|new|latest|check (?:my)?) (?:new )?e-?mails?\b|\binbox\b", re.I)),
    ("memory_note", re.compile(r"^\s*(remember (?:that|this|my)|don'?t forget (?:that|my)|forget (?:that|about)|note that)\b", re.I)),
    ("image_request", re.compile(r"\b(draw|paint|sketch|generate|create|make)\b.{0,25}\b(picture|image|drawing|art|logo|wallpaper)\b", re.I)),
    ("weather", re.compile(r"\b(weather|forecast|temperature outside|is it (?:going to )?(?:rain|snow)|how cold|how hot|"
                           r"need an? (?:jacket|coat|umbrella))\b", re.I)),
    ("check_off", re.compile(r"\b(check (?:it )?off|mark .{0,30}\b(?:done|complete)|i (?:just )?(?:finished|submitted|turned in))\b", re.I)),
    ("assignments", re.compile(
        r"\b(assignments?|homework|hw|what'?s due|due (?:today|tomorrow|this week|next week)|missing (?:work|assignments?)|"
        r"what should i (?:work on|do next|focus on)|canvas (?:due|to-?do))\b", re.I)),
    ("health", re.compile(
        r"\b(how (?:did|'?d) i sleep|sleep score|my sleep|heart ?rate|resting hr|hrv|body battery|stress level|"
        r"steps today|garmin|screen ?time|time on my phone|(?:was|been) (?:i )?on my phone|phone (?:usage|time))\b",
        re.I)),
    ("calendar", re.compile(
        r"\b(calendar|my schedule|on my schedule|what'?s (?:on )?today|next class|when is my|what time is my|"
        r"am i free|meetings? today)\b", re.I)),
    ("hard_problem", re.compile(
        r"\b(prove|derive|derivation|make me an? .{0,25}plan|plan out|game plan|optimi[sz]e my|"
        r"step[- ]by[- ]step solution)\b", re.I)),
]
_COMMAND = re.compile(
    r"^\s*(open|launch|go to|pull up|show me|play|pause|stop|set (?:a )?timer|remind me|"
    r"what time|what'?s the time|what'?s the date|volume|mute|dance|flex|wave)\b",
    re.I,
)
_NEEDS_WEB = re.compile(
    r"\b(search|look up|google|news|latest|today'?s|current(?:ly)?|right now|score|who won|price|"
    r"stock|when does|is .{0,30} open|hours)\b",
    re.I,
)
_SMALLTALK = re.compile(
    r"^\s*(yo|hey|hi|hello|what'?s up|sup|how are you|how'?s it going|thanks|thank you|good (?:morning|night)|"
    r"lol|haha|bet|cool|nice|ok(?:ay)?)\b[\s\w,!?.']{0,40}$",
    re.I,
)
_STUDY = re.compile(
    r"\b(explain|teach me|help me understand|walk me through|quiz me|practice problems?|how does .{0,40} work|"
    r"what'?s the difference between|study)\b",
    re.I,
)


def detect_importance(text: str) -> Importance:
    if _HIGH.search(text):
        return "high"
    if _LOW.search(text):
        return "low"
    return "normal"


# Requests that are real thinking or long work: worth the classifier's ~second even on voice (the reply takes a while
# anyway, and picking the stronger model up front beats escalating mid-answer).
_NEEDS_THOUGHT = re.compile(
    r"\b(design|debug|architect\w*|plan (?:out|my|a|the)|strategy|prove|derive|analy[sz]e|compare|trade-?offs?|"
    r"optimi[sz]e|refactor|implement|algorithm|essay|report|research|outline|draft|write (?:a|an|me|my)|"
    r"step by step|in detail|learn how i)\b", re.I)


def rule_task(text: str) -> tuple[str | None, str]:
    """Return (task id, reason) from rules, or (None, "") if the classifier should decide."""
    for task, pattern in RULES:
        if pattern.search(text):
            return task, f"rule: {task.replace('_', ' ')}"
    if _COMMAND.search(text) and len(text) < 120:
        if _NEEDS_WEB.search(text):
            return "web_lookup", "rule: command needing the web"
        return "command", "rule: command"
    if _SMALLTALK.search(text):
        return "chat", "rule: small talk"
    if _STUDY.search(text):
        return "study_help", "rule: study help"
    if _NEEDS_WEB.search(text) and len(text) < 160:
        return "web_lookup", "rule: quick web lookup"
    return None, ""


# ---------------------------------------------------------------- classifier
CLASSIFIER_TASKS = ["chat", "quick_fact", "command", "weather", "web_lookup", "assignments", "check_off", "todo",
                    "task_helper", "health", "calendar", "memory_note", "general", "read_email", "triage", "briefing", "study_help",
                    "hard_problem", "draft_email", "research", "image_request"]


class TaskGuess(BaseModel):
    task: Literal[tuple(CLASSIFIER_TASKS)]  # type: ignore[valid-type]
    difficulty: int = Field(description="1 trivial, 2 easy, 3 moderate, 4 hard, 5 very hard")
    needs_web: bool
    reason: str = Field(description="under 12 words")


CLASSIFIER_PROMPT = (
    "Classify a college student's request to their voice assistant. Pick the task: chat (small talk), quick_fact "
    "(one-line stable fact), command (open a site, show pictures/videos, timers), weather, web_lookup (a current "
    "fact from the web: scores, hours, news), assignments (Canvas homework), check_off, todo (the user's own to-do "
    "list: add, list, finish or get help with an item), task_helper (do a multi-step job FOR them on a website or "
    "in an app: unsubscribe from mailing lists, fill in a form, change a setting, cancel a subscription, find "
    "something on a site and show it), health (Garmin sleep/heart "
    "rate, phone screen time), calendar, memory_note (remember/forget), general (an everyday question needing a few sentences), "
    "read_email, triage (rank emails/events), briefing (overview of the day), study_help (explain or teach a "
    "concept), hard_problem (careful multi-step reasoning, proofs, planning), draft_email, research (multi-source "
    "research or a report), image_request (make a new picture). Difficulty 1-5. needs_web = true if the answer "
    "depends on current or online information."
)


def classify_with_haiku(client, text: str) -> tuple[str, int, bool, str, object]:
    """Returns (task, difficulty, needs_web, reason, usage)."""
    if hasattr(client, "with_options"):
        client = client.with_options(max_retries=0)   # the SDK's 2 retries would turn the 4 s cap into ~13 s
    resp = client.messages.parse(
        model=HAIKU,
        max_tokens=1024,
        output_config={"effort": "low"},
        system=CLASSIFIER_PROMPT,
        messages=[{"role": "user", "content": f"<request>{text[:2000]}</request>"}],
        output_format=TaskGuess,
        timeout=4.0,              # a slow classifier must not hold up the reply: past this it's "general"
    )
    g: TaskGuess = resp.parsed_output
    return g.task, max(1, min(5, int(g.difficulty))), bool(g.needs_web), g.reason, resp.usage


def refine_task(task: str, difficulty: int, needs_web: bool) -> str:
    """Let difficulty and web needs move generic guesses to the right bucket."""
    if task in ("general", "quick_fact", "chat"):
        if needs_web:
            return "web_lookup" if difficulty <= 3 else "research"
        if difficulty >= 4:
            return "hard_problem"
        if task == "general" and difficulty <= 1:
            return "quick_fact"
        if task == "quick_fact" and difficulty >= 3:
            return "general"
    return task


# ---------------------------------------------------------------- router
class Router:
    def __init__(
        self,
        classify: Callable[[str], tuple] | None = None,
        budget_usd: Callable[[], float] | None = None,
        spent_usd: Callable[[], float] | None = None,
        forced_model: Callable[[], str] | None = None,
        profile: Callable[[], str] | None = None,
        policy: ModelPolicy | None = None,
    ):
        self._classify = classify
        self._budget = budget_usd or (lambda: float("inf"))
        self._spent = spent_usd or (lambda: 0.0)
        self._forced = forced_model or (lambda: "")
        self._profile = profile or (lambda: "best")
        self.policy = policy or ModelPolicy()

    def pick_task(self, text: str, fast: bool = False) -> tuple[str, str]:
        task, reason = rule_task(text)
        if task is not None:
            return task, reason
        if self._classify is None:
            return "general", "default"
        if fast and not _NEEDS_THOUGHT.search(text):
            # Voice: answer directly instead of waiting on a separate classifier call. The general model can still
            # escalate itself; requests that look like real thinking work still get classified (below).
            return "general", "fast path (no classifier)"
        try:
            got = self._classify(text)
            task, diff, needs_web, why = got[0], int(got[1]), bool(got[2]), str(got[3])
            if not self.policy.has(task):
                task = "general"
            return refine_task(task, diff, needs_web), f"classifier: {task} {diff}/5 ({why})"
        except Exception as exc:  # classifier is best-effort
            return "general", f"classifier failed ({type(exc).__name__}); default"

    def route(self, text: str, explicit_importance: Importance | None = None, sticky: Route | None = None,
              fast: bool = False) -> Route:
        importance: Importance = explicit_importance or detect_importance(text)
        task, reason = self.pick_task(text, fast=fast)

        forced = self._forced()
        if forced:
            effort = "high" if importance == "high" else ("low" if forced == HAIKU else "medium")
            return Route(forced, effort, importance, task, reason + " | model forced in Settings", "forced")

        tier = "max" if importance == "high" else "min" if importance == "low" else "default"
        if tier == "default" and self._profile() == "saver":
            tier = "min"
        c = self.policy.choice(task, tier)
        if importance == "high":
            reason += " + you said it's important"
        elif importance == "low":
            reason += " + you said quick"

        # Budget guard.
        budget, spent = self._budget(), self._spent()
        if budget and spent >= budget and importance != "high":
            c = self.policy.choice(task, "min")
            reason += " | monthly budget reached"
        elif budget and spent >= 0.9 * budget and importance != "high":
            lower = self.policy.step_down(task, c)
            if lower != c:
                c = lower
                reason += " | near monthly budget"

        # Sticky model for follow-ups (keeps the prompt cache warm).
        if (sticky is not None and importance == "normal" and sticky.model != c.model
                and self.policy.in_range(task, Choice(sticky.model, c.effort))
                and len(text) < 160):
            c = Choice(sticky.model, c.effort)
            reason += f" | follow-up, stayed on {MODEL_NAMES.get(c.model, c.model)}"

        return Route(c.model, c.effort, importance, task, reason, tier)

    def escalate(self, route: Route) -> Route:
        """Hand off to the next stronger model (used when a cheaper model asks for help)."""
        nxt = {HAIKU: Choice(SONNET, "medium"), SONNET: Choice(OPUS, "medium")}.get(route.model, Choice(OPUS, "high"))
        top = self.policy.choice(route.task, "max")
        if rank(top) > rank(Choice(route.model, route.effort)) and rank(top) < rank(nxt):
            nxt = top
        return replace(route, model=nxt.model, effort=nxt.effort, reason=route.reason + " → escalated")

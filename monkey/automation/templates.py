"""Task templates: what kind of job a goal is, and the extra rules, guidance and checks that come with it.

A template never widens what Monkey may do. It can only *narrow* the gate (`rules`, enforced in
permissions.PermissionGate, read from the task the owner started in Monkey's own UI) and add planner guidance and a
stricter "done" check. Page or email content can't pick a template or change its rules.

Built-ins:
  course            Canvas / LMS modules and trainings (the deterministic CourseSkill, ADR 0001). Unchanged.
  unsubscribe_page  One mailing list's web unsubscribe page: may only press an obvious unsubscribe/confirm control
                    and type only the owner's own address; deterministic (no Claude call); screenshot of the result.
  form_fill         "Fill in this form with my info, let me review": fills fields, never presses Submit on its own.
  look_only         "Find the cheapest flight… just show me": reading, searching, filtering; nothing is booked,
                    bought, sent or submitted (those are refused, not just asked).
  account_settings  Settings, subscriptions, trials and notifications on a site: every change asks first.
  shopping          Carts and bookings: Monkey stops before the final purchase button; payment details are never
                    typed (permissions.SENSITIVE_FIELD), and the purchase click needs the owner's approval of that step.
  generic           Anything else: the normal gate (HIGH asks, MEDIUM runs, read-only steps run freely).

The mailing-list review (monkey/mailing/) is the first-class "unsubscribe from mailing lists" job; a goal like
"unsubscribe me from the Medium newsletter" goes there (`PANEL_TEMPLATES`), not to a browser task.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# Words for an obvious unsubscribe or confirm control (matched on the control's accessible name).
UNSUB_CONTROL = (r"^\W*(?:unsubscribe(?: me)?(?: from (?:all|this list|these e-?mails|all e-?mails|this mailing list|"
                 r"marketing(?: e-?mails)?|everything))?|opt[- ]?out(?: of all)?|remove me(?: from (?:this|the) list)?|"
                 r"(?:yes,? )?(?:confirm|submit|continue)(?: unsubscribe)?|unsubscribe from all|"
                 r"stop (?:all )?e-?mails|update (?:my )?preferences|save (?:my )?preferences|"
                 r"unsubscribe all|confirm unsubscribe|yes,? unsubscribe(?: me)?)\W*$")
UNSUB_DONE = (r"\b(?:you(?:'ve| have)? (?:been )?(?:successfully )?unsubscribed|unsubscribed successfully|"
              r"unsubscribe(?:d)? (?:complete|successful|confirmed)|you(?:'ll| will) no longer (?:receive|get)|"
              r"(?:has|have) been removed from|you(?:'re| are) (?:now )?(?:unsubscribed|opted out)|opted out|"
              r"preferences (?:have been )?(?:saved|updated)|removed from (?:our|the|this) (?:mailing )?list|"
              r"sorry to see you go)\b")
UNSUB_CONTROL_RE = re.compile(UNSUB_CONTROL, re.I)
UNSUB_DONE_RE = re.compile(UNSUB_DONE, re.I)


@dataclass
class Template:
    id: str
    title: str
    blurb: str                                   # one line for the Tasks form
    example: str = ""                            # placeholder for "What should Monkey do?"
    match: re.Pattern | None = None              # on the owner's goal (their own words)
    skill: str = "general"                       # course | general
    rules: dict = field(default_factory=dict)    # narrows the gate: read_only, click_only, type_only, confirm_medium
    guidance: str = ""                           # trusted planner guidance (from Monkey, never from a page)
    done_text: str = ""                          # regex the page must show for "done" (on top of the evidence quote)
    deterministic: bool = False                  # runs without Claude (its skills decide every step)
    screenshot_result: bool = False              # keep a local screenshot of the final page for the owner
    skills: tuple = ()                           # deterministic step functions (view, memo, task) -> Plan | None
    fallback: str = "I need you for this one."   # deterministic templates: what to say when the skill is stuck

    def public(self) -> dict:
        return {"id": self.id, "title": self.title, "blurb": self.blurb, "example": self.example,
                "skill": self.skill, "rules": dict(self.rules), "deterministic": self.deterministic}

    def rules_for(self, **context) -> dict:
        """The gate rules for one task. `type_only` gets the owner's own values (e.g. their address) filled in."""
        r = dict(self.rules)
        if "type_only" in r:
            r["type_only"] = [v for v in context.get("type_only", []) if v]
        return r


# ------------------------------------------------------------------------------------------- unsubscribe page skill
def unsubscribe_step(view, memo: dict, task):
    """One web unsubscribe page, deterministically: type the owner's own address into an empty email field if the
    page asks, press the one obvious unsubscribe/confirm control, then report done when the page says so.
    Anything else (a sign-in, a captcha, several look-alike buttons, nothing recognizable) goes to the owner."""
    from .computer.goal import Plan

    text = f"{view.title}\n{view.text}"
    if UNSUB_DONE_RE.search(text):
        m = UNSUB_DONE_RE.search(text)
        return Plan(status="done", message="The page says you're unsubscribed.", evidence=m.group(0)[:120])
    pressed = memo.setdefault("unsub_pressed", 0)
    if pressed >= 3:
        return Plan(status="need_user", message="I pressed Unsubscribe but the page never confirmed it. Can you "
                                                "check the page?")
    emails = [v for v in (getattr(task, "rules", {}) or {}).get("type_only", []) if "@" in v]
    calls = []
    for e in view.elements:
        if e.role in ("textbox", "searchbox") and (e.input_type == "email" or re.search(r"e-?mail", e.name or "", re.I)) \
                and not (e.value or "").strip() and emails and not memo.get("typed"):
            calls.append({"name": "type_text", "input": {"id": e.id, "text": emails[0]}})
            memo["typed"] = True
            break
    buttons = [e for e in view.elements if e.role in ("button", "link", "checkbox", "radio") and e.enabled
               and UNSUB_CONTROL_RE.search(e.name or "")]
    # Prefer the most specific control: "Unsubscribe from all" over "Update preferences", buttons over links.
    buttons.sort(key=lambda e: (0 if re.search(r"unsubscribe|opt.?out|remove me", e.name, re.I) else 1,
                                0 if e.role == "button" else 1))
    if not buttons:
        # Nothing obvious to press (maybe after typing the address): the fallback hands it to the owner.
        return _plan(calls, "Typing your address where the page asks for it") if calls else None
    memo["unsub_pressed"] = pressed + 1
    calls.append({"name": "click", "input": {"id": buttons[0].id}})
    return _plan(calls, f"Pressing “{buttons[0].name[:40]}”")


def _plan(calls: list, subgoal: str):
    from .computer.goal import Plan

    return Plan(calls=calls, subgoal=subgoal)


# -------------------------------------------------------------------------------------------------------- registry
_R = lambda rx: re.compile(rx, re.I)  # noqa: E731

TEMPLATES: dict[str, Template] = {t.id: t for t in [
    Template(
        "course", "Course modules",
        "Canvas or another course site: works through modules and lessons; questions and confirmations stay yours.",
        "Work through the 4 modules of the Title IX training on Canvas",
        match=_R(r"\b(canvas|modules?|lessons?|training|course(?:work)?|compliance|title ix)\b"), skill="course"),
    Template(
        "unsubscribe_page", "Unsubscribe page (one mailing list)",
        "Opens the list's own unsubscribe page and presses only the unsubscribe button.",
        rules={"click_only": UNSUB_CONTROL, "type_only": [], "no_links": True},
        guidance="Only press an obvious unsubscribe/opt-out/confirm control. Type nothing except the owner's own "
                 "email address, and only if the page asks for it. Never press sign-up, subscribe, offers or links.",
        done_text=UNSUB_DONE, deterministic=True, screenshot_result=True, skills=(unsubscribe_step,),
        fallback="I couldn't find an obvious unsubscribe button on that page, so I didn't press anything. Can you "
                 "take a look?"),
    Template(
        "form_fill", "Fill in a form (you review)",
        "Fills the fields you give him; he asks before pressing Submit, and you can review first.",
        "Fill in the club sign-up form at example.org with my name and email, let me review",
        match=_R(r"\b(fill (?:in|out)|complete (?:the|this|a) (?:form|application)|form)\b"),
        guidance="Fill only fields whose values the owner gave in the objective; leave the rest empty and list them "
                 "in report_status. Do not press Submit/Send/Apply: when the form is filled, report need_user so "
                 "the owner can review (they can approve the submit step)."),
    Template(
        "look_only", "Look something up (just show me)",
        "Searches and reads; never books, buys, sends or submits anything.",
        "Find the cheapest flight from Madison to Denver on Dec 18, just show me",
        match=_R(r"\b(just show me|show me|look up|find (?:me )?(?:the )?(?:cheapest|best|price|prices|options)|"
                 r"compare (?:prices|options)|cheapest|don'?t (?:book|buy|order))\b"),
        rules={"read_only": True},
        guidance="Look-only task: search, filter, sort and read. Never book, buy, order, send, sign up or submit "
                 "(the executor refuses those). Finish with report_status done, quoting the answer on screen.",
    ),
    Template(
        "account_settings", "Change a setting on a site (asks every step)",
        "A setting, notification, subscription or trial; every change asks you first.",
        "Turn off promotional notifications in my Spotify account settings",
        match=_R(r"\b(settings?|notifications?|preferences|cancel (?:my )?.{0,30}(?:subscription|trial|membership|"
                 r"plan|reminder)|free trial|turn (?:on|off)|privacy)\b"),
        rules={"confirm_medium": True},
        guidance="This changes the owner's account: every toggle, save, cancel or confirm needs their approval (the "
                 "executor asks). Never touch passwords, two-factor or security settings (refused).",
    ),
    Template(
        "shopping", "Shopping (stops before paying)",
        "Gets things into the cart or booking page; stops before the final purchase.",
        "Put a 2-pack of AA batteries in my Target cart",
        match=_R(r"\b(buy|order|purchase|cart|book (?:a|the|my)|reserve|checkout|check out)\b"),
        guidance="Spending money is always the owner's call: stop before the final purchase/place-order/pay button "
                 "and report need_user. Never type payment details (refused).",
        # An icon-only "→" or an oddly named buy button reads as an unfamiliar control (MEDIUM): on a shopping site
        # every such step asks too, not just the ones whose names say pay/buy/order.
        rules={"confirm_medium": True}),
    Template(
        "generic", "Anything else",
        "Plans with Claude; reads freely, asks before anything that sends, submits, buys, deletes or changes an "
        "account.",
        "Download last month's statement PDF from my phone carrier's site"),
]}

# Goals that go to a Monkey panel instead of a browser task.
PANEL_TEMPLATES: dict[str, re.Pattern] = {
    # First: "archive the newsletters" is a cleanup, not an unsubscribe.
    "inbox_cleanup": _R(r"\b(?:(?:clean (?:up|out)|organi[sz]e|tidy(?: up)?|declutter|sort(?: out)?)\s+(?:up\s+)?"
                        r"(?:my |the |all (?:of )?my )?(?:e-?mails?|inbox(?:es)?|gmail|outlook|mail)\b|"
                        r"archive (?:all )?(?:the |my |old |those |these )?(?:old )?(?:newsletters|promos?|"
                        r"promotions|e-?mails|notifications|mail|junk)|inbox (?:cleanup|zero))\b"),
    "mailing_lists": _R(r"\b(unsubscribe|opt (?:me )?out|mailing lists?|newsletters?|marketing e-?mails?|"
                        r"stop (?:getting|receiving) (?:these |those |the |all )?(?:e-?mails|newsletters|promos?))\b"),
}


def get(tid: str) -> Template | None:
    return TEMPLATES.get(tid or "")


def pick(objective: str, start_url: str = "") -> Template:
    """The template for a general goal (the owner can change it in the form). Course isn't auto-picked for general
    tasks: the owner picks "Course modules" themselves."""
    text = objective or ""
    for tid in ("look_only", "form_fill", "shopping", "account_settings"):
        t = TEMPLATES[tid]
        if t.match is not None and t.match.search(text):
            return t
    return TEMPLATES["generic"]


def panel_for(objective: str, start_url: str = "") -> str:
    """'mailing_lists' when the goal is about unsubscribing from mail and no specific page was given."""
    if start_url:
        return ""
    for pid, rx in PANEL_TEMPLATES.items():
        if rx.search(objective or ""):
            return pid
    return ""


def listing() -> list[dict]:
    return [t.public() for t in TEMPLATES.values() if t.id != "unsubscribe_page"]


SkillFn = Callable[..., object]

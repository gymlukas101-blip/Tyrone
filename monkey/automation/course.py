"""A deterministic skill for course / training sites (Canvas modules, compliance trainings, LMS lessons).

It reads the accessibility outline (roles + names), never screen positions, so renamed buttons, links-vs-buttons,
re-rendered pages and different layouts still work. Routine pages cost no tokens. Anything it doesn't recognize is
handed to the Claude planner; anything that is the user's to do (answers, attestations, sign-in) is handed to the user.

It never answers questions, ticks confirmations, signs in, speeds up or skips media, or touches completion flags.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .browser import Element, Observation
from .permissions import Action, USER_ONLY_WORDS

CONTINUE = re.compile(r"^\W*(continue|next|next page|next lesson|next section|proceed|go on|forward)\W*$", re.I)
COMPLETE = re.compile(r"\b(complete|finish|mark)\b.*\b(module|lesson|section|unit|page)\b|^mark (as )?(complete|done)",
                      re.I)
PLAY = re.compile(r"(^|\W)(play|start video|watch|▶)(\W|$)", re.I)
DISMISS = re.compile(r"^\W*(not now|no thanks|close|dismiss|skip|later|maybe later|×|x|got it|ok)\W*$", re.I)
START = re.compile(r"\b(start|open|begin|resume|continue|go to)\b.*\b(module|lesson|unit|chapter|section)\b", re.I)
ERROR_PAGE = re.compile(r"\b(50[0-4]|service (temporarily )?unavailable|something went wrong|bad gateway|"
                        r"server error|try again later)\b", re.I)
SIGN_IN = re.compile(r"\b(sign in|log ?in|session (has )?expired|authenticate|single sign-on|netid)\b", re.I)
DONE_PAGE = re.compile(r"\b(course complete|completion record|certificate of completion|all \d+ modules? (are )?complete)\b",
                       re.I)
UNIT = re.compile(r"\b(module|lesson|unit|chapter)\s+(\d+)\b", re.I)
STATUS_DONE = re.compile(r"\b(completed|complete|done|finished|passed)\b|✓|✔", re.I)
STATUS_NOT = re.compile(r"\b(not started|in progress|locked|incomplete|not complete)\b", re.I)


@dataclass
class Step:
    kind: str                       # act | wait | user | retry | verify | stuck | navigate
    action: Action | None = None
    el: Element | None = None
    wait_js: str = ""               # wait until truthy in the page
    wait_change: bool = False       # wait until the page changes (the user did their part)
    timeout_s: float = 60
    message: str = ""               # what to tell the user
    user_kind: str = ""             # user_turn | sign_in | approval
    expect: str = "change"          # change | media_playing | none
    subgoal: str = ""
    approval_id: str = ""


@dataclass
class Overview:
    units: dict = field(default_factory=dict)     # {n: "done" | "todo"}

    @property
    def total(self) -> int:
        return len(self.units)

    @property
    def done(self) -> int:
        return sum(1 for v in self.units.values() if v == "done")


def read_overview(obs: Observation) -> Overview:
    """Units and their status from the page text: 'Module 2 … Status: Completed'. Works for lists, tables, cards."""
    ov = Overview()
    lines = [ln.strip() for ln in obs.text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        m = UNIT.search(ln)
        if not m or len(ln) > 120:
            continue
        n = int(m.group(2))
        near = " ".join([ln] + lines[i + 1:i + 3])
        near = near.split(m.group(0), 1)[-1]
        nxt = UNIT.search(near)
        if nxt:
            near = near[:nxt.start()]
        if STATUS_DONE.search(near) and not STATUS_NOT.search(near):
            ov.units[n] = "done"
        elif n not in ov.units:
            ov.units[n] = "todo"
    return ov


def _in_dialog(obs: Observation) -> tuple[Element | None, list[Element]]:
    for i, e in enumerate(obs.elements):
        if e.role in ("dialog", "alertdialog"):
            inside = []
            for f in obs.elements[i + 1:]:
                if f.depth <= e.depth:
                    break
                inside.append(f)
            return e, inside
    return None, []


class CourseSkill:
    name = "course"

    def decide(self, obs: Observation, memo: dict) -> Step:
        heads = " | ".join(obs.headings)
        title = f"{obs.title} | {heads}"
        # 1. The site is down: reload a few times (bounded by the manager), then report BLOCKED.
        if ERROR_PAGE.search(title) and len(obs.elements) < 12:
            return Step("retry", subgoal="the site returned an error page", message="The site returned an error.")
        # 2. Sign-in / expired session: the user signs in themselves. Monkey never sees or types passwords.
        if obs.has_password_field or (SIGN_IN.search(heads) and obs.find(("textbox",))):
            return Step("user", user_kind="sign_in", wait_change=True, timeout_s=900,
                        subgoal="waiting for you to sign in",
                        message="Please sign in in the Monkey browser window. I don't look at or type passwords; "
                                "I'll continue when you're in.")
        # 3. A pop-up in the way: dismiss it if it has a harmless way out, otherwise ask.
        dlg, inside = _in_dialog(obs)
        if dlg is not None:
            out = [e for e in inside if e.role in ("button", "link") and DISMISS.match(e.name or "") and not e.disabled]
            if out:
                return Step("act", Action("click"), out[0], subgoal=f"closing the pop-up “{dlg.name[:40]}”")
            return Step("user", user_kind="user_turn", wait_change=True, timeout_s=600,
                        subgoal="a pop-up needs a decision",
                        message=f"A pop-up (“{dlg.name[:60]}”) needs a decision from you.")
        # 4. Finished?
        if DONE_PAGE.search(f"{title} {obs.text[:400]}"):
            return Step("verify", subgoal="checking the course is really complete")
        # 5. Course overview: open the first unfinished unit.
        ov = read_overview(obs)
        starts = obs.find(("link", "button"), START, enabled_only=True)
        if ov.total >= 2 and (starts or ov.done == ov.total):
            if ov.done == ov.total:
                return Step("verify", subgoal="every module shows complete")
            todo = sorted(n for n, v in ov.units.items() if v == "todo")
            pick = next((e for e in starts if todo and re.search(rf"\b{todo[0]}\b", e.name)), starts[0] if starts else None)
            if pick is not None:
                return Step("act", Action("click"), pick, subgoal=f"opening module {todo[0] if todo else ''}".strip())
        # 6. Things that are the user's to do on this page.
        attest = [e for e in obs.find(("checkbox",)) if not e.checked and USER_ONLY_WORDS.search(e.name or "")]
        cont = obs.find(("button", "link"), CONTINUE)
        complete = obs.find(("button", "link"), COMPLETE)
        enabled_next = [e for e in complete + cont if not e.disabled]
        if attest and not enabled_next:
            return Step("user", user_kind="user_turn", wait_change=True, timeout_s=1800,
                        subgoal="your confirmation",
                        message=f"This needs your own confirmation (“{attest[0].name[:80]}”). Tick it yourself if "
                                "it's true; I'll take it from there.")
        question = [e for e in obs.elements if e.in_question and e.role in ("radio", "checkbox", "textbox", "combobox")]
        if question and not enabled_next:
            return Step("user", user_kind="user_turn", wait_change=True, timeout_s=1800,
                        subgoal="your answer to the practice question",
                        message="There's a question here, and the answers are yours. Answer it in the browser "
                                "(ask me if you want it explained) and I'll continue when it's done.")
        # 7. Media: press the page's own Play, then wait locally until it really ends (no tokens, no skipping).
        media = [m for m in obs.media if not m.get("ended")]
        if media and not enabled_next:
            m = media[0]
            if m.get("paused"):
                if memo.get("play_tries", 0) >= 2:
                    return Step("user", user_kind="user_turn", wait_change=True, timeout_s=900,
                                subgoal="the lesson won't start", message="The lesson didn't start playing. Press play "
                                "in the browser and I'll keep watching for the end.")
                play = obs.find(("button", "link"), PLAY, enabled_only=True)
                if play:
                    memo["play_tries"] = memo.get("play_tries", 0) + 1
                    return Step("act", Action("play"), play[0], expect="media_playing", subgoal="starting the lesson")
                # Paused and no Play control yet: the page is probably still rendering. Wait briefly, not for the
                # whole lesson (a paused lesson never ends on its own).
                memo["play_tries"] = memo.get("play_tries", 0) + 1
                return Step("wait", wait_js=_PLAY_READY_JS, timeout_s=10, subgoal="waiting for the lesson to load")
            remaining = (m.get("d") or 600) - (m.get("t") or 0)
            return Step("wait", wait_js=_MEDIA_DONE_JS, timeout_s=max(30.0, remaining * 1.5 + 30),
                        subgoal="the lesson is playing; I'll continue when it ends")
        memo.pop("play_tries", None)
        # 8. Move on: finish the unit if that's offered, otherwise Continue.
        for group in (complete, cont):
            ok = [e for e in group if not e.disabled]
            if ok:
                return Step("act", Action("click"), ok[0], subgoal=f"clicking “{ok[0].name[:40]}”")
        if cont or complete:
            return Step("wait", wait_js=_NEXT_ENABLED_JS, timeout_s=120,
                        subgoal="waiting for the page to let me continue")
        return Step("stuck", subgoal="I don't recognize this page")

    def verify(self, obs: Observation) -> tuple[bool, dict]:
        """Completion is what the site itself shows on the course overview, not what Monkey remembers clicking."""
        ov = read_overview(obs)
        ok = ov.total >= 1 and ov.done == ov.total and bool(DONE_PAGE.search(obs.text) or ov.total)
        return ok, {"units": ov.units, "done": ov.done, "total": ov.total, "page": obs.title[:80]}


_MEDIA_DONE_JS = """() => { const ms = [...document.querySelectorAll('video,audio')];
  // The page re-rendered and swapped in a fresh (stopped) player: look again instead of waiting it out.
  if (!window.__mkMedia || !window.__mkMedia.isConnected) {
    const was = window.__mkMedia; window.__mkMedia = ms[0] || null; if (was && ms[0] && ms[0].paused) return true; }
  const next = [...document.querySelectorAll('button,a,[role=button]')].some(b =>
      /^\\W*(continue|next|next page|proceed)\\W*$/i.test((b.innerText || b.getAttribute('aria-label') || '').trim())
      && !b.disabled && b.getAttribute('aria-disabled') !== 'true');
  return ms.every(m => m.ended) || (next && ms.every(m => m.ended || m.paused)); }"""
_PLAY_READY_JS = """() => [...document.querySelectorAll('video,audio')].some(m => !m.paused || m.ended) ||
  [...document.querySelectorAll('button,a,[role=button]')].some(b => b.offsetParent !== null &&
      /(^|\\W)(play|start video|watch|▶)(\\W|$)/i.test((b.innerText || b.getAttribute('aria-label') || '').trim()))"""
_NEXT_ENABLED_JS = """() => [...document.querySelectorAll('button,a,[role=button]')].some(b =>
  /^\\W*(continue|next|next page|proceed|complete module|finish module|mark module complete)\\W*$/i
    .test((b.innerText || b.getAttribute('aria-label') || '').trim()) && !b.disabled)"""

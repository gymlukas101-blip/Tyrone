"""Risk classes and the execution-layer permission gate.

Every action Monkey takes on a page or window goes through PermissionGate.authorize() inside the driver, whichever
planner chose it (the deterministic course skill or Claude). Decisions depend only on:
  * the task's scope, which the user granted in Monkey's own UI (mode, allowed domains, window), and
  * what the control *is* (role, accessible name, input type, sensitive flags), read by the driver.
Nothing a page says can widen that. Approvals are one-time tokens that only Monkey's UI ever sees.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from urllib.parse import urlsplit


class Risk(IntEnum):
    LOW = 1          # read an approved page/window, routine navigation (Continue, Next, Back, Play, close a popup)
    MEDIUM = 2       # edit a field, pick an option, download, change a setting, "mark complete"
    HIGH = 3         # send, submit an official form, buy, delete, change an account or permissions, accept terms
    USER_ONLY = 4    # the user must do it themselves: assessments, attestations, surveys about them, sign-in
    FORBIDDEN = 5    # never: typing into password/card fields, javascript:/file: URLs, off-scope targets


@dataclass
class Target:
    """What the driver knows about the control an action touches."""
    role: str = ""
    name: str = ""
    input_type: str = ""          # password, email, checkbox, radio, file, ...
    href: str = ""
    sensitive: bool = False       # password/card/SSN/one-time-code field or a sensitive window
    in_question: bool = False     # inside a quiz/assessment/survey (radio groups, "Question 3 of 10", ...)
    disabled: bool = False


@dataclass
class Action:
    kind: str                     # click | type | select | press | scroll | navigate | wait | read | play | upload | choose_file
    target: Target | None = None
    text: str = ""                # for type/select/press; never logged
    url: str = ""                 # for navigate
    path: str = ""                # for upload/choose_file: the local file (must be one the user put in the task)
    to_web: bool = False          # choose_file in a picker that belongs to a browser = sending the file to a site

    def fingerprint(self, page_url: str) -> str:
        t = self.target or Target()
        host = urlsplit(page_url).hostname or "" if page_url else ""
        return f"{self.kind}|{t.role}|{t.name.strip().lower()[:80]}|{self.url}|{host}|{self.path}"

    def describe(self) -> str:
        t = self.target
        what = f'{t.role} "{t.name[:60]}"' if t and (t.role or t.name) else ""
        if self.kind == "navigate":
            return f"open {self.url[:80]}"
        if self.kind == "press" and re.fullmatch(r"[A-Za-z0-9+ ]{1,24}", self.text or ""):
            return f"press {self.text}"
        if self.kind in ("upload", "choose_file"):
            from pathlib import PurePath

            return f"{'send' if self.kind == 'upload' or self.to_web else 'pick'} the file {PurePath(self.path).name}"
        if self.kind == "type":
            return f"type {len(self.text)} characters into {what}"
        return f"{self.kind} {what}".strip()


@dataclass
class Decision:
    allowed: bool
    risk: Risk
    reason: str = ""
    needs_approval: bool = False
    user_only: bool = False


# ---- word lists (matched on the control's accessible name, not on page prose) ----------------------------------
_W = lambda *ws: re.compile(r"\b(" + "|".join(ws) + r")\b", re.I)  # noqa: E731
USER_ONLY_WORDS = _W(r"i (?:confirm|certify|attest|acknowledge|agree|affirm|have read|understand)", r"attest\w*",
                     "certif(?:y|ication statement)", "acknowledge(?:ment)?", r"e-?sign\w*", "signature",
                     r"submit (?:quiz|exam|test|assessment|answers?|attempt|survey|evaluation|response)",
                     r"(?:finish|end|start) (?:quiz|exam|test|assessment|attempt)", "check answer", "submit answer",
                     "captcha", "i'?m not a robot", "sign in", "log ?in", "verify (?:it'?s|its) you")
HIGH_WORDS = _W("submit", "send", "post", "publish", "pay", "purchase", "buy", "checkout", "check out", "place order",
                "order now", "donate", "subscribe", "delete", "remove", "erase", "unenroll", "enroll", "register",
                "drop (?:class|course)", "withdraw", "transfer", "accept(?: terms)?", "agree", "share", "invite",
                "change password", "reset password", "deactivate", "close account", "grant", "allow access",
                "authorize", "confirm (?:purchase|order|payment|deletion)", "reply", "forward", "upload", "save and submit")
MEDIUM_WORDS = _W("save", "mark (?:as )?(?:complete|completed|done|read)", "complete module", "complete lesson",
                  "download", "export", "apply", "update", "edit", "settings", "turn (?:on|off)", "enable", "disable")
LOW_WORDS = _W("continue", "next", "next page", "back", "previous", "prev", "start", "resume", "begin", "open",
               "view", "play", "pause", "replay", "close", "dismiss", "not now", "no thanks", "skip", "later", "ok",
               "got it", "expand", "collapse", "show", "hide", "menu", "home", "proceed", "go to", "module", "lesson")
SENSITIVE_FIELD = re.compile(r"(passw|passcode|\bpin\b|one[- ]time|otp|2fa|mfa code|verification code|security code|"
                             r"card ?number|credit card|cvv|cvc|expir|social security|\bssn\b|routing|account number|"
                             r"bank)", re.I)
SENSITIVE_WINDOW = re.compile(r"(1password|bitwarden|keepass|lastpass|dashlane|keeper|password manager|"
                              r"credential manager|windows security|user account control|bank|banking|paypal|venmo|"
                              r"wallet|sign in to your account)", re.I)
READ_KINDS = {"read", "wait", "screenshot", "scroll"}


def classify(action: Action) -> tuple[Risk, str]:
    """Risk of one action from what the control is. Unknown clicks default to MEDIUM, never LOW."""
    t = action.target or Target()
    name = f"{t.name} {t.role}".strip()
    if action.kind in READ_KINDS:
        return Risk.LOW, "reading"
    if action.kind == "navigate":
        return Risk.LOW, "opening an allowed page"
    if action.kind == "upload" or (action.kind == "choose_file" and action.to_web):
        return Risk.HIGH, "this sends a file from your PC to the site"
    if action.kind == "choose_file":
        return Risk.MEDIUM, "picking a file in the app's Open/Save box"
    if t.sensitive or t.input_type in ("password",) or (action.kind == "type" and SENSITIVE_FIELD.search(name)):
        return Risk.FORBIDDEN, "sensitive field (passwords, codes and card numbers are yours to type)"
    if action.kind in ("type", "select") and t.in_question:
        return Risk.USER_ONLY, "an answer to a question is yours to give"
    if action.kind == "click" and t.in_question and t.role in ("radio", "checkbox", "option", "textbox", "combobox"):
        return Risk.USER_ONLY, "an answer to a question is yours to give"
    if USER_ONLY_WORDS.search(t.name or ""):
        return Risk.USER_ONLY, "this needs you (an attestation, assessment or sign-in)"
    if action.kind == "click" and t.role == "checkbox" and re.search(r"\b(i |agree|confirm|consent)", t.name or "", re.I):
        return Risk.USER_ONLY, "ticking a statement about you is yours to do"
    if action.kind == "type":
        return Risk.MEDIUM, "editing a field (nothing is submitted)"
    if action.kind in ("select", "press"):
        return (Risk.MEDIUM, "choosing an option") if action.kind == "select" else _press_risk(action.text)
    if HIGH_WORDS.search(t.name or ""):
        return Risk.HIGH, "this sends, submits, buys, deletes or changes something"
    if MEDIUM_WORDS.search(t.name or ""):
        return Risk.MEDIUM, "saves or changes something"
    if LOW_WORDS.search(t.name or "") or t.role in ("link", "tab", "menuitem", "treeitem"):
        return Risk.LOW, "routine navigation"
    if action.kind == "play":
        return Risk.LOW, "playing the lesson media"
    return Risk.MEDIUM, "an unfamiliar control"


def _press_risk(keys: str) -> tuple[Risk, str]:
    k = (keys or "").lower()
    if k in ("enter", "return") or "enter" in k:
        return Risk.MEDIUM, "Enter can submit a form"
    return Risk.LOW, "a navigation key"


def url_allowed(url: str, allowed_domains: list[str]) -> tuple[bool, str]:
    if re.search(r"[\s\x00-\x1f\x7f]", url or ""):
        return False, "the address has hidden characters"
    if url in ("back", "forward", "reload", "about:blank"):
        return True, ""
    with_scheme = url if re.match(r"[a-z][a-z0-9+.-]*:", url, re.I) else f"https://{url}"
    try:
        p = urlsplit(with_scheme.replace("\\", "/"))
    except ValueError:
        return False, "the address can't be read"
    if p.scheme not in ("http", "https"):
        return False, f"{p.scheme}: addresses are never opened"
    host = (p.hostname or "").lower().rstrip(".")
    if "*" in allowed_domains and host:
        return True, ""                                   # the user let this task use any website
    for d in allowed_domains:
        d = d.lower().strip().rstrip(".")
        if d and (host == d or host.endswith("." + d)):
            return True, ""
    return False, f"{host or 'that site'} isn't one of the sites you allowed for this task"


def path_allowed(path: str, allowed: list[str]) -> tuple[bool, str]:
    """Files are in scope only if the user named them (or a folder holding them) for this task."""
    from pathlib import Path

    if not path:
        return False, "no file was given"
    try:
        p = Path(path).expanduser().resolve()
    except (OSError, ValueError):
        return False, "that file path can't be read"
    for a in allowed:
        try:
            q = Path(a).expanduser().resolve()
        except (OSError, ValueError):
            continue
        if p == q or q in p.parents:
            return True, ""
    return False, f"{p.name} isn't one of the files you gave this task"


@dataclass
class Approval:
    id: str
    task_id: str
    fingerprint: str
    summary: str
    risk: str
    token: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    status: str = "pending"           # pending | approved | used | denied
    created: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {"id": self.id, "task_id": self.task_id, "summary": self.summary, "risk": self.risk,
                "status": self.status, "token": self.token}    # the UI needs the token; the model never sees this


class PermissionGate:
    """Enforced in the drivers. Thread-safe; the emergency stop flips `stopped` for every task at once."""

    def __init__(self):
        self._lock = threading.Lock()
        self._approvals: dict[str, Approval] = {}
        self.stopped = threading.Event()

    def authorize(self, scope, action: Action, page_url: str = "", paused: bool = False) -> Decision:
        """scope: a Task (mode, allowed_domains, confirm_medium, id)."""
        if self.stopped.is_set() or paused:
            return Decision(False, Risk.LOW, "Monkey is stopped or paused")
        risk, why = classify(action)
        if scope.mode == "observe_window" and action.kind not in READ_KINDS:
            return Decision(False, risk, "this task can only look, not click or type")
        if action.kind not in READ_KINDS and action.kind != "navigate" and page_url.startswith("http") \
                and getattr(scope, "allowed_domains", None) and not url_allowed(page_url, scope.allowed_domains)[0]:
            # A redirect can land on a site you never allowed: nothing is clicked or typed there.
            return Decision(False, Risk.FORBIDDEN, "this page is on a site you didn't allow for this task")
        if action.kind == "navigate":
            ok, msg = url_allowed(action.url, scope.allowed_domains)
            if not ok:
                return Decision(False, Risk.FORBIDDEN, msg)
        if action.kind in ("upload", "choose_file"):
            ok, msg = path_allowed(action.path, getattr(scope, "files", []) or [])
            if not ok:
                return Decision(False, Risk.FORBIDDEN, msg)
        if action.target is not None and action.target.href and not action.target.href.startswith("#"):
            from urllib.parse import urljoin

            ok, msg = url_allowed(urljoin(page_url or "", action.target.href), scope.allowed_domains)
            if not ok:
                return Decision(False, Risk.FORBIDDEN, f"that link leaves the allowed sites ({msg})")
        if risk == Risk.FORBIDDEN:
            return Decision(False, risk, why)
        if risk == Risk.USER_ONLY:
            # Your own answer or confirmation (said, typed or clicked in Monkey) lets him click exactly that, once.
            if self._consume(scope.id, action.fingerprint(page_url)):
                return Decision(True, risk, "your choice")
            return Decision(False, risk, why, user_only=True)
        if risk == Risk.HIGH or (risk == Risk.MEDIUM and getattr(scope, "confirm_medium", False)):
            if self._consume(scope.id, action.fingerprint(page_url)):
                return Decision(True, risk, "you approved this")
            return Decision(False, risk, why, needs_approval=True)
        return Decision(True, risk, why)

    # ---- approvals ---------------------------------------------------------------------------------------------
    def request(self, task_id: str, action: Action, page_url: str, risk: Risk) -> Approval:
        fp = action.fingerprint(page_url)
        with self._lock:
            for a in self._approvals.values():
                if a.task_id == task_id and a.fingerprint == fp and a.status == "pending":
                    return a
            a = Approval("ap_" + secrets.token_hex(4), task_id, fp, action.describe(), risk.name.lower())
            self._approvals[a.id] = a
            return a

    def approve(self, approval_id: str, token: str) -> Approval:
        with self._lock:
            a = self._approvals.get(approval_id)
            if a is None or a.status != "pending" or not secrets.compare_digest(a.token, token or ""):
                raise PermissionError("That approval isn't valid any more")
            a.status, a.token = "approved", ""
            return a

    def grant_user_choice(self, task_id: str, action: Action, page_url: str) -> None:
        """Only Monkey's reply handler calls this, with the user's own letter or "I confirm": a one-time grant for that
        exact click. Page content can't reach it, and FORBIDDEN actions (passwords, codes) can never be granted."""
        if classify(action)[0] == Risk.FORBIDDEN:
            raise PermissionError("That can't be done for you")
        a = Approval("uc_" + secrets.token_hex(4), task_id, action.fingerprint(page_url), action.describe(), "user_choice",
                     token="", status="approved")
        with self._lock:
            self._approvals[a.id] = a

    def deny(self, approval_id: str) -> None:
        with self._lock:
            a = self._approvals.get(approval_id)
            if a and a.status == "pending":
                a.status, a.token = "denied", ""

    def _consume(self, task_id: str, fingerprint: str) -> bool:
        with self._lock:
            for a in self._approvals.values():
                if a.task_id == task_id and a.fingerprint == fingerprint and a.status == "approved":
                    a.status = "used"                      # one approval = one action, never a standing grant
                    return True
        return False

    def status(self, approval_id: str) -> str:
        a = self._approvals.get(approval_id)
        return a.status if a else "unknown"

    def pending_for(self, task_id: str) -> list[Approval]:
        return [a for a in self._approvals.values() if a.task_id == task_id and a.status == "pending"]

    def drop_task(self, task_id: str) -> None:
        with self._lock:
            for a in self._approvals.values():
                if a.task_id == task_id and a.status in ("pending", "approved"):
                    a.status, a.token = "denied", ""

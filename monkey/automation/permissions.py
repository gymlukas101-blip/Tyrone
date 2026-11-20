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
    kind: str                     # click | type | select | press | scroll | navigate | wait | read | play
    target: Target | None = None
    text: str = ""                # for type/select/press; never logged
    url: str = ""                 # for navigate

    def fingerprint(self, page_url: str) -> str:
        t = self.target or Target()
        host = urlsplit(page_url).hostname or "" if page_url else ""
        return f"{self.kind}|{t.role}|{t.name.strip().lower()[:80]}|{self.url}|{host}"

    def describe(self) -> str:
        t = self.target
        what = f'{t.role} "{t.name[:60]}"' if t and (t.role or t.name) else ""
        if self.kind == "navigate":
            return f"open {self.url[:80]}"
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
    if action.kind == "press":
        # Scored by the key *and* what it lands on (Tab on a focused "Sign in" is still just Tab).
        return _press_risk(action.text, action.target)
    if action.kind == "type" and "\n" in (action.text or ""):
        r, why = _press_risk("Enter", action.target)       # a line break in typed text presses Enter
        if r > Risk.MEDIUM:
            return r, why
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
    if action.kind == "select":
        return Risk.MEDIUM, "choosing an option"
    if HIGH_WORDS.search(t.name or ""):
        return Risk.HIGH, "this sends, submits, buys, deletes or changes something"
    if MEDIUM_WORDS.search(t.name or ""):
        return Risk.MEDIUM, "saves or changes something"
    if LOW_WORDS.search(t.name or "") or t.role in ("link", "tab", "menuitem", "treeitem"):
        return Risk.LOW, "routine navigation"
    if action.kind == "play":
        return Risk.LOW, "playing the lesson media"
    return Risk.MEDIUM, "an unfamiliar control"


# Keys that send, delete or close things on their own (mail clients, editors, browsers, Explorer).
_DANGER_KEYS = re.compile(r"^(?:(?:control|ctrl|meta|cmd)\+(?:shift\+)?(?:enter|return|w|q|d|delete)|"
                          r"alt\+(?:s|f4|enter|return)|(?:shift\+)?(?:delete|del)|control\+shift\+w)$", re.I)
_NAV_KEYS = {"tab", "shift+tab", "arrowup", "arrowdown", "arrowleft", "arrowright", "up", "down", "left", "right",
             "pageup", "pagedown", "home", "end", "escape", "esc"}
_ACTIVATE_KEYS = {"enter", "return", "space", " ", "numpadenter", "spacebar"}


_PYWIN = {"^": "control+", "%": "alt+", "+": "shift+"}
_COMPOSER = re.compile(r"\b(message|reply|comment|post|chat|tweet|send|compose|write a)\b", re.I)


def normalize_keys(keys: str) -> list[str]:
    """Playwright names ("Control+Enter Tab") and pywinauto syntax ("^{ENTER}", "%{F4}", "{DELETE}") → one form."""
    k = (keys or "").strip()
    if "{" in k or (k[:1] in _PYWIN and len(k) > 1):
        out = []
        for m in re.finditer(r"([\^%+]*)(\{[^}]+\}|.)", k):
            mods = "".join(_PYWIN[c] for c in m.group(1))
            key = m.group(2).strip("{}").split()[0] if m.group(2).startswith("{") else m.group(2)
            if key.strip():
                out.append(mods + key.lower())
        return out
    return [x for x in re.split(r"[\s,]+", k) if x]


def _press_risk(keys: str, target: Target | None = None) -> tuple[Risk, str]:
    """A key press is as risky as what it does: Enter/Space on a focused control *is* pressing that control (so
    "Send", "Submit quiz", "Delete account" get their own risk), and some chords send/delete/close by themselves.
    Several keys in one press ("Tab Tab Enter") take the riskiest one. Unknown keys are MEDIUM, never LOW."""
    worst: tuple[Risk, str] = (Risk.LOW, "a navigation key")
    t = target
    for k in normalize_keys(keys) or [""]:
        kl = k.lower()
        if _DANGER_KEYS.match(kl):
            r = (Risk.HIGH, f"{k} can send, delete or close something")
        elif kl in _NAV_KEYS:
            # Arrow keys on a quiz option change the answer; elsewhere they just move.
            if t is not None and t.in_question and t.role in ("radio", "option", "checkbox", "combobox", "listbox") \
                    and kl not in ("tab", "shift+tab", "escape", "esc"):
                r = (Risk.USER_ONLY, "an answer to a question is yours to give")
            else:
                r = (Risk.LOW, "a navigation key")
        elif kl in ("space", " ", "spacebar") and t is not None and t.in_question:
            r = (Risk.USER_ONLY, "an answer to a question is yours to give")
        elif kl in ("enter", "return", "numpadenter") and t is not None and \
                t.role in ("textbox", "searchbox", "combobox") and _COMPOSER.search(t.name or ""):
            r = (Risk.HIGH, "Enter here sends the message")
        elif kl in _ACTIVATE_KEYS or kl.endswith("+enter") or kl.endswith("+return"):
            if target is not None and (target.name or target.role):
                cr, why = classify(Action("click", target=target))
                r = (max(cr, Risk.MEDIUM), why if cr > Risk.MEDIUM else "Enter/Space presses the focused control")
            else:
                r = (Risk.MEDIUM, "Enter can submit a form")
        else:
            r = (Risk.MEDIUM, "a key that may change something")
        if r[0] > worst[0]:
            worst = r
    return worst


_SECOND_LEVEL = {"co", "com", "ac", "org", "net", "gov", "edu", "ne", "or"}


def registrable(host: str) -> str:
    """example.co.uk / attacker.example — the part a site owner controls (small public-suffix heuristic)."""
    parts = [p for p in (host or "").lower().rstrip(".").split(".") if p]
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _looks_like_data_out(url: str, page_url: str) -> bool:
    """A typed address to another site that carries a lot of data (query, fragment or a long path)."""
    try:
        u = urlsplit(url if re.match(r"[a-z][a-z0-9+.-]*:", url or "", re.I) else f"https://{url}")
        cur = (urlsplit(page_url).hostname or "") if page_url else ""
    except ValueError:
        return True
    if not cur:
        return False                      # nothing loaded yet (about:blank, the start page): no page data to carry
    host = (u.hostname or "").lower()
    if registrable(host) == registrable(cur):
        return False
    return len(u.path) + len(u.query) + len(u.fragment) > 80


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
            if "*" in (scope.allowed_domains or []) and _looks_like_data_out(action.url, page_url):
                # "Any website" is the owner's choice, so ordinary navigation never asks. But a typed address to a
                # *different* site that carries a long query string is the shape of page-steered data theft: ask.
                if self._consume(scope.id, action.fingerprint(page_url)):
                    return Decision(True, Risk.HIGH, "you approved this")
                return Decision(False, Risk.HIGH, "this opens another site with a lot of data in the address",
                                needs_approval=True)
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

    def pending_for(self, task_id: str) -> list[Approval]:
        return [a for a in self._approvals.values() if a.task_id == task_id and a.status == "pending"]

    def drop_task(self, task_id: str) -> None:
        with self._lock:
            for a in self._approvals.values():
                if a.task_id == task_id and a.status in ("pending", "approved"):
                    a.status, a.token = "denied", ""

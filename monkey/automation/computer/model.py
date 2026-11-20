"""The shared vocabulary of Monkey's computer use: targets, outcomes, typed errors, coordinate spaces, capabilities.

Every backend (managed browser, Windows UI Automation, visual grounding) speaks this, so the task loop, the trace,
the UI and the planner never see a library's own types. Three rules it encodes:

* A target is identified by *what it is* (backend, session, ref, role, name, automation id), never only by where it
  was. Coordinates always carry their space (VIEWPORT = browser CSS px of one page, SCREEN = physical px on the
  virtual desktop, IMAGE = px of a resized screenshot); converting between them is explicit (see coords.py).
* An outcome separates *accepted* (the permission gate allowed it), *executed* (the backend did it without error),
  *changed* (the UI visibly changed), and *verified* (the expected state was read back). Only the last one counts
  as progress toward the user's goal.
* Errors are typed, and each type maps to recovery strategies the loop can try without a model call.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from enum import Enum

from ..permissions import Target


class Space(str, Enum):
    VIEWPORT = "viewport"       # CSS px in one browser page's viewport (Playwright mouse coordinates)
    SCREEN = "screen"           # physical px on the Windows virtual desktop (may be negative on left/top monitors)
    IMAGE = "image"             # px of a screenshot as resized for a model


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float
    space: Space

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h


class ErrorKind(str, Enum):
    NOT_FOUND = "not_found"               # nothing matches the target description / ref
    STALE = "stale"                       # the ref existed but the UI re-rendered
    NOT_INTERACTABLE = "not_interactable" # disabled, hidden, zero-size
    COVERED = "covered"                   # another window/overlay is on top of the target
    REFUSED = "refused"                   # the permission gate said no (never retried)
    NEEDS_APPROVAL = "needs_approval"     # allowed only with the user's one-time approval
    NEEDS_USER = "needs_user"             # the user's own action (answers, attestations, sign-in)
    TIMEOUT = "timeout"
    SESSION_LOST = "session_lost"         # the browser/window closed
    NO_EFFECT = "no_effect"               # executed, but nothing changed
    UNSUPPORTED = "unsupported"           # this backend can't do that op on that target
    WRONG_WINDOW = "wrong_window"         # focus/target window isn't the one in scope
    USER_ACTIVE = "user_active"           # the user is using the mouse/keyboard: physical input waits
    DUPLICATE = "duplicate"               # the same op already ran from this exact state (idempotency guard)
    AMBIGUOUS = "ambiguous"               # the description/identity matches several controls: never guess
    NEEDS_FOREGROUND = "needs_foreground" # only the real mouse/keyboard would work, and the user hasn't allowed it
    UNRESPONSIVE = "unresponsive"         # the app isn't answering (hung window)
    ELEVATED = "elevated"                 # the window runs as administrator; Windows blocks input from Monkey
    VERIFY_FAILED = "verify_failed"       # the expected state wasn't there afterwards
    INTERNAL = "internal"


# What the loop may try for each error, in order, before asking a model or the user. "alt_backend" = the router's
# next choice for that op; "reobserve" = fresh observation + find the target again by role/name/automation id.
RECOVERY: dict[ErrorKind, tuple[str, ...]] = {
    ErrorKind.NOT_FOUND: ("reobserve", "scroll_into_view", "alt_backend"),
    ErrorKind.STALE: ("reobserve",),
    ErrorKind.NOT_INTERACTABLE: ("wait_enabled", "reobserve"),
    ErrorKind.COVERED: ("dismiss_overlay", "wait"),
    ErrorKind.TIMEOUT: ("wait_longer", "reload"),
    ErrorKind.SESSION_LOST: ("reacquire",),
    ErrorKind.NO_EFFECT: ("wait_change", "alt_backend"),
    ErrorKind.UNSUPPORTED: ("alt_backend",),
    ErrorKind.WRONG_WINDOW: ("refocus",),
    ErrorKind.USER_ACTIVE: ("wait_idle",),
    ErrorKind.VERIFY_FAILED: ("reobserve",),
    ErrorKind.REFUSED: (), ErrorKind.NEEDS_APPROVAL: ("ask_user",), ErrorKind.NEEDS_USER: ("ask_user",),
    ErrorKind.DUPLICATE: (), ErrorKind.INTERNAL: (),
    ErrorKind.AMBIGUOUS: ("reobserve",), ErrorKind.NEEDS_FOREGROUND: ("ask_user",),
    ErrorKind.UNRESPONSIVE: ("wait_longer",), ErrorKind.ELEVATED: (),
}


class DriverError(Exception):
    def __init__(self, kind: ErrorKind, detail: str = ""):
        super().__init__(detail or kind.value)
        self.kind = kind
        self.detail = detail or kind.value


@dataclass
class ElementRef:
    """One control, as any backend sees it. `id` is opaque to the planner ("b1:f1e4", "w1:42.7.3", "v1:3")."""
    id: str
    backend: str                      # browser | uia | visual
    session: str                      # which browser tab / window / capture it belongs to
    ref: str                          # the backend's own handle (aria ref, UIA runtime id, grounding index)
    role: str = ""
    name: str = ""
    automation_id: str = ""
    box: Box | None = None
    enabled: bool = True
    checked: bool | None = None
    value: str = ""                   # never filled for sensitive fields
    sensitive: bool = False
    in_question: bool = False
    input_type: str = ""
    href: str = ""
    native: object = field(default=None, repr=False, compare=False)   # the backend's live object (not persisted)

    def target(self) -> Target:
        return Target(role=self.role, name=self.name, input_type=self.input_type, href=self.href,
                      sensitive=self.sensitive, in_question=self.in_question, disabled=not self.enabled)

    def public(self) -> dict:
        return {"id": self.id, "backend": self.backend, "role": self.role, "name": self.name[:120],
                "enabled": self.enabled, "checked": self.checked}


@dataclass
class View:
    """One observation of one session: what a planner (or a deterministic skill) reasons over."""
    backend: str
    session: str
    title: str = ""
    location: str = ""                # URL for a page, "process.exe" for a window
    elements: list[ElementRef] = field(default_factory=list)
    text: str = ""
    signature: str = ""
    ts: float = field(default_factory=time.time)
    extra: dict = field(default_factory=dict)

    def get(self, el_id: str) -> ElementRef | None:
        return next((e for e in self.elements if e.id == el_id), None)

    def outline(self, limit: int = 4000) -> str:
        """Compact, model-facing: interactive controls with ids. Sensitive values are never included."""
        lines = []
        for e in self.elements:
            if not (e.role and (e.name or e.role in ("textbox", "edit", "combobox", "document"))):
                continue
            flags = []
            if not e.enabled:
                flags.append("disabled")
            if e.checked is not None:
                flags.append("checked" if e.checked else "unchecked")
            if e.value and not e.sensitive:
                flags.append(f'value="{e.value[:40]}"')
            lines.append(f'- {e.role} "{e.name[:80]}"{" [" + ", ".join(flags) + "]" if flags else ""} [id={e.id}]')
        out = "\n".join(lines)
        return out[:limit]


def signature_of(*parts: str) -> str:
    return hashlib.sha1("\n".join(parts).encode("utf-8", "ignore")).hexdigest()[:16]


@dataclass
class Outcome:
    op: str
    backend: str = ""
    target_id: str = ""
    accepted: bool = False
    executed: bool = False
    changed: bool | None = None       # None = not checked (reads, waits)
    verified: bool | None = None      # None = no expectation given
    error: ErrorKind | None = None
    detail: str = ""
    risk: str = ""
    ms: int = 0
    before: str = ""
    after: str = ""
    evidence: dict = field(default_factory=dict)
    recovered_by: str = ""

    @property
    def ok(self) -> bool:
        return self.executed and self.error is None and self.verified is not False

    @property
    def stage(self) -> str:
        if not self.accepted:
            return "refused"
        if not self.executed:
            return "failed"
        if self.verified:
            return "verified"
        if self.changed:
            return "changed"
        return "executed"

    def public(self) -> dict:
        d = asdict(self)
        d["error"] = self.error.value if self.error else None
        d["stage"] = self.stage
        return d


@dataclass(frozen=True)
class Capability:
    """What a backend can do, so the router can choose per step (and the docs can say why)."""
    name: str
    os: tuple[str, ...]
    app_types: tuple[str, ...]        # web | native | any
    semantic: bool                    # reads controls by role/name (accessibility tree / DOM)
    dom: bool                         # page structure, frames, form values
    visual: bool                      # works from pixels
    needs_foreground: bool            # must the window be in front / move the real mouse?
    background_ok: bool               # can act while the user works in another window
    coord_space: Space
    upload: bool
    download: bool
    cost: str                         # free | model
    typical_ms: int                   # per action, measured where the bench measured it (see docs)
    recovery: tuple[str, ...] = ()
    notes: str = ""

    def public(self) -> dict:
        d = asdict(self)
        d["coord_space"] = self.coord_space.value
        return d

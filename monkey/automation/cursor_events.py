"""Banana cursor: the event interface the executors call, and where each kind of pointer is drawn.

Three different things, never mixed up:
  1. Browser automation pointer (implemented). Playwright clicks inside Monkey's own browser without moving the
     Windows mouse. So the banana is drawn *inside that browser's viewport* (a click-through layer in a closed shadow
     root) at the same viewport coordinate Playwright clicks. It is never presented as the physical mouse.
  2. Physical desktop pointer (Windows overlay, cursor_native.py). Only when a desktop action really moves the OS
     mouse (UI Automation's click_input fallback). The banana is drawn beside the real pointer, at the same screen
     pixel; the system cursor is never hidden or replaced.
  3. Presentation only: UI Automation "invoke" activates a control without any pointer. The banana may point at the
     control it activated (its centre), but no physical pointer movement is implied.

The cursor is feedback, not control: it never decides, delays more than the short travel time, or changes where a
click lands. If drawing fails, the action still runs.

Coordinate spaces (CursorSpace):
  viewport  CSS pixels of the managed browser's viewport (what Playwright's mouse uses). Browser zoom, page zoom,
            device-pixel ratio and scrolling don't matter: the click and the banana are both in this space.
  screen    physical pixels on the Windows virtual desktop (per-monitor DPI aware; negative on left/upper monitors).
            desktop.ScreenMap converts a resized model screenshot to this space; logical_to_physical handles APIs that
            report DPI-unaware coordinates.
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("monkey.automation")
CURSOR_DIR = Path(__file__).resolve().parent / "cursor"
INTERACTIVE = {"button", "link", "textbox", "checkbox", "radio", "combobox", "menuitem", "tab", "slider", "switch",
               "option", "searchbox", "spinbutton", "treeitem", "menuitemcheckbox", "menuitemradio", "listbox",
               "edit", "hyperlink"}


def travel_ms(dist: float, motion: str = "full") -> int:
    """Same formula as banana_cursor.js travelMs: short hops feel snappy, long ones ease; never above 260 ms."""
    if motion in ("reduced", "off"):
        return 0
    return int(round(min(260, max(70, 70 + math.sqrt(max(dist, 0)) * 7))))


@dataclass
class CursorSettings:
    mode: str = "control"          # off | control (shown only while Monkey is controlling something)
    scale: float = 1.0
    glow: float = 0.7
    motion: str = "auto"           # auto (follows Windows animation settings) | full | reduced
    click_fx: bool = True
    busy_fx: bool = True

    @classmethod
    def from_app(cls, s) -> "CursorSettings":
        return cls(getattr(s, "cursor_mode", "control"), float(getattr(s, "cursor_scale", 1.0)),
                   float(getattr(s, "cursor_glow", 0.7)), getattr(s, "cursor_motion", "auto"),
                   bool(getattr(s, "cursor_click_fx", True)), bool(getattr(s, "cursor_busy_fx", True)))

    def js(self) -> dict:
        return {"scale": self.scale, "glow": self.glow, "motion": self.motion, "clickFx": self.click_fx,
                "busyFx": self.busy_fx}


def manifest() -> dict:
    return json.loads((CURSOR_DIR / "manifest.json").read_text(encoding="utf-8"))


def init_script(settings: CursorSettings) -> str:
    """The script injected into every page of Monkey's browser (top frame only)."""
    m = manifest()
    data = {"svg": (CURSOR_DIR / "banana.svg").read_text(encoding="utf-8"), "hotspot": m["hotspot"],
            "config": settings.js(), "sprite": None}
    sp = m.get("sprite")
    if sp and (CURSOR_DIR / sp["file"]).exists():          # an approved, extracted base sprite replaces the vector
        import base64

        data["sprite"] = {**sp, "src": "data:image/png;base64," +
                          base64.b64encode((CURSOR_DIR / sp["file"]).read_bytes()).decode()}
    return f"window.__MONKEY_BANANA = {json.dumps(data)};\n" + (CURSOR_DIR / "banana_cursor.js").read_text(encoding="utf-8")


class BrowserCursor:
    """Draws the banana in the managed browser. All calls happen on the browser thread (Playwright is synchronous).

    Every method is best-effort: a page that blocks scripts or is mid-navigation just doesn't show the cursor.
    """

    space = "viewport"

    def __init__(self, settings: CursorSettings, sleep: Callable[[float], None] = time.sleep,
                 on_event: Callable[[dict], None] | None = None):
        self.settings = settings
        self.sleep = sleep
        self.on_event = on_event                 # mirrors events to Monkey's UI (companion status), if wanted
        self.page = None
        self.task_id = ""
        self.pos: tuple[float, float] | None = None
        self.last_ms = {"travel": 0, "press": 0}

    @property
    def enabled(self) -> bool:
        return self.settings.mode != "off"

    def install(self, context) -> None:
        if self.enabled:
            context.add_init_script(init_script(self.settings))

    def _call(self, method: str, *args):
        if not self.enabled or self.page is None:
            return None
        last = list(self.pos) if self.pos and method not in ("hide", "tip", "moveTo") else None
        try:
            # A new document starts with a fresh (hidden) cursor: put it back where the last page left it first.
            return self.page.evaluate(
                "([m, a, last]) => { const c = window.__monkeyCursor; if (!c) return null;"
                " if (last && c.position().x < -900) c.moveTo(last[0], last[1], {duration: 0});"
                " return c[m](...a); }", [method, list(args), last])
        except Exception:  # noqa: BLE001 - navigation in progress, closed page: drawing is optional
            return None

    def _emit(self, kind: str, **kw) -> None:
        if self.on_event is not None:
            self.on_event({"kind": kind, "task_id": self.task_id, "space": self.space, **kw})

    # ---- the interface the executor uses ---------------------------------------------------------------------------
    def move_to(self, x: float, y: float) -> int:
        """Animate the tip to (x, y) in viewport CSS px. Waits the (short) travel time so you see where it goes."""
        if not self.enabled:
            return 0
        frm = list(self.pos) if self.pos else None
        ms = self._call("moveTo", x, y, {"from": frm} if frm else {}) or 0
        self.pos = (x, y)
        self.last_ms["travel"] = int(ms)
        self._emit("move", x=x, y=y)
        if ms:
            self.sleep(ms / 1000)
        return int(ms)

    def hover(self, role: str) -> bool:
        on = bool(self._call("hover", role)) if self.enabled else False
        self._emit("hover", role=role, interactive=on)
        return on

    def press(self) -> None:
        if not self.enabled:
            return
        ms = self._call("press") or 0
        self.last_ms["press"] = int(ms)
        if ms:
            self.sleep(min(ms, 90) / 1000)       # the squash is visible before the click; never more than 90 ms

    def release(self) -> None:
        self._call("release")
        self._emit("click", x=self.pos[0] if self.pos else None, y=self.pos[1] if self.pos else None)

    def drag_to(self, x: float, y: float) -> int:
        ms = self._call("dragTo", x, y) or 0
        self.pos = (x, y)
        return int(ms)

    def set_state(self, state: str, label: str = "") -> None:
        """busy | thinking | typing | waiting | paused | blocked | error | success | idle"""
        self._call("setState", state, label)
        self._emit("state", state=state)

    def hide(self) -> None:
        self._call("hide")
        self._emit("hide")

    def tip(self) -> dict | None:
        return self._call("tip")

    def reset_page(self) -> None:
        """A new document has its own (fresh) cursor: start it where the last one was."""
        if self.pos is not None:
            self._call("moveTo", self.pos[0], self.pos[1], {"duration": 0})


TASK_STATE_CURSOR = {"RUNNING": "idle", "WAITING": "busy", "VERIFYING": "thinking", "NEEDS_INPUT": "waiting",
                     "PAUSED": "paused", "BLOCKED": "blocked", "FAILED": "error", "COMPLETED": "success"}

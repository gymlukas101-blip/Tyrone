"""Capability-aware routing: which backend runs this step.

Order (a starting rule, adjusted by evidence collected during the task):
  1. the backend that owns the target (refs are backend-specific);
  2. a native dialog in scope (file picker, message box) goes to the Windows backend;
  3. semantic backends before pixels: browser (DOM + accessibility) for web, UIA for native windows;
  4. visual grounding last, only if the user allowed screenshots for this task, only for pointer ops.
A backend that failed the same op twice in this task is demoted to the end (and the switch is traced).
"""
from __future__ import annotations

from collections import Counter

from .model import Capability, ElementRef

POINTER_OPS = {"click", "double_click", "hover", "drag"}
WEB_OPS = {"navigate"}
NATIVE_OPS = {"choose_file", "select_window", "list_windows"}


class Router:
    def __init__(self, capabilities: dict[str, Capability], allow_visual: bool = False):
        self.caps = capabilities
        self.allow_visual = allow_visual
        self.failures: Counter = Counter()
        self.current: str = ""

    def available(self) -> list[str]:
        return [n for n in ("browser", "uia", "visual") if n in self.caps
                and (n != "visual" or self.allow_visual)]

    def order(self, op: str, el: ElementRef | None = None, *, dialog_open: bool = False,
              prefer: str = "") -> list[str]:
        avail = self.available()
        if op in WEB_OPS:
            out = [b for b in ("browser",) if b in avail]
        elif op in NATIVE_OPS:
            out = [b for b in ("uia",) if b in avail]
        elif el is not None:
            out = [el.backend] if el.backend in avail else []
            if op in POINTER_OPS and "visual" in avail and el.backend != "visual":
                out.append("visual")        # same control, found again from pixels if its backend can't act on it
        else:
            first = "uia" if dialog_open and "uia" in avail else (prefer or self.current)
            sem = [b for b in ("browser", "uia") if b in avail]
            out = ([first] if first in sem else []) + [b for b in sem if b != first]
            if op in POINTER_OPS and "visual" in avail:
                out.append("visual")
        # demote backends that keep failing this op
        out.sort(key=lambda b: self.failures[(b, op)] >= 2)
        return out

    def record(self, backend: str, op: str, ok: bool) -> None:
        if ok:
            self.failures[(backend, op)] = 0
        else:
            self.failures[(backend, op)] += 1

    def describe(self) -> list[dict]:
        return [self.caps[n].public() for n in self.available()]

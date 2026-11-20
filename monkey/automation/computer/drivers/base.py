"""The backend interface. Drivers do no permission checks and no tracing: the Computer facade does both, uniformly,
before and after every call, so a new backend can't forget them."""
from __future__ import annotations

from typing import Callable

from ..model import Capability, DriverError, ElementRef, ErrorKind, View

OPS = ("observe", "navigate", "click", "double_click", "hover", "type_text", "press_key", "scroll", "drag",
       "select_option", "upload_file", "get_element_state", "wait_for", "capture_screenshot")


class Driver:
    name = "base"
    capability: Capability
    session_id = ""

    def alive(self) -> bool:
        return True

    def observe(self) -> View:
        raise DriverError(ErrorKind.UNSUPPORTED, f"{self.name} can't observe")

    def signature(self) -> str:
        """Cheap state fingerprint used to detect change and duplicate actions."""
        return self.observe().signature

    def refind(self, el: ElementRef) -> ElementRef:
        """The same control after a re-render, by what it is (role + name + automation id), never by position."""
        v = self.observe()
        for cand in v.elements:
            if cand.role == el.role and cand.name == el.name and (not el.automation_id
                                                                   or cand.automation_id == el.automation_id):
                return cand
        raise DriverError(ErrorKind.NOT_FOUND, f"{el.role} '{el.name[:40]}' isn't there any more")

    def perform(self, op: str, el: ElementRef | None, args: dict) -> dict:
        """Do it; return evidence (e.g. {"x", "y", "space"} of the click). Raise DriverError on failure."""
        raise DriverError(ErrorKind.UNSUPPORTED, f"{self.name} can't {op}")

    def element_state(self, el: ElementRef) -> dict:
        raise DriverError(ErrorKind.UNSUPPORTED, f"{self.name} can't read element state")

    def wait_for(self, cond: dict, timeout_s: float, should_stop: Callable[[], bool]) -> bool:
        raise DriverError(ErrorKind.UNSUPPORTED, f"{self.name} can't wait for {cond.get('kind')}")

    def capture(self):
        """(PIL.Image, ImageMap-able source box) or raise UNSUPPORTED."""
        raise DriverError(ErrorKind.UNSUPPORTED, f"{self.name} can't capture")

    def close(self) -> None:
        pass

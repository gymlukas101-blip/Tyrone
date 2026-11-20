"""A stand-in Windows app for non-Windows tests: Notepad-like editor + a modal Save As dialog that really writes the
file. It implements the same Driver interface as UIADriver, so the Computer/GoalRunner code paths are the real ones."""
from __future__ import annotations

import time
from pathlib import Path

from monkey.automation.computer.drivers.base import Driver
from monkey.automation.computer.drivers.uia import CAPABILITY
from monkey.automation.computer.model import DriverError, ElementRef, ErrorKind, View, signature_of


class _Scope:
    def __init__(self, app):
        self.app = app

    def dialogs(self):
        return [2] if self.app.dialog else []


class FakeNotepad(Driver):
    name = "uia"
    capability = CAPABILITY

    def __init__(self):
        self.session_id = "w1"
        self.text = ""
        self.dialog = False
        self.saved_to: Path | None = None
        self.scope = _Scope(self)
        self.alive_ = True
        self.physical_presses = 0

    def alive(self):
        return self.alive_

    def file_dialog(self):
        return 2 if self.dialog else 0

    def dialog_process(self):
        return "notepad.exe" if self.dialog else ""

    def observe(self) -> View:
        if not self.alive_:
            raise DriverError(ErrorKind.SESSION_LOST, "closed")
        if self.dialog:
            els = [ElementRef("w1:d0#0", "uia", "w1@2", "d0#0", "textbox", "File name:", "1001"),
                   ElementRef("w1:d1#0", "uia", "w1@2", "d1#0", "button", "Save", "1")]
            return View("uia", "w1@2", "Save As", "#32770", els, signature=signature_of("dialog"),
                        extra={"dialog": True})
        els = [ElementRef("w1:0#0", "uia", "w1@1", "0#0", "textbox", "Text Editor", "15", value=self.text),
               ElementRef("w1:1#0", "uia", "w1@1", "1#0", "menuitem", "File")]
        return View("uia", "w1@1", (self.saved_to.name if self.saved_to else "Untitled") + " - Notepad", "Notepad",
                    els, signature=signature_of("app", self.text, str(self.saved_to)), extra={"dialog": False})

    def signature(self):
        return self.observe().signature

    def refind(self, el):
        for e in self.observe().elements:
            if e.role == el.role and e.name == el.name:
                return e
        raise DriverError(ErrorKind.STALE, "gone")

    def element_state(self, el):
        return {"enabled": True, "value": self.text if el.name == "Text Editor" else "", "checked": None}

    def perform(self, op, el, args):
        if op == "type_text" and el is not None and el.name == "Text Editor" and not self.dialog:
            self.text = args.get("text", "")
            return {"via": "value_pattern", "physical": False}
        if op == "press_key" and args.get("keys", "").lower() in ("control+s", "ctrl+s"):
            self.physical_presses += 1
            self.dialog = True
            return {"physical": True}
        if op == "upload_file" or op == "choose_file":
            if not self.dialog:
                raise DriverError(ErrorKind.NOT_FOUND, "no file picker is open")
            p = Path(str(args["path"]))
            p.write_text(self.text, "utf-8")
            self.saved_to, self.dialog = p, False
            return {"via": "file_dialog/value_pattern", "dialog_closed": True}
        raise DriverError(ErrorKind.UNSUPPORTED, f"fake can't {op}")

    def wait_for(self, cond, timeout_s, should_stop):
        k = cond.get("kind")
        end = time.time() + timeout_s
        while time.time() < end:
            if k == "file_dialog" and self.dialog or k == "dialog_gone" and not self.dialog:
                return True
            if k == "change" and self.signature() != cond.get("since"):
                return True
            if k == "time":
                time.sleep(min(timeout_s, float(cond.get("seconds", 1))))
                return True
            time.sleep(0.05)
        return False

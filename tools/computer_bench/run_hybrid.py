"""Hybrid workflow: browser → native app (+ its Save As dialog) → browser, in one task, without losing state.

    1. Monkey's browser shows a confirmation code (and an upload form).
    2. Monkey switches to Notepad (an app the user allowed), types the code, presses Ctrl+S, and fills the native
       Save As dialog with the task's file path.
    3. Back in the browser, it attaches that saved file (approval) and sends it (approval); the server must
       receive a file that contains the code.

On Windows this drives the real Notepad and the real common file dialog through UI Automation. Elsewhere
(--simulate) a scripted stand-in app exercises the same orchestration (driver switching, dialog routing,
checkpoints, approvals); the result says which one ran.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from monkey.automation.browser import BrowserSession
from monkey.automation.computer import Computer, Trace
from monkey.automation.computer.drivers.browser import BrowserDriver
from monkey.automation.computer.goal import GoalRunner, Plan
from monkey.automation.permissions import PermissionGate

from . import fixtures as fx
from .harness import BenchHost, C, ScriptedPlanner, new_task

CODE = "MKY-4471"


def script(note: Path) -> list:
    def editor_id(v):
        return next((e.id for e in v.elements if e.role == "textbox"), "")

    in_app = lambda v: v.backend == "uia" and not v.extra.get("dialog")  # noqa: E731
    return [
        (lambda v, r: v.backend == "browser" and f"Received {note.name}" in v.text,
         Plan(status="done", message="sent", evidence=f"Received {note.name}")),
        (lambda v, r: note.is_file() and CODE in note.read_text("utf-8", "ignore"),
         Plan(calls=[C("upload_file", "Note file", path=str(note)), C("click", "Send note", "button"),
                     C("wait_for", kind="text", text=f"Received {note.name}", timeout_s=8, backend="browser")],
              subgoal="Upload the saved note")),
        (lambda v, r: v.backend == "uia" and v.extra.get("dialog"),
         Plan(calls=[C("choose_file", path=str(note))], subgoal="Save it as the task's file")),
        (lambda v, r: in_app(v) and any(CODE in (e.value or "") for e in v.elements),
         Plan(calls=[C("press_key", keys="Control+S"), C("wait_for", kind="file_dialog", timeout_s=8)],
              subgoal="Open Save As")),
        (lambda v, r: in_app(v),
         lambda v: Plan(calls=[{"name": "type_text", "input": {"id": editor_id(v),
                                                               "text": f"Confirmation code: {CODE}"}}],
                        subgoal="Write the code down")),
        (lambda v, r: v.backend == "browser" and CODE in v.text,
         Plan(calls=[C("select_window", process="notepad.exe")], subgoal="Switch to Notepad")),
    ]


class Notepad:
    def __init__(self):
        self.proc = None

    def start(self) -> int:
        from monkey.automation.desktop import list_windows

        self.proc = subprocess.Popen(["notepad.exe"])
        end = time.time() + 20
        while time.time() < end:
            h = next((w.hwnd for w in list_windows() if w.process.lower() == "notepad.exe"), 0)
            if h:
                return h
            time.sleep(0.3)
        raise RuntimeError("Notepad didn't open")

    def stop(self):
        if self.proc:
            self.proc.kill()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulate", action="store_true", help="scripted stand-in for Notepad (non-Windows)")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    simulate = a.simulate or sys.platform != "win32"
    fx.S.reset()
    srv, port = fx.serve()
    res: dict = {"mode": "simulated desktop app" if simulate else "real Windows: Notepad + common Save As dialog",
                 "platform": f"{platform.system()} {platform.release()}"}
    np_ = Notepad()
    with tempfile.TemporaryDirectory() as d:
        note = Path(d) / "code-note.txt"
        gate = PermissionGate()
        task = new_task(fx.FIXTURES["hybrid"]["goal"], f"http://127.0.0.1:{port}/f/hybrid", files=[str(note)],
                        apps=["notepad.exe"], allow_physical=True)
        from tools.automation_eval import browser_path

        sess = BrowserSession(Path(d) / "profile", gate, headless=True,
                              channel="msedge" if sys.platform == "win32" and not browser_path() else None,
                              executable_path=browser_path(), allowed_domains=task.allowed_domains)
        sess.start()
        hwnd = 0 if simulate else np_.start()

        def open_driver(kind, **kw):
            if kind != "uia":
                return None
            if simulate:
                from tests.fakes_desktop import FakeNotepad

                return FakeNotepad()
            from monkey.automation.computer.drivers.uia import UIADriver

            return UIADriver(hwnd, allow_physical=True)

        host = BenchHost(gate, approve=(r"send the file code-note\.txt", r'click button "Send note"'),
                         open_driver=open_driver)
        host.timeout_s = 180
        trace = Trace(task.id)
        comp = Computer(task, gate, {"browser": BrowserDriver(sess)}, trace, should_stop=host.should_stop,
                        save=lambda: host.save(task))
        t0 = time.time()
        try:
            comp.do("navigate", None, url=task.start_url)
            state = GoalRunner(task, comp, ScriptedPlanner(script(note)), host).run()
            ok = bool(fx.FIXTURES["hybrid"]["check"]())
            res.update(success=ok, runner_state=state, task_state=task.state.value, seconds=round(time.time() - t0, 2),
                       file_saved=note.is_file(), approvals=host.approvals, **trace.metrics(),
                       switches=[{k: e.get(k) for k in ("from", "to", "why")} for e in trace.events
                                 if e["ev"] == "DRIVER_SWITCHED"],
                       checkpoints=[c["note"] for c in task.checkpoints if c["step"] == "op"])
        finally:
            sess.close()
            np_.stop()
            srv.shutdown()
    print(json.dumps(res, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1))
    return 0 if res.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())

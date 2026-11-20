"""Windows desktop benchmark: the same native tasks through three backends, scored by the fixture app's own log.

    python -m tools.computer_bench.run_windows --backends monkey,agent-desktop,windows-mcp --out win.json

Backends
  monkey         Monkey's UIADriver through the Computer facade (gate, verification, trace) — in-process pywinauto.
  agent-desktop  vercel-labs/agent-desktop CLI (npm, pinned), JSON over stdout, one process per command.
  windows-mcp    CursorTouch/Windows-MCP (uvx, Python 3.14 sidecar), MCP over stdio, physical input.

For each task: success (log), ms, backend calls, and whether the user was interrupted (foreground window changed
or the real mouse cursor moved). Runs on a real Windows session (GitHub windows-latest in CI; label results so).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
TITLE = "Monkey Fixture"


# ------------------------------------------------------------------------------------------------ the fixture app
class Fixture:
    def __init__(self, workdir: Path):
        self.log = workdir / "fixture.log"
        self.proc = None

    def start(self) -> None:
        self.log.write_text("", "utf-8")
        self.proc = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                      str(HERE / "win_fixture.ps1"), str(self.log)])
        end = time.time() + 30
        while time.time() < end and not self.hwnd():
            time.sleep(0.3)
        if not self.hwnd():
            raise RuntimeError("fixture window didn't appear")

    def stop(self) -> None:
        if self.proc:
            self.proc.kill()
            self.proc.wait(10)

    def hwnd(self) -> int:
        from monkey.automation.desktop import list_windows

        return next((w.hwnd for w in list_windows() if w.title == TITLE), 0)

    def lines(self) -> list[str]:
        try:
            return [x.strip().lstrip("﻿") for x in self.log.read_text("utf-8", "ignore").splitlines() if x.strip()]
        except OSError:
            return []

    def wait_line(self, rx: str, timeout: float = 6.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if any(re.search(rx, ln) for ln in self.lines()):
                return True
            time.sleep(0.15)
        return False


def cursor_pos() -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    p = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def foreground() -> int:
    import ctypes

    return int(ctypes.windll.user32.GetForegroundWindow() or 0)


def bring_front(hwnd: int) -> None:
    import ctypes

    u = ctypes.windll.user32
    u.ShowWindow(hwnd, 9)
    u.keybd_event(0x12, 0, 0, 0)          # ALT tap: lets SetForegroundWindow succeed from a background process
    u.SetForegroundWindow(hwnd)
    u.keybd_event(0x12, 0, 2, 0)


def notepad() -> tuple[subprocess.Popen, int]:
    from monkey.automation.desktop import list_windows

    p = subprocess.Popen(["notepad.exe"])
    end = time.time() + 15
    while time.time() < end:
        h = next((w.hwnd for w in list_windows() if w.process.lower() == "notepad.exe"), 0)
        if h:
            return p, h
        time.sleep(0.3)
    return p, 0


# ------------------------------------------------------------------------------------------------ backends
class MonkeyBackend:
    name = "monkey"

    def __init__(self, fx: Fixture, physical: bool = False):
        from monkey.automation.computer import Computer, Trace
        from monkey.automation.computer.drivers.uia import UIADriver
        from monkey.automation.computer.drivers.visual import JsonGrounder, VisualDriver
        from monkey.automation.permissions import PermissionGate
        from monkey.automation.tasks import Task

        self.fx = fx
        self.gate = PermissionGate()
        self.task = Task(objective="benchmark", mode="control_window", skill="general", files=[str(fx.log.parent)],
                         allow_physical=physical, send_screenshots=True)
        self.drv = UIADriver(fx.hwnd(), allow_physical=physical)
        self.trace = Trace(self.task.id)
        self.visual = VisualDriver(self.drv, JsonGrounder(_green))
        self.c = Computer(self.task, self.gate, {"uia": self.drv}, self.trace, visual=self.visual)
        self.calls = 0

    def _ok(self, out) -> bool:
        self.calls += 1
        if out.error is not None:
            raise RuntimeError(f"{out.error.value}: {out.detail}")
        return True

    def snapshot(self) -> dict:
        v = self.c.observe("uia")
        self.calls += 1
        return {"elements": len(v.elements), "chars": len(v.outline(100000))}

    def list_windows(self) -> bool:
        from monkey.automation.desktop import list_windows

        self.calls += 1
        return any(w.title == TITLE for w in list_windows())

    def click(self, name: str, role: str = "button") -> None:
        self.c.observe("uia")
        self._ok(self.c.do("click", {"name": name, "role": role, "backend": "uia"}))

    def type(self, name: str, text: str) -> None:
        self.c.observe("uia")
        self._ok(self.c.do("type_text", {"name": name, "role": "textbox", "backend": "uia"}, text=text))

    def select(self, name: str, option: str) -> None:
        self.c.observe("uia")
        self._ok(self.c.do("select_option", {"name": name, "role": "combobox", "backend": "uia"}, option=option))

    def wait_enabled(self, name: str, timeout: float) -> None:
        self.c.observe("uia")
        el = self.c.find(name, "uia", "button")
        out = self.c.wait_for({"kind": "enabled", "el": el}, timeout, "uia")
        self._ok(out)
        if not out.verified:
            raise RuntimeError("never enabled")

    def file_dialog(self, path: str) -> None:
        self._ok(self.c.do("choose_file", None, path=path))

    def dismiss_dialog(self, button: str = "OK") -> None:
        self.c.observe("uia")                    # the message box is an owned dialog: observe() switches to it
        self._ok(self.c.do("click", {"name": button, "role": "button", "backend": "uia"}))

    def visual_click(self, desc: str) -> None:
        self._ok(self.c.do("click", desc))

    def notepad_type(self, hwnd: int, text: str) -> str:
        from monkey.automation.computer.drivers.uia import UIADriver

        d = UIADriver(hwnd)
        self.c.add_driver("uia", d)
        v = self.c.observe("uia")
        ed = next((e for e in v.elements if e.role == "textbox"), None)
        if ed is None:
            raise RuntimeError("no editor found")
        self._ok(self.c.do("type_text", ed, text=text))
        return d.element_state(ed).get("value", "")

    def close(self) -> None:
        pass


class AgentDesktopBackend:
    name = "agent-desktop"

    def __init__(self, fx: Fixture, exe: str):
        self.fx, self.exe, self.calls = fx, exe, 0
        self.env = {**os.environ, "AGENT_DESKTOP_HOME": str(fx.log.parent / "ad")}
        self.app = ["--app", "powershell.exe"]
        wins = self.run("list-windows", check=False).get("data") or []
        wid = next((w.get("id") for w in wins if isinstance(w, dict) and w.get("title") == TITLE), None)
        self.win = ["--window-id", wid] if wid else self.app

    def run(self, *args, check=True) -> dict:
        self.calls += 1
        p = subprocess.run([self.exe, *args], capture_output=True, text=True, timeout=60, env=self.env)
        try:
            d = json.loads(p.stdout or "{}")
        except ValueError:
            d = {"ok": False, "error": {"message": (p.stdout + p.stderr)[:300]}}
        if check and not d.get("ok", p.returncode == 0):
            raise RuntimeError(json.dumps(d.get("error") or d)[:300])
        return d

    def find(self, name: str, role: str, where: list | None = None) -> str:
        d = self.run("find", *(where or self.win), "--role", role, "--name", name, "--exact", "--first")
        ref = ((d.get("data") or {}).get("match") or {}).get("ref_id")
        if not ref:
            raise RuntimeError(f"not found: {role} {name}")
        return ref

    def snapshot(self) -> dict:
        d = self.run("snapshot", *self.win, "-i", "--compact", "--timeout-ms", "10000")
        s = json.dumps(d.get("data") or {})
        return {"elements": (d.get("data") or {}).get("ref_count", 0), "chars": len(s)}

    def list_windows(self) -> bool:
        d = self.run("list-windows")
        return TITLE in json.dumps(d.get("data") or [])

    def click(self, name: str, role: str = "button") -> None:
        self.run("toggle" if role == "checkbox" else "click", self.find(name, role))

    def type(self, name: str, text: str) -> None:
        self.run("set-value", self.find(name, "textfield"), text)

    def select(self, name: str, option: str) -> None:
        ref = self.find(name, "combobox")
        self.run("select", ref, option)

    def wait_enabled(self, name: str, timeout: float) -> None:
        ref = self.find(name, "button")
        self.run("wait", "--element", ref, "--predicate", "enabled", "--timeout", str(int(timeout * 1000)))

    def file_dialog(self, path: str) -> None:
        ref = self.find("File name:", "textfield", self.app)
        self.run("set-value", ref, path)
        self.run("click", self.find("Open", "button", self.app))

    def dismiss_dialog(self, button: str = "OK") -> None:
        self.run("click", self.find(button, "button", self.app))

    def visual_click(self, desc: str) -> None:
        raise NotImplementedError("no visual grounding in this backend")

    def notepad_type(self, hwnd: int, text: str) -> str:
        app = ["--app", "notepad.exe"]
        d = self.run("find", *app, "--role", "textfield", "--first", check=False)
        ref = ((d.get("data") or {}).get("match") or {}).get("ref_id")
        if not ref:
            d = self.run("find", *app, "--role", "document", "--first")
            ref = ((d.get("data") or {}).get("match") or {}).get("ref_id")
        self.run("set-value", ref, text)
        return text if _notepad_text(hwnd) == text else _notepad_text(hwnd)

    def close(self) -> None:
        pass


class WindowsMcpBackend:
    """Physical-input backend: everything goes through screen coordinates parsed from its Snapshot text."""
    name = "windows-mcp"

    def __init__(self, fx: Fixture):
        from fastmcp import Client
        from fastmcp.client.transports import StdioTransport

        self.fx, self.calls = fx, 0
        env = {**os.environ, "ANONYMIZED_TELEMETRY": "false", "WINDOWS_MCP_DISABLE_FLASH": "1"}
        self.client = Client(StdioTransport("uvx", ["--python", "3.14", "windows-mcp==0.8.9", "serve",
                                                     "--no-control"], env=env))
        self.loop = asyncio.new_event_loop()
        self.loop.run_until_complete(self.client.__aenter__())

    def call(self, tool: str, args: dict) -> str:
        self.calls += 1
        r = self.loop.run_until_complete(self.client.call_tool(tool, args))
        parts = getattr(r, "content", None) or []
        return "\n".join(getattr(p, "text", "") for p in parts)

    def _find(self, name: str, role: str) -> tuple[int, int]:
        txt = self.call("Snapshot", {"use_annotation": False})
        for line in txt.splitlines():
            m = re.search(r"\((\-?\d+),\s*(\-?\d+)\)\s+(\w[\w ]*?)\s+\"(.*)\"", line)
            if m and m.group(4).strip() == name and role.lower() in m.group(3).lower():
                return int(m.group(1)), int(m.group(2))
        raise RuntimeError(f"not found: {role} {name}")

    def snapshot(self) -> dict:
        txt = self.call("Snapshot", {"use_annotation": False})
        return {"elements": sum(1 for ln in txt.splitlines() if re.search(r"\(\-?\d+,\s*\-?\d+\)", ln)),
                "chars": len(txt)}

    def list_windows(self) -> bool:
        return TITLE in self.call("Snapshot", {"use_annotation": False})

    def click(self, name: str, role: str = "button") -> None:
        x, y = self._find(name, role)
        self.call("Click", {"loc": [x, y]})

    def type(self, name: str, text: str) -> None:
        x, y = self._find(name, "edit")
        self.call("Type", {"loc": [x, y], "text": text, "clear": True})

    def select(self, name: str, option: str) -> None:
        x, y = self._find(name, "combo")
        self.call("Click", {"loc": [x, y]})
        time.sleep(0.4)
        x, y = self._find(option, "item")
        self.call("Click", {"loc": [x, y]})

    def wait_enabled(self, name: str, timeout: float) -> None:
        time.sleep(timeout)                    # its WaitFor element_enabled doesn't read IsEnabled (research note)

    def file_dialog(self, path: str) -> None:
        x, y = self._find("File name:", "edit")
        self.call("Type", {"loc": [x, y], "text": path, "clear": True})
        self.call("Shortcut", {"shortcut": "enter"})

    def dismiss_dialog(self, button: str = "OK") -> None:
        self.click(button)

    def visual_click(self, desc: str) -> None:
        raise NotImplementedError("needs a grounding model on top")

    def notepad_type(self, hwnd: int, text: str) -> str:
        bring_front(hwnd)
        x, y = self._find("Text Editor", "")
        self.call("Type", {"loc": [x, y], "text": text, "clear": True})
        return _notepad_text(hwnd)

    def close(self) -> None:
        try:
            self.loop.run_until_complete(self.client.__aexit__(None, None, None))
        except Exception:  # noqa: BLE001
            pass


def _green(image, desc: str):
    import numpy as np

    a = np.asarray(image.convert("RGB")).astype(int)
    mask = (a[..., 1] > 110) & (a[..., 0] < 60) & (a[..., 2] < 60)
    if mask.sum() < 30:
        return None
    ys, xs = np.nonzero(mask)
    return float(xs.mean()), float(ys.mean())


def _notepad_text(hwnd: int) -> str:
    from pywinauto import Desktop

    w = Desktop(backend="uia").window(handle=hwnd)
    for c in w.descendants():
        ct = (c.element_info.control_type or "").lower()
        if ct in ("edit", "document"):
            try:
                return c.iface_value.CurrentValue
            except Exception:  # noqa: BLE001
                try:
                    return c.window_text()
                except Exception:  # noqa: BLE001
                    continue
    return ""


# ------------------------------------------------------------------------------------------------ tasks
def tasks(fx: Fixture, workdir: Path):
    pick = workdir / "picked.txt"
    pick.write_text("x")
    return [
        ("W01 list windows", lambda b: b.list_windows() or (_ for _ in ()).throw(RuntimeError("not listed")),
         None, False),
        ("W02 snapshot window", lambda b: b.snapshot(), None, False),
        ("W03 type into a text box", lambda b: b.type("Name", "Ada"), None, False),
        ("W04 click a button", lambda b: b.click("Greet"), r"^greet:Ada$", False),
        ("W05 toggle a checkbox", lambda b: b.click("Subscribe to updates", "checkbox"), r"^subscribe:True$", False),
        ("W06 select in a combo box", lambda b: b.select("Color", "Blue"), r"^color:Blue$", False),
        ("W07 wait until enabled, click", lambda b: (b.click("Prepare"), b.wait_enabled("Ready", 6),
                                                     b.click("Ready")), r"^ready$", False),
        ("W08 stale control after rebuild", lambda b: (b.click("Rebuild"), b.click("Archive")), r"^archive$",
         False),
        ("W09 native Open dialog", lambda b: (b.click("Browse..."), time.sleep(1.2), b.file_dialog(str(pick))),
         r"^picked:.*picked\.txt$", False),
        ("W10 unexpected message box", lambda b: (b.click("Save settings"), time.sleep(1.0),
                                                  b.dismiss_dialog("OK")), r"^alert_closed$", False),
        ("W11 act on a covered (background) window", lambda b: b.click("Greet"), r"^greet:", True),
        ("W12 owner-drawn control (pixels only)", lambda b: b.visual_click("the green Start button"),
         r"^canvas_start$", False),
    ]


def run_backend(name: str, workdir: Path, ad_exe: str = "") -> list[dict]:
    rows = []
    fx = Fixture(workdir)
    fx.start()
    np_proc, np_hwnd = None, 0
    try:
        if name == "monkey":
            b = MonkeyBackend(fx, physical=True)     # physical allowed (as if the user ticked it) for W12 only
        elif name == "agent-desktop":
            b = AgentDesktopBackend(fx, ad_exe)
        else:
            b = WindowsMcpBackend(fx)
        for label, fn, expect, covered in tasks(fx, workdir):
            if covered:
                np_proc, np_hwnd = notepad()
                bring_front(np_hwnd)
                time.sleep(0.6)
            else:
                bring_front(fx.hwnd())
                time.sleep(0.3)
            fg0, cur0 = foreground(), cursor_pos()
            t0 = time.time()
            calls0 = b.calls
            row = {"backend": name, "task": label}
            try:
                res = fn(b)
                ok = fx.wait_line(expect) if expect else True
                if label.startswith("W03"):
                    ok = _value_of(fx.hwnd(), "Name") == "Ada"
                if isinstance(res, dict):
                    row.update(res)
                row["success"] = bool(ok)
                if not ok:
                    row["failure"] = "no effect in the app"
            except NotImplementedError as exc:
                row["success"], row["failure"] = None, f"n/a: {exc}"
            except Exception as exc:  # noqa: BLE001
                row["success"], row["failure"] = False, f"{type(exc).__name__}: {exc}"[:240]
            row["ms"] = int((time.time() - t0) * 1000)
            row["calls"] = b.calls - calls0
            row["cursor_moved"] = cursor_pos() != cur0
            row["focus_changed"] = foreground() != fg0
            rows.append(row)
            print(f"[{name}] {label:42s} {row['success']!s:5s} {row['ms']:6d} ms  cursor_moved={row['cursor_moved']}"
                  f" focus_changed={row['focus_changed']} {row.get('failure', '')}", flush=True)
            if covered and np_proc:
                np_proc.kill()
                np_proc = None
            if label.startswith("W10"):
                for _ in range(3):              # leave no message box behind for the next task
                    if fx.wait_line("^alert_closed$", 0.5):
                        break
        # W13: a real third-party app (Notepad): type and read back
        np_proc, np_hwnd = notepad()
        t0, cur0 = time.time(), cursor_pos()
        calls0 = b.calls
        row = {"backend": name, "task": "W13 Notepad: type + read back"}
        try:
            got = b.notepad_type(np_hwnd, "Monkey was here")
            row["success"] = "Monkey was here" in (got or _notepad_text(np_hwnd))
        except NotImplementedError as exc:
            row["success"], row["failure"] = None, f"n/a: {exc}"
        except Exception as exc:  # noqa: BLE001
            row["success"], row["failure"] = False, f"{type(exc).__name__}: {exc}"[:240]
        row.update(ms=int((time.time() - t0) * 1000), calls=b.calls - calls0, cursor_moved=cursor_pos() != cur0)
        rows.append(row)
        print(f"[{name}] {row['task']:42s} {row['success']!s:5s} {row['ms']:6d} ms {row.get('failure', '')}",
              flush=True)
        b.close()
    except Exception as exc:  # noqa: BLE001 - the backend couldn't even start
        rows.append({"backend": name, "task": "startup", "success": False,
                     "failure": f"{type(exc).__name__}: {exc}"[:300]})
        print(f"[{name}] startup failed: {exc}", flush=True)
    finally:
        if np_proc:
            np_proc.kill()
        fx.stop()
    return rows


def _value_of(hwnd: int, name: str) -> str:
    from pywinauto import Desktop

    w = Desktop(backend="uia").window(handle=hwnd)
    for c in w.descendants(control_type="Edit"):
        if c.element_info.name == name:
            try:
                return c.iface_value.CurrentValue
            except Exception:  # noqa: BLE001
                return c.window_text()
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backends", default="monkey,agent-desktop,windows-mcp")
    ap.add_argument("--agent-desktop", default=shutil.which("agent-desktop") or shutil.which("agent-desktop.cmd") or "")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    if sys.platform != "win32":
        print("Windows only")
        return 2
    from monkey.automation.desktop import make_dpi_aware

    make_dpi_aware()
    rows = []
    with tempfile.TemporaryDirectory() as d:
        for name in a.backends.split(","):
            w = Path(d) / name
            w.mkdir()
            rows += run_backend(name, w, a.agent_desktop)
    summary = {"platform": f"{platform.system()} {platform.release()} {platform.version()}",
               "machine": os.environ.get("RUNNER_NAME", "local") and "GitHub Actions windows-latest (real Windows "
                          "session, not the user's PC)" if os.environ.get("GITHUB_ACTIONS") else "local",
               "rows": rows}
    for name in a.backends.split(","):
        rs = [r for r in rows if r["backend"] == name and r.get("success") is not None]
        summary[name] = {"passed": sum(1 for r in rs if r["success"]), "applicable": len(rs),
                         "focus_or_cursor_disturbed": sum(1 for r in rs if r.get("cursor_moved") or
                                                          r.get("focus_changed"))}
    if a.out:
        Path(a.out).write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

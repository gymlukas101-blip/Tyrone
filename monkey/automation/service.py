"""What MonkeyApp owns for computer tasks: the TaskManager, the demo course, window listing, the e-stop.

Nothing here runs unless Settings → computer_access is on, and every task starts from Monkey's own permission dialog
(the chat brain can only *propose* a task; the user grants it in the UI).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from .permissions import PermissionGate, url_allowed

log = logging.getLogger("monkey.automation")


class AutomationService:
    def __init__(self, app):
        self.app = app
        self.gate = PermissionGate()
        self._mgr = None
        self.demo = None
        self._said: dict[str, str] = {}

    # ---- lazily built (Playwright is only imported when a task starts) -----------------------------------------
    @property
    def mgr(self):
        if self._mgr is None:
            from .manager import TaskManager
            from .tasks import TaskStore

            self._mgr = TaskManager(TaskStore(Path(self.app.cfg.data_dir) / "automation.db"), self.gate,
                                    self._session, emit=self._emit, planner=self._planner())
        return self._mgr

    def _planner(self):
        client = getattr(self.app, "client", None)
        if client is None:
            return None
        from ..brain.costs import Usage, cost_usd
        from .planner import ClaudePlanner

        return ClaudePlanner(client, record_usage=self.app._record_usage,
                             cost_fn=lambda model, u: cost_usd(model, Usage.from_response(u)))

    def _session(self, task):
        from .browser import BrowserSession, default_profile_dir
        from .cursor_events import BrowserCursor, CursorSettings

        cs = CursorSettings.from_app(self.app.cfg.settings)
        cursor = BrowserCursor(cs, on_event=lambda e: self.app.ui.emit("cursor", e)) if cs.mode != "off" else None
        return BrowserSession(default_profile_dir(self.app.cfg.data_dir), self.gate, headless=False, cursor=cursor)

    def _emit(self, name: str, p: dict) -> None:
        self.app.ui.emit(name, p)
        t = p.get("task") or {}
        key = f"{t.get('state')}:{(t.get('pending') or {}).get('kind', '')}"
        if self._said.get(t.get("id", "")) == key:
            return
        self._said[t.get("id", "")] = key
        line = {"COMPLETED": "Done, and I checked: the site shows it's complete.",
                "NEEDS_INPUT": "I need you for a sec.", "BLOCKED": "I'm stuck waiting on the site.",
                "FAILED": "I had to stop that task."}.get(t.get("state", ""))
        if line:
            try:
                self.app._say(line)
            except Exception:  # noqa: BLE001
                pass

    # ---- API ---------------------------------------------------------------------------------------------------
    def enabled(self) -> bool:
        return bool(self.app.cfg.settings.computer_access)

    def state(self) -> dict:
        out = {"enabled": self.enabled(), "tasks": [], "active": None, "approvals": [],
               "demo_url": self.demo.url if self.demo else "", "stop_hotkey": self.app.cfg.settings.automation_stop_hotkey,
               "windows_supported": sys.platform == "win32"}
        if self._mgr is None and not self.enabled():
            return out
        m = self.mgr
        out["tasks"] = [t.public() for t in m.store.list(20)]
        out["active"] = m.active_id
        out["approvals"] = [a.public() for t in out["tasks"] for a in self.gate.pending_for(t["id"])]
        return out

    def start(self, objective: str, start_url: str, domains: list[str], mode: str = "managed_browser",
              send_screenshots: bool = False, confirm_medium: bool = False, window: dict | None = None) -> dict:
        if not self.enabled():
            return {"ok": False, "error": "Turn on computer tasks first (the switch at the top of this window)."}
        objective = (objective or "").strip()
        if len(objective) < 4:
            return {"ok": False, "error": "Say what Monkey should do (one sentence is enough)."}
        if mode != "managed_browser":
            return {"ok": False, "error": "Window tasks are read-only previews in this version: use the Monkey "
                                         "browser for tasks."}
        domains = [d.strip().lower() for d in domains if d and d.strip()]
        if not domains:
            return {"ok": False, "error": "Add at least one site Monkey may use."}
        ok, why = url_allowed(start_url, domains)
        if not ok:
            return {"ok": False, "error": f"The start page has to be on an allowed site ({why})."}
        try:
            t = self.mgr.create(objective, start_url, domains, send_screenshots=bool(send_screenshots),
                                confirm_medium=bool(confirm_medium))
            self.mgr.start(t.id)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "task": t.public()}

    def demo_start(self, media_seconds: float = 8.0) -> dict:
        from .democourse import DemoCourse

        if self.demo is None:
            self.demo = DemoCourse(media_seconds=media_seconds, variants={"modal"}).start()
        return {"ok": True, "url": self.demo.url, "domain": "127.0.0.1",
                "objective": "Work through all 4 modules of the demo safety training. I'll answer the questions "
                             "and tick the confirmations myself."}

    def control(self, action: str, task_id: str) -> dict:
        m = self.mgr
        try:
            {"pause": m.pause, "resume": m.resume, "stop": m.stop, "done": m.user_done}[action](task_id)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def approve(self, task_id: str, approval_id: str, token: str, allow: bool) -> dict:
        try:
            if allow:
                self.mgr.approve(task_id, approval_id, token)
            else:
                self.mgr.deny(task_id, approval_id)
        except PermissionError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def history(self, task_id: str) -> dict:
        t = self.mgr.get(task_id)
        if t is None:
            return {"ok": False, "error": "Unknown task"}
        return {"ok": True, "task": t.public(), "log": self.mgr.store.audit_log(task_id)[-200:]}

    def windows(self) -> dict:
        from .desktop import list_windows

        return {"ok": True, "windows": [w.public() for w in list_windows()]}

    def emergency_stop(self) -> None:
        self.gate.stopped.set()
        if self._mgr is not None:
            self._mgr.emergency_stop()
        self.app.ui.emit("automation_stopped", {})

    def shutdown(self) -> None:
        if self._mgr is not None:
            self._mgr.shutdown()
        if self.demo is not None:
            self.demo.stop()

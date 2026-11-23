"""The companion (small floating monkey window) shows only while a computer task is under way, never at startup."""
from __future__ import annotations

from types import SimpleNamespace

from monkey import app as app_mod
from monkey.automation.service import AutomationService


class FakeWindow:
    def __init__(self):
        self.calls = []

    def show(self):
        self.calls.append("show")

    def hide(self):
        self.calls.append("hide")


def _app(access=True, enabled=True):
    a = SimpleNamespace(cfg=SimpleNamespace(settings=SimpleNamespace(computer_access=access, overlay_enabled=enabled)),
                        ui=SimpleNamespace(emit=lambda *a, **k: None), _overlay_window=FakeWindow())
    a.on_task_running = lambda running: app_mod._overlay_visibility(a)
    a.automation = AutomationService(a)
    return a


def _task(tid, state):
    return {"task": {"id": tid, "state": state}}


def test_hidden_without_a_task_shown_while_one_runs_hidden_after(monkeypatch):
    monkeypatch.setattr("monkey.desktop_overlay.installed", lambda: True)
    a = _app()
    app_mod._overlay_visibility(a)                                     # startup: no task
    assert a._overlay_window.calls == ["hide"]
    a.automation._emit("automation", _task("t1", "PLANNING"))
    assert a.automation.task_running and a._overlay_window.calls[-1] == "show"
    a.automation._emit("automation", _task("t1", "NEEDS_INPUT"))      # still under way: no flicker
    assert a._overlay_window.calls.count("show") == 1
    a.automation._emit("automation", _task("t2", "RUNNING"))
    a.automation._emit("automation", _task("t1", "COMPLETED"))       # another task still running
    assert a._overlay_window.calls[-1] == "show"
    a.automation._emit("automation", _task("t2", "FAILED"))
    assert not a.automation.task_running and a._overlay_window.calls[-1] == "hide"


def test_emergency_stop_hides_and_settings_still_win(monkeypatch):
    monkeypatch.setattr("monkey.desktop_overlay.installed", lambda: True)
    a = _app()
    a.automation._emit("automation", _task("t1", "RUNNING"))
    a.automation.emergency_stop()
    assert not a.automation.task_running and a._overlay_window.calls[-1] == "hide"
    b = _app(enabled=False)                                            # the owner turned the companion off
    b.automation._emit("automation", _task("t1", "RUNNING"))
    assert "show" not in b._overlay_window.calls
    c = _app(access=False)                                             # computer access off
    c.automation._emit("automation", _task("t1", "RUNNING"))
    assert "show" not in c._overlay_window.calls


def test_first_show_installs_the_no_taskbar_style(monkeypatch):
    seen = []
    monkeypatch.setattr("monkey.desktop_overlay.installed", lambda: False)
    monkeypatch.setattr("monkey.desktop_overlay.install", lambda win, title: seen.append(title))
    a = _app()
    a.automation._emit("automation", _task("t1", "RUNNING"))
    assert seen == ["Monkey companion"]


def test_companion_window_starts_hidden():
    src = (app_mod.__file__ and open(app_mod.__file__, encoding="utf-8").read())
    block = src[src.index('"Monkey companion", url=str(index)'):]
    assert "hidden=True" in block[:600]

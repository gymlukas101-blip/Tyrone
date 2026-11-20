"""Monkey's UIA backend against a real WinForms app (Windows only; opt-in with MONKEY_UIA_TESTS=1 because it opens
windows and a file dialog on the desktop)."""
from __future__ import annotations

import os
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32" or os.environ.get("MONKEY_UIA_TESTS") != "1",
                                reason="needs a Windows desktop session (MONKEY_UIA_TESTS=1)")


@pytest.fixture()
def app(tmp_path):
    from tools.computer_bench.run_windows import Fixture

    fx = Fixture(tmp_path)
    fx.start()
    yield fx
    fx.stop()


def _computer(fx, tmp_path, physical=False):
    from monkey.automation.computer import Computer, Trace
    from monkey.automation.computer.drivers.uia import UIADriver
    from monkey.automation.permissions import PermissionGate
    from monkey.automation.tasks import Task

    t = Task(objective="test", skill="general", files=[str(tmp_path)], allow_physical=physical)
    d = UIADriver(fx.hwnd(), allow_physical=physical)
    return Computer(t, PermissionGate(), {"uia": d}, Trace(t.id)), d


def test_type_click_toggle_select_in_the_background(app, tmp_path):
    from tools.computer_bench.run_windows import cursor_pos, foreground

    c, _ = _computer(app, tmp_path)
    fg, cur = foreground(), cursor_pos()
    c.observe("uia")
    assert c.do("type_text", {"name": "Name", "role": "textbox"}, text="Ada").verified
    assert c.do("click", {"name": "Greet", "role": "button"}).error is None
    assert app.wait_line("^greet:Ada$")
    c.observe("uia")
    out = c.do("click", {"name": "Subscribe to updates", "role": "checkbox"})
    assert out.error is None and app.wait_line("^subscribe:True$")
    c.observe("uia")
    assert c.do("select_option", {"name": "Color", "role": "combobox"}, option="Blue").error is None
    assert app.wait_line("^color:Blue$")
    assert cursor_pos() == cur                                      # the user's mouse never moved


def test_stale_control_is_found_again_by_identity(app, tmp_path):
    c, _ = _computer(app, tmp_path)
    c.observe("uia")
    old = c.find("Archive", "uia", "button")
    c.do("click", {"name": "Rebuild", "role": "button"})
    assert app.wait_line("^rebuilt$")
    out = c.do("click", old)
    assert out.error is None and app.wait_line("^archive$")


def test_native_open_dialog_is_in_scope_and_filled(app, tmp_path):
    f = tmp_path / "pick.txt"
    f.write_text("x")
    c, d = _computer(app, tmp_path)
    c.observe("uia")
    c.do("click", {"name": "Browse...", "role": "button"})
    assert c.wait_for({"kind": "file_dialog"}, 10, "uia").verified
    out = c.do("choose_file", None, path=str(f))
    assert out.error is None and out.verified, out
    assert app.wait_line(r"^picked:.*pick\.txt$")


def test_physical_input_is_refused_unless_allowed(app, tmp_path):
    from monkey.automation.computer.model import ErrorKind

    c, _ = _computer(app, tmp_path, physical=False)
    c.observe("uia")
    out = c.do("press_key", None, keys="Tab")
    assert out.error == ErrorKind.NEEDS_FOREGROUND

"""Desktop driver: coordinate maps everywhere; real windows on Windows only (CI's windows job runs these)."""
from __future__ import annotations

import subprocess
import sys
import time
from types import SimpleNamespace as NS

import pytest

from monkey.automation.desktop import Rect, ScreenMap, logical_to_physical
from monkey.automation.permissions import Action, PermissionGate, SENSITIVE_WINDOW


def test_screenmap_roundtrip_on_a_secondary_monitor_left_of_primary():
    # A 2560×1440 window on a monitor at x = -2560 (left of the primary), shown to the model at 1280 wide.
    m = ScreenMap.fit(Rect(-2560, 100, 0, 1540), 1280, 800)
    assert (m.img_w, m.img_h) == (1280, 720)
    X, Y = m.to_screen(640, 360)
    assert (X, Y) == (-1279, 821)
    assert m.to_image(X, Y) == (640, 360)
    assert m.to_screen(0, 0) == (-2559, 101)                       # the centre of the first scaled pixel
    with pytest.raises(ValueError):
        m.to_screen(1280, 10)                                       # outside the image: never clicked


def test_screenmap_small_window_is_not_upscaled():
    m = ScreenMap.fit(Rect(0, 0, 800, 600))
    assert (m.img_w, m.img_h, m.sx, m.sy) == (800, 600, 1.0, 1.0)


def test_logical_to_physical_at_150_percent():
    assert logical_to_physical(100, 100, Rect(0, 0, 3840, 2400), 1.5) == (150, 150)
    assert logical_to_physical(-2000, 50, Rect(-2560, 0, 0, 1440), 1.25) == (-1860, 62)


def test_sensitive_windows_are_recognized():
    for t in ("1Password", "Bitwarden", "Windows Security", "Chase Online Banking", "KeePassXC"):
        assert SENSITIVE_WINDOW.search(t), t
    assert not SENSITIVE_WINDOW.search("Untitled - Notepad")


# ---------------------------------------------------------------- real Windows (skipped elsewhere)
win = pytest.mark.skipif(sys.platform != "win32", reason="Windows UI Automation")


@pytest.fixture
def notepad():
    pytest.importorskip("pywinauto")
    from monkey.automation.desktop import list_windows

    before = {w.hwnd for w in list_windows()}
    p = subprocess.Popen(["notepad.exe"])
    hwnd = 0
    for _ in range(60):
        time.sleep(0.25)
        new = [w for w in list_windows() if w.hwnd not in before and "notepad" in w.process.lower()]
        if new:
            hwnd = new[0].hwnd
            break
    if not hwnd:
        p.kill()
        pytest.skip("Notepad didn't open a window here")
    yield hwnd
    subprocess.run(["taskkill", "/F", "/IM", "notepad.exe"], capture_output=True)


@win
def test_window_list_capture_and_uia_typing(notepad):
    from monkey.automation.desktop import DesktopSession, ScreenMap, capture_window

    img, rect = capture_window(notepad)
    assert img.size == (rect.width, rect.height) and rect.width > 100
    ScreenMap.fit(rect)                                               # maps cleanly for this window
    s = DesktopSession(notepad, PermissionGate())
    edit = next(c for c in s.observe() if c.role in ("edit", "document"))
    scope = NS(id="t", mode="control_window", allowed_domains=[], confirm_medium=False)
    r = s.act(scope, Action("type", text="Monkey was here"), edit)
    assert r.ok, r.detail
    s.observe()
    edit = next(c for c in s.controls if c.role in ("edit", "document"))
    assert "Monkey was here" in s.read_text(edit)


@win
def test_observe_only_scope_cannot_type(notepad):
    from monkey.automation.desktop import DesktopSession

    s = DesktopSession(notepad, PermissionGate())
    edit = next(c for c in s.observe() if c.role in ("edit", "document"))
    scope = NS(id="t", mode="observe_window", allowed_domains=[], confirm_medium=False)
    r = s.act(scope, Action("type", text="nope"), edit)
    assert not r.ok and "only look" in r.detail


def test_native_cursor_placement_math():
    from monkey.automation.cursor_native import tip_offset, window_origin

    assert tip_offset((42, 42), 1.5) == (63, 63)
    assert window_origin(-1000, 200, (42, 42), 1.0) == (-1042, 158)     # a monitor left of the primary


@win
def test_native_banana_overlay_is_aligned_click_through_and_unfocusable():
    import ctypes

    from monkey.automation.cursor_native import NativeCursor
    from monkey.automation.desktop import root_at

    nc = NativeCursor(motion="reduced")
    try:
        nc.move_to(400, 300)
        nc.hover("button")
        nc.flush()
        left, top, right, bottom = nc.window_rect()
        assert right - left > 40 and bottom - top > 40
        assert (left + nc.tip[0], top + nc.tip[1]) == (400, 300)      # the tip pixel is on the action point
        ex = ctypes.windll.user32.GetWindowLongW(nc.hwnd, -20)
        for bit in (0x80000, 0x20, 0x8000000, 0x8):                  # LAYERED TRANSPARENT NOACTIVATE TOPMOST
            assert ex & bit, hex(bit)
        assert root_at(400 + 6, 300 + 6) != nc.hwnd                 # clicks go to whatever is underneath
        assert ctypes.windll.user32.GetForegroundWindow() != nc.hwnd
        nc.press()
        nc.release()
        nc.hide()
        nc.flush()
        assert not ctypes.windll.user32.IsWindowVisible(nc.hwnd)
    finally:
        nc.close()

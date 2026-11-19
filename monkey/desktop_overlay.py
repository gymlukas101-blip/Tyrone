"""Windows extras for the companion window (no-ops elsewhere).

* Click-through outside Monkey: the window *region* is set to the shapes the UI reports (the avatar and the panel),
  so clicks on the empty parts reach the app underneath. Window regions clip hit-testing and drawing for the whole
  window including the WebView2 child, which is more reliable than layered/transparent windows with WebView2.
* Never steals focus (WS_EX_NOACTIVATE) and has no taskbar button (WS_EX_TOOLWINDOW), so typing and automation keep
  going to the app you're using.
* Hidden from screen capture (WDA_EXCLUDEFROMCAPTURE), so window screenshots Monkey takes never include himself.
* A remembered position that is no longer on any monitor (a display was unplugged) is reset.
"""
from __future__ import annotations

import logging
import sys
import threading
import time

log = logging.getLogger("monkey")
IS_WIN = sys.platform == "win32"
_state: dict = {"hwnd": 0, "rects": None, "dpr": 1.0}


def region_rects(rects: list[dict], dpr: float, limit: int = 12) -> list[tuple[int, int, int, int, int]]:
    """CSS-pixel rects from the page → physical-pixel (left, top, right, bottom, corner) tuples for the region."""
    out = []
    for r in rects[:limit]:
        try:
            x, y, w, h = (float(r[k]) for k in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        rad = float(r.get("r", 16))
        out.append((round(x * dpr), round(y * dpr), round((x + w) * dpr), round((y + h) * dpr), round(rad * 2 * dpr)))
    return out


def install(window, title: str) -> None:
    if not IS_WIN:
        return

    def find():
        import ctypes

        user32 = ctypes.windll.user32
        for _ in range(100):
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                _state["hwnd"] = hwnd
                GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_APPWINDOW = -20, 0x80, 0x08000000, 0x40000
                ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW)
                try:
                    user32.SetWindowDisplayAffinity(hwnd, 0x11)          # WDA_EXCLUDEFROMCAPTURE (Win10 2004+)
                except Exception:  # noqa: BLE001
                    pass
                if _state["rects"] is not None:
                    _apply()
                return
            time.sleep(0.1)
        log.warning("companion window not found for its extras")

    threading.Thread(target=find, name="overlay-extras", daemon=True).start()


def set_hit_rects(rects: list[dict], dpr: float) -> None:
    _state["rects"], _state["dpr"] = rects, dpr or 1.0
    if IS_WIN and _state["hwnd"]:
        _apply()


def _apply() -> None:
    import ctypes

    gdi, user32 = ctypes.windll.gdi32, ctypes.windll.user32
    shapes = region_rects(_state["rects"] or [], _state["dpr"])
    if not shapes:
        user32.SetWindowRgn(_state["hwnd"], None, True)                  # no shapes reported: whole window
        return
    rgn = gdi.CreateRectRgn(0, 0, 0, 0)
    for left, top, right, bottom, corner in shapes:
        part = gdi.CreateRoundRectRgn(left, top, right + 1, bottom + 1, corner, corner)
        gdi.CombineRgn(rgn, rgn, part, 2)                                # RGN_OR
        gdi.DeleteObject(part)
    if not user32.SetWindowRgn(_state["hwnd"], rgn, True):              # on success Windows owns the region
        gdi.DeleteObject(rgn)


def position_on_screen(x, y) -> bool:
    """False if (x, y) isn't on any monitor any more (so the companion doesn't open off-screen)."""
    if x is None or y is None:
        return False
    if not IS_WIN:
        return True
    import ctypes
    from ctypes import wintypes

    return bool(ctypes.windll.user32.MonitorFromPoint(wintypes.POINT(int(x) + 20, int(y) + 20), 0))  # DEFAULTTONULL

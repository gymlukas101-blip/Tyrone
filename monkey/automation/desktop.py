"""Windows desktop driver: list/pick windows, capture one window, read and act through UI Automation.

Scope rules (enforced here and in PermissionGate):
  * Only the window the user picked is read or touched. Its handle is checked before every action; UIA elements must
    belong to it; a coordinate click must land on it (WindowFromPoint), so a window that pops up on top is never
    clicked by accident.
  * Password managers, Windows Security / UAC, banking and credential windows can't be picked at all.
  * Captures are kept in memory only, never written to disk or logs. They go to Claude only if the user ticked
    "let Claude see screenshots" for that task.

Coordinates: Monkey runs per-monitor DPI aware, so window rects and input are physical pixels on the virtual desktop
(negative x/y on monitors left of/above the primary). ScreenMap converts between a resized screenshot (what a model
sees, e.g. 1280 px wide) and those physical pixels.
"""
from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass, field

from .permissions import Action, PermissionGate, SENSITIVE_WINDOW, Target

IS_WIN = sys.platform == "win32"


# ------------------------------------------------------------------------------------------- coordinate mapping
@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


@dataclass(frozen=True)
class ScreenMap:
    """Window capture (physical px at `origin`) → resized image (`img_w`×`img_h`) and back."""
    origin: Rect                  # the captured area on the virtual desktop, physical pixels
    img_w: int
    img_h: int

    @classmethod
    def fit(cls, origin: Rect, max_w: int = 1280, max_h: int = 800) -> "ScreenMap":
        s = min(1.0, max_w / max(origin.width, 1), max_h / max(origin.height, 1))
        return cls(origin, max(1, round(origin.width * s)), max(1, round(origin.height * s)))

    @property
    def sx(self) -> float:
        return self.origin.width / self.img_w

    @property
    def sy(self) -> float:
        return self.origin.height / self.img_h

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        if not (0 <= x < self.img_w and 0 <= y < self.img_h):
            raise ValueError("that point is outside the captured window")
        return self.origin.left + int(x * self.sx + self.sx / 2), self.origin.top + int(y * self.sy + self.sy / 2)

    def to_image(self, X: int, Y: int) -> tuple[int, int]:
        return int((X - self.origin.left) / self.sx), int((Y - self.origin.top) / self.sy)


def logical_to_physical(x: float, y: float, monitor: Rect, scale: float) -> tuple[int, int]:
    """For APIs that report DPI-unaware (logical) coordinates on a scaled monitor (e.g. 150% = 1.5)."""
    return monitor.left + round((x - monitor.left) * scale), monitor.top + round((y - monitor.top) * scale)


# ------------------------------------------------------------------------------------------- windows
@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process: str = ""
    pid: int = 0
    rect: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    minimized: bool = False
    sensitive: bool = False

    def public(self) -> dict:
        return {"hwnd": self.hwnd, "title": self.title[:120], "process": self.process, "sensitive": self.sensitive,
                "minimized": self.minimized, "rect": [self.rect.left, self.rect.top, self.rect.width, self.rect.height]}


def make_dpi_aware() -> None:
    if not IS_WIN:
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # per-monitor v2
    except Exception:  # noqa: BLE001 - already set by pywebview, or an old Windows
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:  # noqa: BLE001
            pass


def _rect(hwnd: int) -> Rect:
    from ctypes import wintypes

    r = wintypes.RECT()
    # DWMWA_EXTENDED_FRAME_BOUNDS = 9: the visible frame, without the invisible resize borders.
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return Rect(r.left, r.top, r.right, r.bottom)


def _cloaked(hwnd: int) -> bool:
    from ctypes import wintypes

    v = wintypes.DWORD()
    ok = ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(v), ctypes.sizeof(v))
    return ok == 0 and v.value != 0


def list_windows(include_own: bool = False) -> list[WindowInfo]:
    """Visible top-level app windows (what Alt+Tab shows), marked sensitive where they must not be picked."""
    if not IS_WIN:
        return []
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    out: list[WindowInfo] = []
    own = os.getpid()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):        # GW_OWNER: skip owned popups
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if (pid.value == own and not include_own) or _cloaked(hwnd):
            return True
        proc = ""
        try:
            import psutil

            proc = psutil.Process(pid.value).name()
        except Exception:  # noqa: BLE001
            pass
        title = buf.value
        out.append(WindowInfo(int(hwnd), title, proc, pid.value, _rect(hwnd), bool(user32.IsIconic(hwnd)),
                              bool(SENSITIVE_WINDOW.search(f"{title} {proc}"))))
        return True

    user32.EnumWindows(cb, 0)
    return out


def foreground_hwnd() -> int:
    return int(ctypes.windll.user32.GetForegroundWindow() or 0) if IS_WIN else 0


def root_at(x: int, y: int) -> int:
    """The top-level window under a physical screen point (GA_ROOT = 2)."""
    from ctypes import wintypes

    h = ctypes.windll.user32.WindowFromPoint(wintypes.POINT(x, y))
    return int(ctypes.windll.user32.GetAncestor(h, 2) or 0) if h else 0


def capture_window(hwnd: int):
    """PIL image of one window (PrintWindow, works when partly covered). Memory only."""
    from ctypes import wintypes

    from PIL import Image

    r = _rect(hwnd)
    wr = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(wr))
    w, h = wr.right - wr.left, wr.bottom - wr.top
    gdi, user32 = ctypes.windll.gdi32, ctypes.windll.user32
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi.CreateCompatibleDC(hdc)
    bmp = gdi.CreateCompatibleBitmap(hdc, w, h)
    gdi.SelectObject(mem, bmp)
    try:
        user32.PrintWindow(hwnd, mem, 2)                                      # PW_RENDERFULLCONTENT
        bmi = (ctypes.c_byte * 40)()
        ctypes.memmove(bmi, ctypes.byref(ctypes.c_uint32(40)), 4)
        ctypes.cast(ctypes.byref(bmi, 4), ctypes.POINTER(ctypes.c_int32))[0] = w
        ctypes.cast(ctypes.byref(bmi, 8), ctypes.POINTER(ctypes.c_int32))[0] = -h   # top-down rows
        ctypes.cast(ctypes.byref(bmi, 12), ctypes.POINTER(ctypes.c_uint16))[0] = 1
        ctypes.cast(ctypes.byref(bmi, 14), ctypes.POINTER(ctypes.c_uint16))[0] = 32
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi.GetDIBits(mem, bmp, 0, h, buf, bmi, 0)
        img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        gdi.DeleteObject(bmp)
        gdi.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)
    # Crop the invisible resize borders so the image matches the visible frame (and ScreenMap's origin).
    return img.crop((r.left - wr.left, r.top - wr.top, r.left - wr.left + r.width, r.top - wr.top + r.height)), r


# ------------------------------------------------------------------------------------------- UI Automation
@dataclass
class Control:
    ref: str
    role: str                     # UIA control type, lower-case: button, edit, document, checkbox, ...
    name: str
    automation_id: str = ""
    enabled: bool = True
    rect: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    is_password: bool = False
    _wrapper: object = None

    def target(self) -> Target:
        role = {"edit": "textbox", "document": "textbox", "radiobutton": "radio", "hyperlink": "link",
                "combobox": "combobox", "checkbox": "checkbox"}.get(self.role, self.role)
        return Target(role=role, name=self.name, input_type="password" if self.is_password else "",
                      sensitive=self.is_password, disabled=not self.enabled)


class DesktopSession:
    """One authorized window, read and driven through UI Automation (pywinauto, uia backend)."""

    def __init__(self, hwnd: int, gate: PermissionGate, cursor=None):
        if not IS_WIN:
            raise RuntimeError("Window control works on Windows only")
        make_dpi_aware()
        info = next((w for w in list_windows() if w.hwnd == hwnd), None)
        if info is None:
            raise RuntimeError("That window isn't open any more")
        if info.sensitive:
            raise PermissionError("Monkey can't look at or control that kind of window (passwords, security, banking)")
        self.hwnd, self.info, self.gate = hwnd, info, gate
        self.cursor = cursor            # cursor_native.NativeCursor (screen space) or None
        from pywinauto import Desktop

        self._win = Desktop(backend="uia").window(handle=hwnd)
        self.controls: list[Control] = []

    def alive(self) -> bool:
        return bool(ctypes.windll.user32.IsWindow(self.hwnd))

    def observe(self, limit: int = 300) -> list[Control]:
        if not self.alive():
            raise RuntimeError("the window was closed")
        out: list[Control] = []
        for i, w in enumerate(self._win.descendants()[:limit]):
            try:
                ei = w.element_info
                r = ei.rectangle
                is_pw = bool(getattr(ei.element, "CurrentIsPassword", False))
                out.append(Control(f"w{i}", (ei.control_type or "").lower(), (ei.name or "")[:200],
                                   ei.automation_id or "", bool(ei.enabled), Rect(r.left, r.top, r.right, r.bottom),
                                   is_pw, w))
            except Exception:  # noqa: BLE001 - controls can vanish mid-walk
                continue
        self.controls = out
        return out

    def outline(self) -> str:
        return "\n".join(f'- {c.role} "{c.name}"{"" if c.enabled else " [disabled]"} [ref={c.ref}]'
                         for c in self.controls if c.role and (c.name or c.role in ("edit", "document")))

    def read_text(self, c: Control) -> str:
        if c.is_password:
            return "[hidden]"
        try:
            return c._wrapper.window_text() or c._wrapper.get_value()
        except Exception:  # noqa: BLE001
            try:
                return c._wrapper.iface_value.CurrentValue
            except Exception:  # noqa: BLE001
                return ""

    def act(self, scope, action: Action, c: Control | None = None):
        from .browser import ActResult

        if action.target is None and c is not None:
            action.target = c.target()
        d = self.gate.authorize(scope, action, page_url="")
        if not d.allowed:
            return ActResult(False, d.reason, d)
        if not self.alive():
            return ActResult(False, "the window was closed", d)
        if c is not None and c.rect.width and c.rect.height:
            cx, cy = (c.rect.left + c.rect.right) // 2, (c.rect.top + c.rect.bottom) // 2
            if root_at(cx, cy) not in (self.hwnd, 0):
                return ActResult(False, "another window is covering it, so I didn't click", d)
        w = c._wrapper if c is not None else None
        cur = self.cursor if (self.cursor is not None and c is not None and c.rect.width) else None
        try:
            if action.kind == "click":
                if cur is not None:
                    # Points at the control it activates (its centre: also where click_input would click).
                    cur.move_to((c.rect.left + c.rect.right) // 2, (c.rect.top + c.rect.bottom) // 2)
                    cur.hover(c.target().role)
                for how in ("invoke", "toggle", "select", "click_input"):
                    fn = getattr(w, how, None)
                    if fn is None:
                        continue
                    try:
                        if how == "click_input" and cur is not None:
                            cur.press()                      # a real OS pointer click: press/ripple match it
                        fn()
                        break
                    except Exception:  # noqa: BLE001 - not supported by this control: try the next way
                        continue
                if cur is not None:
                    cur.release()
            elif action.kind == "type":
                try:
                    w.set_edit_text(action.text)
                except Exception:  # noqa: BLE001
                    w.set_focus()
                    w.type_keys(action.text, with_spaces=True, set_foreground=True)
            elif action.kind == "press":
                if foreground_hwnd() != self.hwnd:
                    return ActResult(False, "the window isn't in front, so I didn't press keys", d)
                from pywinauto.keyboard import send_keys

                send_keys(action.text)
            else:
                return ActResult(False, f"{action.kind} isn't supported for windows", d)
        except Exception as exc:  # noqa: BLE001
            return ActResult(False, f"the window refused that ({type(exc).__name__})", d)
        return ActResult(True, "done", d)

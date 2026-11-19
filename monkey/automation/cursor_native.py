"""Windows: the banana beside the *real* mouse pointer during physical desktop actions.

A tiny native layered window (no WebView, no extra process) shows the pre-rendered banana frames
(cursor/png/*.png, rendered from banana.svg) with per-pixel alpha:
  WS_EX_LAYERED | WS_EX_TRANSPARENT  → fully click-through: WindowFromPoint skips it, clicks reach the app below
  WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW → never takes focus, no taskbar button
  WS_EX_TOPMOST                        → above the app Monkey is operating
  WDA_EXCLUDEFROMCAPTURE               → never appears in screenshots Monkey takes
The Windows mouse pointer is never hidden or replaced, so there is nothing to restore after a crash: the window lives
in Monkey's process and disappears with it.

Coordinates are physical screen pixels (per-monitor DPI aware). The banana is scaled by the monitor's DPI so it looks
the same size on a 100 % and a 150 % display, and the tip pixel is placed exactly on (x, y).
Only one thread (the overlay's own) touches the window; callers just queue commands.
"""
from __future__ import annotations

import ctypes
import json
import logging
import math
import queue
import sys
import threading
import time
from pathlib import Path

from .cursor_events import INTERACTIVE, travel_ms

log = logging.getLogger("monkey.automation")
IS_WIN = sys.platform == "win32"
CURSOR_DIR = Path(__file__).resolve().parent / "cursor"


def tip_offset(frame_tip: tuple[int, int], scale: float) -> tuple[int, int]:
    """Where the tip sits inside the scaled sprite (pixels): the window goes at (x, y) minus this."""
    return round(frame_tip[0] * scale), round(frame_tip[1] * scale)


def window_origin(x: int, y: int, frame_tip: tuple[int, int], scale: float) -> tuple[int, int]:
    tx, ty = tip_offset(frame_tip, scale)
    return x - tx, y - ty


class NativeCursor:
    space = "screen"

    def __init__(self, base_px: int = 64, motion: str = "full", click_fx: bool = True, busy_fx: bool = True):
        if not IS_WIN:
            raise RuntimeError("the desktop banana overlay is Windows-only")
        self.base_px, self.motion, self.click_fx, self.busy_fx = base_px, motion, click_fx, busy_fx
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._ready = threading.Event()
        self.hwnd = 0
        self.pos: tuple[float, float] | None = None
        self.frame = "default"
        self.state = "idle"
        self.tip = (0, 0)                 # tip pixel inside the current sprite (set by the overlay thread)
        self._thread = threading.Thread(target=self._run, name="banana-overlay", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    # ---- public (any thread) ----------------------------------------------------------------------------------------
    def move_to(self, x: int, y: int) -> int:
        d = math.hypot(x - self.pos[0], y - self.pos[1]) if self.pos else 0
        ms = travel_ms(d, self.motion) if self.pos else 0
        self._q.put(("move", x, y, ms))
        self.pos = (x, y)
        if ms:
            time.sleep(ms / 1000)
        return ms

    def hover(self, role: str) -> bool:
        on = (role or "").lower() in INTERACTIVE
        self._q.put(("frame", "hover" if on else "default"))
        return on

    def press(self) -> None:
        self._q.put(("frame", "pressed"))
        time.sleep(0.07)

    def release(self) -> None:
        self._q.put(("ripple",))
        self._q.put(("frame", "hover"))

    def set_state(self, state: str, label: str = "") -> None:
        self._q.put(("state", state))

    def hide(self) -> None:
        self._q.put(("hide",))

    def close(self) -> None:
        self._q.put(("quit",))
        self._thread.join(3)

    def window_rect(self) -> tuple[int, int, int, int]:
        from ctypes import wintypes

        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(self.hwnd, ctypes.byref(r))
        return r.left, r.top, r.right, r.bottom

    def flush(self, timeout: float = 2.0) -> None:
        """Wait until queued commands are drawn (tests)."""
        done = threading.Event()
        self._q.put(("sync", done))
        done.wait(timeout)

    # ---- overlay thread ------------------------------------------------------------------------------------------------
    def _load(self, scale: float):
        from PIL import Image

        man = json.loads((CURSOR_DIR / "manifest.json").read_text(encoding="utf-8"))
        size = min((64, 96), key=lambda s: abs(s - self.base_px * scale))       # nearest pre-rendered size
        frames, tip = {}, None
        for name in ("default", "hover", "pressed", "busy"):
            ent = next(e for e in man["pngs"][name] if e["size"] == size)
            img = Image.open(CURSOR_DIR / ent["file"]).convert("RGBA")
            k = self.base_px * scale / size
            if abs(k - 1) > 0.02:
                img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
            frames[name] = img
            tip = (ent["tip"][0] * k, ent["tip"][1] * k)
        return frames, (round(tip[0]), round(tip[1]))

    def _run(self) -> None:
        from ctypes import wintypes

        user32, gdi32, kernel32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
        try:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:  # noqa: BLE001
            pass
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        self._wndproc = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]

        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW(ctypes.sizeof(WNDCLASSEXW), 0, self._wndproc, 0, 0, hinst, None, None, None, None,
                         "MonkeyBananaCursor", None)
        user32.RegisterClassExW(ctypes.byref(wc))
        ex = 0x00080000 | 0x00000020 | 0x08000000 | 0x00000080 | 0x00000008   # LAYERED TRANSPARENT NOACTIVATE TOOL TOPMOST
        user32.CreateWindowExW.restype = wintypes.HWND
        self.hwnd = user32.CreateWindowExW(ex, "MonkeyBananaCursor", "Monkey banana cursor", 0x80000000,  # WS_POPUP
                                           0, 0, 1, 1, None, None, hinst, None)
        try:
            user32.SetWindowDisplayAffinity(self.hwnd, 0x11)                     # WDA_EXCLUDEFROMCAPTURE
        except Exception:  # noqa: BLE001
            pass
        self._ready.set()

        scale = 1.0
        frames, tip = self._load(scale)
        cur_pos = None
        move = None                       # (x0, y0, x1, y1, t0, ms)
        ripple_t0 = 0.0
        visible = False
        msg = wintypes.MSG()

        def draw():
            nonlocal frames, tip
            if cur_pos is None:
                return
            img = frames["busy" if self.state == "busy" and self.busy_fx and self.frame == "default" else self.frame]
            img = img.copy()
            if ripple_t0 and self.click_fx and self.motion != "reduced":
                from PIL import ImageDraw

                t = (time.time() - ripple_t0) / 0.32
                if t < 1:
                    d = ImageDraw.Draw(img)
                    r = 6 + t * 26 * (img.width / 154)
                    a = int(255 * (1 - t))
                    d.ellipse((tip[0] - r, tip[1] - r, tip[0] + r, tip[1] + r), outline=(255, 214, 10, a),
                              width=max(2, round(3 * img.width / 154)))
            self.tip = tip
            self._blit(img, round(cur_pos[0]) - tip[0], round(cur_pos[1]) - tip[1])

        running = True
        while running:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):        # PM_REMOVE
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            animating = bool(move) or (ripple_t0 and time.time() - ripple_t0 < 0.4)
            try:
                cmd = self._q.get(timeout=1 / 60 if animating else 0.05)
            except queue.Empty:
                cmd = None
            if cmd:
                k = cmd[0]
                if k == "move":
                    _, x, y, ms = cmd
                    k_dpi = self._dpi_scale(x, y)                               # same physical size on every monitor
                    if abs(k_dpi - scale) > 0.01:
                        scale = k_dpi
                        frames, tip = self._load(scale)
                    if cur_pos is None or not ms:
                        cur_pos, move = (x, y), None
                    else:
                        move = (cur_pos[0], cur_pos[1], x, y, time.time(), ms / 1000)
                    if not visible:
                        user32.ShowWindow(self.hwnd, 4)                          # SW_SHOWNOACTIVATE
                        visible = True
                elif k == "frame":
                    if cmd[1] == "pressed" and move:                             # snap: never press mid-flight
                        cur_pos, move = (move[2], move[3]), None
                    self.frame = cmd[1]
                elif k == "ripple":
                    ripple_t0 = time.time()
                elif k == "state":
                    self.state = cmd[1]
                elif k == "hide":
                    user32.ShowWindow(self.hwnd, 0)
                    visible, cur_pos, move = False, None, None
                elif k == "sync":
                    draw()
                    cmd[1].set()
                    continue
                elif k == "quit":
                    running = False
                    continue
            if move:
                t = min(1.0, (time.time() - move[4]) / move[5])
                e = 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2
                cur_pos = (move[0] + (move[2] - move[0]) * e, move[1] + (move[3] - move[1]) * e)
                if t >= 1:
                    move = None
            if visible and (cmd or animating):
                draw()
        user32.DestroyWindow(self.hwnd)

    @staticmethod
    def _dpi_scale(x: int, y: int) -> float:
        from ctypes import wintypes

        try:
            mon = ctypes.windll.user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)   # NEAREST
            dx, dy = ctypes.c_uint(), ctypes.c_uint()
            ctypes.windll.shcore.GetDpiForMonitor(mon, 0, ctypes.byref(dx), ctypes.byref(dy))
            return max(0.75, dx.value / 96)
        except Exception:  # noqa: BLE001
            return 1.0

    def _blit(self, img, left: int, top: int) -> None:
        """UpdateLayeredWindow with a premultiplied BGRA bitmap (per-pixel alpha, no background rectangle)."""
        from ctypes import wintypes

        import numpy as np

        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        arr = np.asarray(img, dtype=np.uint16)
        a = arr[..., 3:4]
        pm = np.concatenate([(arr[..., :3] * a // 255), a], axis=2).astype(np.uint8)[..., [2, 1, 0, 3]]
        h, w = pm.shape[:2]
        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)

        class BMI(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        bmp = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, pm.tobytes(), w * h * 4)
        old = gdi32.SelectObject(mem, bmp)

        class BLEND(ctypes.Structure):
            _fields_ = [("op", ctypes.c_byte), ("flags", ctypes.c_byte), ("alpha", ctypes.c_ubyte), ("fmt", ctypes.c_byte)]

        pt, sz, src = wintypes.POINT(left, top), wintypes.SIZE(w, h), wintypes.POINT(0, 0)
        user32.UpdateLayeredWindow(self.hwnd, screen, ctypes.byref(pt), ctypes.byref(sz), mem, ctypes.byref(src), 0,
                                   ctypes.byref(BLEND(0, 0, 255, 1)), 2)       # AC_SRC_ALPHA, ULW_ALPHA
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)

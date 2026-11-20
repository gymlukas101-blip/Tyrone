"""Windows backend: native UI Automation (pywinauto, uia backend) on windows the user put in scope.

Scope = the window the user picked, plus windows *owned* by it in the same process (its dialogs: Open/Save pickers,
message boxes), plus, for hybrid tasks, the windows of Monkey's own managed browser. Nothing else is read or touched.

Background-first: Invoke / Toggle / SelectionItem / ExpandCollapse / Value patterns act without moving the user's
mouse or stealing focus. Only when a control supports none of them does Monkey fall back to physical input
(click_input / type_keys), which needs the window in front and waits while the user is typing or moving the mouse.
"""
from __future__ import annotations

import ctypes
import os
import re
import sys
import time
from typing import Callable

from ...desktop import IS_WIN, Rect, foreground_hwnd, list_windows, make_dpi_aware, root_at
from ...permissions import SENSITIVE_WINDOW
from ..model import Box, Capability, DriverError, ElementRef, ErrorKind, Space, View, signature_of
from .base import Driver

CAPABILITY = Capability(
    name="uia", os=("windows",), app_types=("native", "web"), semantic=True, dom=False, visual=True,
    needs_foreground=False, background_ok=True, coord_space=Space.SCREEN, upload=True, download=False, cost="free",
    typical_ms=250, recovery=("reobserve", "refocus", "alt_backend"),
    notes="UIA patterns act in the background; physical-input fallback needs the foreground and an idle user. "
          "Owned dialogs (file pickers, message boxes) of an in-scope window are in scope.")

ROLE = {"edit": "textbox", "document": "textbox", "radiobutton": "radio", "hyperlink": "link", "listitem": "option",
        "menuitem": "menuitem", "tabitem": "tab", "treeitem": "treeitem", "checkbox": "checkbox", "button": "button",
        "combobox": "combobox", "text": "text", "list": "list", "window": "window", "pane": "pane"}
_SKIP_ROLES = {"pane", "group", "custom", "image", "separator", "thumb", "titlebar", "scrollbar", "toolbar"}
# Common file dialog (comdlg32 / IFileDialog): the "File name:" edit and the Open/Save button have fixed ids.
FILE_NAME_IDS = ("1148", "1001")
FILE_OK_ID = "1"
GW_OWNER = 4


def user_idle_ms() -> int:
    """Milliseconds since the last keyboard/mouse input on this session (GetLastInputInfo)."""
    if not IS_WIN:
        return 10**9

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    li = LASTINPUTINFO()
    li.cbSize = ctypes.sizeof(li)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        return 10**9
    return int(ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF


def owner_of(hwnd: int) -> int:
    return int(ctypes.windll.user32.GetWindow(hwnd, GW_OWNER) or 0) if IS_WIN else 0


def pid_of(hwnd: int) -> int:
    if not IS_WIN:
        return 0
    from ctypes import wintypes

    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def class_of(hwnd: int) -> str:
    if not IS_WIN:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def top_windows() -> list[int]:
    """Every visible top-level window, owned popups included (list_windows() skips those on purpose)."""
    if not IS_WIN:
        return []
    from ctypes import wintypes

    out: list[int] = []
    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if user32.IsWindowVisible(h):
            out.append(int(h))
        return True

    user32.EnumWindows(cb, 0)
    return out


def child_pids(root_pid: int) -> set[int]:
    try:
        import psutil

        return {p.pid for p in psutil.Process(root_pid).children(recursive=True)}
    except Exception:  # noqa: BLE001
        return set()


class Scope:
    """Which top-level windows a task may read/act on. Pure logic (testable off Windows with injected functions)."""

    def __init__(self, roots: set[int], pids: set[int] | None = None, *, owner=owner_of, pid=pid_of,
                 windows=top_windows, title=None):
        self.roots = set(roots)
        self.pids = set(pids or ())          # whole processes in scope (Monkey's managed browser)
        self._owner, self._pid, self._windows = owner, pid, windows
        self._title = title or _title

    def contains(self, hwnd: int) -> bool:
        if not hwnd:
            return False
        if hwnd in self.roots:
            return True
        if self._pid(hwnd) in self.pids:
            return True
        seen, h = set(), hwnd
        while h and h not in seen:           # owned by an in-scope window (its dialog), same process
            seen.add(h)
            o = self._owner(h)
            if o in self.roots or (o and self._pid(o) in self.pids):
                return self._pid(h) == self._pid(o)
            h = o
        return False

    def dialogs(self) -> list[int]:
        """In-scope owned windows (file pickers, message boxes), newest first in Z-order."""
        out = []
        for h in self._windows():
            if h in self.roots or not self.contains(h):
                continue
            if self._owner(h) and not SENSITIVE_WINDOW.search(self._title(h)):
                out.append(h)
        return out


def _title(hwnd: int) -> str:
    if not IS_WIN:
        return ""
    n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


class UIADriver(Driver):
    name = "uia"
    capability = CAPABILITY

    def __init__(self, root_hwnd: int = 0, *, pids: set[int] | None = None, session_id: str = "w1",
                 cursor=None, max_controls: int = 400, allow_physical: bool = False):
        if not IS_WIN:
            raise DriverError(ErrorKind.UNSUPPORTED, "Window control works on Windows only")
        make_dpi_aware()
        if root_hwnd:
            info = next((w for w in list_windows() if w.hwnd == root_hwnd), None)
            if info is None:
                raise DriverError(ErrorKind.SESSION_LOST, "That window isn't open any more")
            if info.sensitive:
                raise DriverError(ErrorKind.REFUSED, "Monkey can't control that kind of window")
            if is_elevated(info.pid) and not is_elevated(os.getpid()):
                raise DriverError(ErrorKind.ELEVATED, "that window runs as administrator, so Windows won't let Monkey "
                                                      "control it")
        self.scope = Scope({root_hwnd} if root_hwnd else set(), pids)
        self.root = root_hwnd
        self.session_id = session_id
        self.cursor = cursor
        self.max_controls = max_controls
        self.active = root_hwnd          # the window observe() reads: a modal dialog takes over while it's open
        self._els: dict[str, ElementRef] = {}
        self._own_input_at = 0.0
        self.allow_physical = allow_physical   # the user ticked "may use my real mouse/keyboard in this window"

    # ---- windows ----------------------------------------------------------------------------------------------------
    def alive(self) -> bool:
        return bool(self.active and ctypes.windll.user32.IsWindow(self.active)) or bool(self.scope.dialogs())

    def pick_active(self) -> int:
        """A dialog of the scope (e.g. the Open picker) wins; otherwise the root (or the browser's top window)."""
        d = self.scope.dialogs()
        if d:
            self.active = d[0]
        elif self.root and ctypes.windll.user32.IsWindow(self.root):
            self.active = self.root
        else:
            cands = [h for h in top_windows() if self.scope.contains(h) and not owner_of(h)]
            self.active = cands[0] if cands else 0
        if not self.active:
            raise DriverError(ErrorKind.SESSION_LOST, "the window was closed")
        return self.active

    def _wrapper(self, hwnd: int):
        from pywinauto import Desktop

        return Desktop(backend="uia").window(handle=hwnd).wrapper_object()

    # ---- observing --------------------------------------------------------------------------------------------------
    def observe(self) -> View:
        try:
            return self._observe()
        except DriverError:
            raise
        except Exception:  # noqa: BLE001 - a COM hiccup while a dialog opens/closes: look once more
            time.sleep(0.3)
            try:
                return self._observe()
            except DriverError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise DriverError(ErrorKind.STALE, f"the window changed while reading it ({type(exc).__name__})") \
                    from exc

    def _observe(self) -> View:
        hwnd = self.pick_active()
        if is_hung(hwnd):
            raise DriverError(ErrorKind.UNRESPONSIVE, "the app isn't responding")
        win = self._wrapper(hwnd)
        els: list[ElementRef] = []
        self._els = {}
        try:
            desc = _walk(win, limit=self.max_controls * 3, per_list=60, budget_s=4.0)
        except Exception as exc:  # noqa: BLE001
            raise DriverError(ErrorKind.SESSION_LOST, f"couldn't read the window ({type(exc).__name__})") from exc
        twins: dict[tuple, int] = {}
        truncated = len(desc) > self.max_controls * 3
        # Budget: interactive controls first, so a long list can't push the dialog's buttons out of the snapshot.
        desc = sorted(desc[: self.max_controls * 3], key=lambda w: _rank(w))[: self.max_controls]
        for w in desc:
            try:
                ei = w.element_info
                ct = (ei.control_type or "").lower()
                if ct in _SKIP_ROLES and not ei.name:
                    continue
                key = (ct, ei.name or "", ei.automation_id or "")
                n = twins.get(key, 0)
                twins[key] = n + 1
                rid = f"{len(els)}#{n}"
                r = ei.rectangle
                pw = bool(getattr(ei.element, "CurrentIsPassword", False))
                role = ROLE.get(ct, ct)
                el = ElementRef(id=f"{self.session_id}:{rid}", backend=self.name, session=f"{self.session_id}@{hwnd}",
                                ref=rid, role=role, name=(ei.name or "")[:200], automation_id=ei.automation_id or "",
                                box=Box(r.left, r.top, r.width(), r.height(), Space.SCREEN), enabled=bool(ei.enabled),
                                sensitive=pw, input_type="password" if pw else "", native=w)
                if role == "checkbox" or role == "radio":
                    el.checked = _toggle_state(w)
                if role in ("textbox", "combobox") and not pw:
                    el.value = _value(w)[:200]
                els.append(el)
                self._els[el.id] = el
            except Exception:  # noqa: BLE001 - controls can vanish mid-walk
                continue
        title = _title(hwnd)
        sig = signature_of(str(hwnd), title, "\n".join(f"{e.role}|{e.name}|{e.enabled}|{e.checked}|{e.value}"
                                                      for e in els))
        return View(backend=self.name, session=f"{self.session_id}@{hwnd}", title=title[:200],
                    location=class_of(hwnd), elements=els, signature=sig,
                    extra={"dialog": hwnd != self.root, "hwnd": hwnd, "truncated": truncated})

    def signature(self) -> str:
        return self.observe().signature

    def refind(self, el: ElementRef) -> ElementRef:
        twins_before = int(el.ref.split("#")[1]) if "#" in el.ref else 0
        v = self.observe()
        same = [c for c in v.elements if c.role == el.role and c.name == el.name
                and c.automation_id == el.automation_id]
        if not same and (not el.automation_id or el.automation_id.isdigit()):
            # Win32/WinForms controls without a developer-set id get a numeric one (the control id/handle) that
            # changes when the control is recreated: then role + name is the identity, if it's unique.
            same = [c for c in v.elements if c.role == el.role and c.name == el.name]
            if len(same) > 1:
                raise DriverError(ErrorKind.AMBIGUOUS, f"several controls are called '{el.name[:40]}'")
        if not same:
            raise DriverError(ErrorKind.STALE, f"{el.role} '{el.name[:40]}' isn't there any more")
        if len(same) > 1 and twins_before >= len(same):
            raise DriverError(ErrorKind.AMBIGUOUS, f"several controls are called '{el.name[:40]}'")
        return same[min(twins_before, len(same) - 1)]

    def element_state(self, el: ElementRef) -> dict:
        w = self._live(el)
        try:
            return {"enabled": bool(w.element_info.enabled), "checked": _toggle_state(w),
                    "value": "" if el.sensitive else _value(w)[:200], "visible": bool(w.is_visible())}
        except Exception as exc:  # noqa: BLE001
            raise DriverError(ErrorKind.STALE, "couldn't read that control") from exc

    def _live(self, el: ElementRef):
        """The live control for a ref: the cached wrapper if it's still the same control (role + name + automation
        id read now), else re-found by that identity. Zero matches = stale, several = ambiguous: never a guess."""
        e = self._els.get(el.id) or el
        w = e.native
        if w is not None:
            try:
                ei = w.element_info
                if ROLE.get((ei.control_type or "").lower(), "") == el.role and (ei.name or "")[:200] == el.name \
                        and (ei.automation_id or "") == el.automation_id and w.is_enabled() is not None:
                    return w
            except Exception:  # noqa: BLE001 - the element died
                pass
        return self.refind(el).native

    # ---- acting -----------------------------------------------------------------------------------------------------
    def _check_target(self, el: ElementRef) -> None:
        if el.box and el.box.w and el.box.h:
            cx, cy = el.box.center
            top = root_at(int(cx), int(cy))
            if top and not self.scope.contains(top):
                raise DriverError(ErrorKind.COVERED, "another window is covering it, so I didn't click")

    def _physical_ok(self) -> None:
        """Physical input only if the user allowed it for this task, with our window in front and the user idle for
        1.5 s (their input always wins). Otherwise refuse: never a silent fallback to the real mouse."""
        if not self.allow_physical:
            raise DriverError(ErrorKind.NEEDS_FOREGROUND, "that control only responds to the real mouse or keyboard")
        el = getattr(self, "_target_el", None)
        if el is not None:
            self._check_target(el)            # a real click must land on our window, not on whatever covers it
        if foreground_hwnd() not in (self.active, self.root) and not self.scope.contains(foreground_hwnd()):
            raise DriverError(ErrorKind.WRONG_WINDOW, "the window isn't in front, so I didn't use the mouse")
        idle = user_idle_ms()
        if idle < 1500 and time.time() - self._own_input_at > 2.0:
            raise DriverError(ErrorKind.USER_ACTIVE, "you're using the mouse or keyboard; I'll wait")

    def perform(self, op: str, el: ElementRef | None, args: dict) -> dict:
        if op == "press_key":
            if self.allow_physical and foreground_hwnd() != self.active and self.active:
                try:
                    self._wrapper(self.active).set_focus()      # the user allowed real input in this window
                    time.sleep(0.2)
                except Exception:  # noqa: BLE001
                    pass
            self._physical_ok()
            from pywinauto.keyboard import send_keys

            send_keys(to_pywinauto_keys(args["keys"]))
            self._own_input_at = time.time()
            return {"physical": True}
        if op == "choose_file":
            return self.fill_file_dialog(str(args["path"]))
        if el is None:
            raise DriverError(ErrorKind.NOT_FOUND, f"{op} needs a target")
        w = self._live(el)
        self._target_el = el          # the covered-check runs only before *physical* input (see _physical_ok)
        ev = {}
        if el.box:
            cx, cy = el.box.center
            ev = {"x": int(cx), "y": int(cy), "space": "screen"}
            if self.cursor is not None:
                self.cursor.move_to(int(cx), int(cy))
                self.cursor.hover(el.role)
        try:
            if op == "click":
                ev.update(self._click(w))
            elif op == "double_click":
                self._physical_ok()
                w.double_click_input()
                self._own_input_at = time.time()
                ev["physical"] = True
            elif op == "hover":
                ev["physical"] = False          # shown with the banana only; the real mouse stays with the user
            elif op == "type_text":
                ev.update(self._type(w, args.get("text", "")))
            elif op == "select_option":
                ev.update(self._select(w, str(args.get("option", ""))))
            elif op == "scroll":
                try:
                    w.iface_scroll_item.ScrollIntoView()
                    ev["via"] = "scroll_item"
                except Exception:  # noqa: BLE001
                    self._physical_ok()
                    w.scroll(args.get("direction", "down"), "page", int(args.get("amount", 1)))
                    ev["physical"] = True
            elif op in ("upload_file", "choose_file"):
                ev.update(self.fill_file_dialog(str(args["path"])))
            else:
                raise DriverError(ErrorKind.UNSUPPORTED, f"windows can't {op}")
        except DriverError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not ctypes.windll.user32.IsWindow(self.active):
                raise DriverError(ErrorKind.SESSION_LOST, "the window closed") from exc
            raise DriverError(ErrorKind.INTERNAL, f"the window refused that ({type(exc).__name__})") from exc
        finally:
            if self.cursor is not None:
                self.cursor.release()
        return ev

    def _click(self, w) -> dict:
        # A button that opens a modal dialog doesn't return from Invoke until the dialog closes (Win32 BM_CLICK is
        # synchronous). Monkey must never wait on that: classic buttons get a *posted* BM_CLICK (background-safe,
        # returns at once); everything else is invoked on a helper thread and given 3 s.
        if self.cursor is not None:
            self.cursor.press()
        if _post_bm_click(w):
            return {"via": "bm_click", "physical": False}
        for how in ("invoke", "toggle", "select", "expand"):
            fn = getattr(w, how, None)
            if fn is None:
                continue
            res = _call_with_deadline(fn, 3.0)
            if res == "ok":
                return {"via": how, "physical": False}
            if res == "pending":
                return {"via": how, "physical": False, "pending": True}   # likely a modal dialog opened
            # "error": pattern not supported → try the next one
        self._physical_ok()
        if self.cursor is not None:
            self.cursor.press()
        w.click_input()
        self._own_input_at = time.time()
        return {"via": "click_input", "physical": True}

    def _select(self, w, option: str) -> dict:
        """Pick a list/combo item with ExpandCollapse + SelectionItem patterns (background-safe, no real mouse);
        the Value pattern for editable combos; physical selection only as an allowed last resort."""
        expanded = False
        try:
            w.iface_expand_collapse.Expand()
            expanded = True
        except Exception:  # noqa: BLE001
            pass
        try:
            for item in w.descendants():
                ei = item.element_info
                if (ei.control_type or "").lower() == "listitem" and (ei.name or "").strip().lower() == option.lower():
                    item.iface_selection_item.Select()
                    return {"via": "selection_item", "physical": False}
            try:
                w.iface_value.SetValue(option)
                return {"via": "value_pattern", "physical": False}
            except Exception:  # noqa: BLE001
                pass
        finally:
            if expanded:
                try:
                    w.iface_expand_collapse.Collapse()
                except Exception:  # noqa: BLE001
                    pass
        self._physical_ok()
        w.select(option)
        self._own_input_at = time.time()
        return {"via": "select", "physical": True}

    def _type(self, w, text: str) -> dict:
        try:
            w.iface_value.SetValue(text)
            return {"via": "value_pattern", "physical": False}
        except Exception:  # noqa: BLE001
            pass
        try:
            w.set_edit_text(text)
            return {"via": "set_edit_text", "physical": False}
        except Exception:  # noqa: BLE001
            pass
        self._physical_ok()
        w.set_focus()
        w.type_keys(text, with_spaces=True, with_newlines=False, set_foreground=False)
        self._own_input_at = time.time()
        return {"via": "type_keys", "physical": True}

    # ---- the native file picker ----------------------------------------------------------------------------------
    def file_dialog(self) -> int:
        for h in self.scope.dialogs():
            if class_of(h) == "#32770" and self._find_file_name(h) is not None:
                return h
        return 0

    def dialog_process(self) -> str:
        """The program that owns the open file picker ("" if none or unknown)."""
        h = self.file_dialog()
        if not h:
            return ""
        try:
            import psutil

            return psutil.Process(pid_of(h)).name()
        except Exception:  # noqa: BLE001
            return ""

    def _find_file_name(self, hwnd: int):
        try:
            win = self._wrapper(hwnd)
            for aid in FILE_NAME_IDS:
                for c in win.descendants(control_type="Edit"):
                    if c.element_info.automation_id == aid:
                        return c
            for c in win.descendants(control_type="Edit"):
                if re.search(r"file ?name", c.element_info.name or "", re.I):
                    return c
        except Exception:  # noqa: BLE001
            return None
        return None

    def fill_file_dialog(self, path: str, timeout_s: float = 8.0) -> dict:
        """Type the path into the picker's File name box and press Open (both through UIA patterns), then wait for
        the dialog to close. The path is validated by the caller (task scope); nothing is browsed or listed."""
        end = time.time() + timeout_s
        hwnd = 0
        while time.time() < end and not hwnd:
            hwnd = self.file_dialog()
            if not hwnd:
                time.sleep(0.2)
        if not hwnd:
            raise DriverError(ErrorKind.NOT_FOUND, "no file picker is open")
        self.active = hwnd
        edit = self._find_file_name(hwnd)
        if edit is None:
            raise DriverError(ErrorKind.NOT_FOUND, "couldn't find the file name box")
        via = self._type(edit, path)["via"]
        ok_btn = None
        for c in self._wrapper(hwnd).descendants(control_type="Button"):
            if c.element_info.automation_id == FILE_OK_ID:
                ok_btn = c
                break
        if ok_btn is None:
            raise DriverError(ErrorKind.NOT_FOUND, "couldn't find the Open button")
        try:
            ok_btn.invoke()
        except Exception:  # noqa: BLE001
            self._physical_ok()
            ok_btn.click_input()
        while time.time() < end:
            if not ctypes.windll.user32.IsWindow(hwnd) or not ctypes.windll.user32.IsWindowVisible(hwnd):
                self.active = self.root
                return {"via": f"file_dialog/{via}", "dialog_closed": True}
            time.sleep(0.15)
        raise DriverError(ErrorKind.NO_EFFECT, "the file picker didn't close (the path may be wrong)")

    # ---- waiting -------------------------------------------------------------------------------------------------------
    def wait_for(self, cond: dict, timeout_s: float, should_stop: Callable[[], bool]) -> bool:
        kind = cond.get("kind", "")
        checks = {
            "change": lambda: self.signature() != (cond.get("since") or ""),
            "text": lambda: any(str(cond.get("text", "")).lower() in (e.name + " " + e.value).lower()
                                for e in self.observe().elements),
            "dialog": lambda: bool(self.scope.dialogs()),
            "file_dialog": lambda: bool(self.file_dialog()),
            "dialog_gone": lambda: not self.scope.dialogs(),
            "enabled": lambda: self.element_state(cond["el"]).get("enabled", False),
            "time": lambda: False,
        }
        if kind not in checks:
            raise DriverError(ErrorKind.UNSUPPORTED, f"windows can't wait for {kind}")
        if kind == "time":
            timeout_s = min(timeout_s, float(cond.get("seconds", 1)))
        end = time.time() + timeout_s
        while time.time() < end:
            if should_stop():
                return False
            try:
                if checks[kind]():
                    return True
            except DriverError as exc:
                if exc.kind == ErrorKind.SESSION_LOST and kind != "dialog_gone":
                    raise
                if kind == "dialog_gone":
                    return True
            time.sleep(0.25)
        return kind == "time"

    def capture(self):
        from ...desktop import capture_window

        img, r = capture_window(self.pick_active())
        return img, (float(r.left), float(r.top), float(r.width), float(r.height))

    def click_point(self, x: float, y: float) -> None:
        top = root_at(int(x), int(y))
        if not self.scope.contains(top):
            raise DriverError(ErrorKind.COVERED, "that point isn't on the window in scope")
        self._physical_ok()
        from pywinauto import mouse

        mouse.click(coords=(int(x), int(y)))
        self._own_input_at = time.time()

    def target_at(self, x: float, y: float):
        from ...permissions import Target

        try:
            from pywinauto import Desktop

            w = Desktop(backend="uia").from_point(int(x), int(y))
            ei = w.element_info
            pw = bool(getattr(ei.element, "CurrentIsPassword", False))
            return Target(role=ROLE.get((ei.control_type or "").lower(), ""), name=ei.name or "",
                          input_type="password" if pw else "", sensitive=pw)
        except Exception:  # noqa: BLE001
            return Target(role="", name="")


_LISTS = {"list", "tree", "datagrid", "table", "menu"}


def _walk(win, limit: int, per_list: int, budget_s: float) -> list:
    """Breadth-first walk with hard caps: at most `limit` controls, `per_list` children of any list/tree/grid (a file
    dialog's folder view can hold thousands), and `budget_s` seconds. A truncated walk still has the dialog's buttons."""
    out, queue, t0 = [], [win], time.time()
    while queue and len(out) < limit and time.time() - t0 < budget_s:
        node = queue.pop(0)
        try:
            kids = node.children()
        except Exception:  # noqa: BLE001
            continue
        try:
            if (node.element_info.control_type or "").lower() in _LISTS:
                kids = kids[:per_list]
        except Exception:  # noqa: BLE001
            pass
        out.extend(kids)
        queue.extend(kids)
    return out[:limit]


def _post_bm_click(w) -> bool:
    """Classic Win32/WinForms buttons: PostMessage(BM_CLICK) clicks without waiting for what the click opens."""
    if not IS_WIN:
        return False
    try:
        ei = w.element_info
        if (ei.control_type or "").lower() not in ("button", "checkbox", "radiobutton"):
            return False
        h = int(ei.handle or 0)
        if not h or "button" not in class_of(h).lower():
            return False
        from ctypes import wintypes

        return bool(ctypes.windll.user32.PostMessageW(wintypes.HWND(h), 0x00F5, 0, 0))   # BM_CLICK
    except Exception:  # noqa: BLE001
        return False


def _call_with_deadline(fn, seconds: float) -> str:
    """'ok' | 'error' | 'pending' (still running after `seconds`, e.g. blocked behind a modal it opened)."""
    import threading

    box: dict = {}

    def run():
        try:
            try:
                import comtypes

                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            except Exception:  # noqa: BLE001
                pass
            fn()
            box["r"] = "ok"
        except Exception:  # noqa: BLE001
            box["r"] = "error"

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(seconds)
    return box.get("r", "pending")


_INTERACTIVE = {"button", "edit", "checkbox", "radiobutton", "combobox", "hyperlink", "menuitem", "tabitem",
                "listitem", "treeitem", "document", "spinner", "slider"}


def _rank(w) -> int:
    try:
        return 0 if (w.element_info.control_type or "").lower() in _INTERACTIVE else 1
    except Exception:  # noqa: BLE001
        return 2


def is_hung(hwnd: int, timeout_ms: int = 1500) -> bool:
    """SendMessageTimeout(WM_NULL, SMTO_ABORTIFHUNG): a window that doesn't answer in time is treated as hung, so a
    UIA call can't block the task thread for minutes."""
    if not IS_WIN:
        return False
    from ctypes import wintypes

    res = ctypes.c_size_t()
    ok = ctypes.windll.user32.SendMessageTimeoutW(wintypes.HWND(hwnd), 0, 0, 0, 0x0002, timeout_ms, ctypes.byref(res))
    return ok == 0 and ctypes.windll.user32.IsWindow(wintypes.HWND(hwnd))


def is_elevated(pid: int) -> bool:
    """Does the process run elevated (administrator)? UIPI blocks Monkey's input into it, and SendInput would still
    report success, so Monkey checks first. A process Monkey can't even query counts as elevated."""
    if not IS_WIN or not pid:
        return False
    from ctypes import wintypes

    k32, adv = ctypes.windll.kernel32, ctypes.windll.advapi32
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)              # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return k32.GetLastError() == 5                   # access denied: a higher-integrity process
    tok = wintypes.HANDLE()
    try:
        if not adv.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):     # TOKEN_QUERY
            return False
        elev, size = wintypes.DWORD(), wintypes.DWORD()
        ok = adv.GetTokenInformation(tok, 20, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(size))
        return bool(ok and elev.value)
    finally:
        if tok:
            k32.CloseHandle(tok)
        k32.CloseHandle(h)


_KEYNAMES = {"enter": "{ENTER}", "return": "{ENTER}", "tab": "{TAB}", "escape": "{ESC}", "esc": "{ESC}",
             "backspace": "{BACKSPACE}", "delete": "{DELETE}", "space": " ", "up": "{UP}", "down": "{DOWN}",
             "left": "{LEFT}", "right": "{RIGHT}", "home": "{HOME}", "end": "{END}", "pageup": "{PGUP}",
             "pagedown": "{PGDN}", **{f"f{i}": f"{{F{i}}}" for i in range(1, 13)}}
_MODS = {"control": "^", "ctrl": "^", "shift": "+", "alt": "%"}


def to_pywinauto_keys(keys: str) -> str:
    """Playwright-style names ("Control+S", "Enter", "Alt+F4") → pywinauto send_keys syntax ("^s", "{ENTER}")."""
    out = []
    for chord in keys.split():
        parts = chord.split("+")
        mods = "".join(_MODS.get(p.lower(), "") for p in parts[:-1])
        k = parts[-1]
        key = _KEYNAMES.get(k.lower(), k.lower() if len(k) == 1 else "{" + k.upper() + "}")
        out.append(mods + key)
    return "".join(out)


def _toggle_state(w) -> bool | None:
    try:
        return bool(w.get_toggle_state())
    except Exception:  # noqa: BLE001
        try:
            return bool(w.is_selected())
        except Exception:  # noqa: BLE001
            return None


def _value(w) -> str:
    for get in (lambda: w.iface_value.CurrentValue, lambda: w.get_value(), lambda: w.window_text()):
        try:
            v = get()
            if v:
                return str(v)
        except Exception:  # noqa: BLE001
            continue
    return ""


def describe_windows() -> list[dict]:
    """Diagnostics: every visible top-level window with class, owner and process id."""
    return [{"hwnd": h, "class": class_of(h), "title": _title(h)[:60], "owner": owner_of(h), "pid": pid_of(h)}
            for h in top_windows()]


__all__ = ["UIADriver", "Scope", "CAPABILITY", "user_idle_ms", "Rect", "sys"]

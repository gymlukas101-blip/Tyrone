"""Reminders as native Windows notifications (toasts in Action Center), with Done and Snooze 10 min buttons.

Library: `windows-toasts` (WinRT through pywinrt, MIT). It's pure Python on top of the `winrt-*` wheels, so
PyInstaller bundles it like any other package (monkey.spec collects `winrt` and the selftest imports it).

Identity: a toast from an unpackaged app (Monkey is a PyInstaller exe installed by Velopack) needs an
AppUserModelID that Windows knows. Monkey registers one for the current user under
HKCU\\Software\\Classes\\AppUserModelId\\<AUMID> (DisplayName "Monkey" + icon), which Windows accepts without a
Start-menu shortcut. The ID is Velopack's default process ID ("velopack.<packId>"), so taskbar and notifications
agree when Velopack sets it. No COM activator is registered: a click reaches Monkey while he's running (also from
the tray, also from Action Center); a toast left over from before a restart just opens nothing.

Everything Windows-specific is behind `ToastBackend`, so the dispatcher logic is tested on Linux with a fake, and
on other systems the backend reports "not available" and does nothing.
"""
from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol

from . import due_phrase

log = logging.getLogger("monkey.notify")

AUMID = "velopack.Monkey"
APP_NAME = "Monkey"
GROUP = "todo"
SNOOZE_MIN = 10


class ToastBackend(Protocol):
    available: bool
    reason: str

    def show(self, tag: str, lines: list[str], *, high: bool, expires: datetime | None,
             buttons: list[tuple[str, str]], on_click: Callable[[str], None]) -> None: ...

    def remove(self, tag: str) -> None: ...


class UnavailableBackend:
    """Non-Windows (Linux CI, dev) or the library is missing: a clear status, no notifications."""

    def __init__(self, reason: str):
        self.available = False
        self.reason = reason

    def show(self, *a, **k) -> None:  # noqa: D401 - no-op
        return None

    def remove(self, tag: str) -> None:
        return None


def register_aumid(aumid: str = AUMID, name: str = APP_NAME, icon: Path | None = None) -> None:
    """Tell Windows who sends the toasts (name + icon in the notification header). Per user, no admin needed."""
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, f"SOFTWARE\\Classes\\AppUserModelId\\{aumid}") as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, name)
        if icon is not None and icon.exists():
            winreg.SetValueEx(k, "IconUri", 0, winreg.REG_SZ, str(icon.resolve()))


def unregister_aumid(aumid: str = AUMID) -> None:
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"SOFTWARE\\Classes\\AppUserModelId\\{aumid}")
    except FileNotFoundError:
        pass


class WinToastBackend:  # pragma: no cover - needs Windows; covered by the Windows CI job and the exe selftest
    """windows-toasts on Windows 10/11."""

    def __init__(self, aumid: str = AUMID, icon: Path | None = None):
        self.available = False
        self.reason = ""
        self._aumid = aumid
        self._toasts: dict[str, object] = {}       # keep shown toasts (and their callbacks) alive while Monkey runs
        try:
            from windows_toasts import InteractableWindowsToaster

            register_aumid(aumid, APP_NAME, icon)
            self._toaster = InteractableWindowsToaster(APP_NAME, notifierAUMID=aumid)
            self.available = True
            self.reason = "Windows notifications are ready."
        except Exception as exc:  # noqa: BLE001
            self.reason = f"Windows notifications aren't available here ({type(exc).__name__})."
            log.warning("windows notifications unavailable: %s", type(exc).__name__)

    def build(self, tag: str, lines: list[str], *, high: bool, expires: datetime | None,
              buttons: list[tuple[str, str]], on_click: Callable[[str], None]):
        from windows_toasts import Toast, ToastButton, ToastScenario

        t = Toast(text_fields=lines[:3], group=GROUP, expiration_time=expires,
                  scenario=ToastScenario.Reminder if high else ToastScenario.Default,   # high: stays until handled
                  actions=[ToastButton(label, args) for label, args in buttons],
                  on_activated=lambda ev: on_click(str(getattr(ev, "arguments", "") or "")))
        t.tag = tag                     # the body's click arguments are the tag; one toast per item (a new one replaces it)
        return t

    def show(self, tag, lines, *, high, expires, buttons, on_click) -> None:
        t = self.build(tag, lines, high=high, expires=expires, buttons=buttons, on_click=on_click)
        self._toasts[tag] = t
        while len(self._toasts) > 200:
            self._toasts.pop(next(iter(self._toasts)))
        self._toaster.show_toast(t)

    def remove(self, tag: str) -> None:
        t = self._toasts.pop(tag, None)
        if t is not None:
            self._toaster.remove_toast(t)


def default_backend(icon: Path | None = None) -> ToastBackend:
    if sys.platform != "win32":
        return UnavailableBackend("Windows notifications only work on Windows.")
    return WinToastBackend(AUMID, icon)


def monkey_in_front() -> bool:
    """True when one of Monkey's own windows is the foreground window (so the in-app note is in plain view)."""
    if sys.platform != "win32":
        return False
    try:  # pragma: no cover - Windows only
        import ctypes
        import os
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == os.getpid()
    except Exception:  # noqa: BLE001
        return False


@dataclass
class Handlers:
    """What a click does: the same actions as the in-app reminder's buttons."""
    open: Callable[[str], None]          # show Monkey's window and the To-do panel
    done: Callable[[str], None]
    snooze: Callable[[str, int], None]


class WindowsNotifier:
    """Decides whether a due reminder becomes a Windows notification, and routes the clicks back.

    Called from `MonkeyApp.todo_tick`, which already fires each item once per due time (and again only after a
    snooze ends), so this never repeats on its own. Skipped when the in-app note is on and Monkey's window is the
    foreground window: the owner is looking at the same reminder already."""

    def __init__(self, settings: Callable, handlers: Handlers, backend: ToastBackend | None = None,
                 in_front: Callable[[], bool] = monkey_in_front, icon: Path | None = None):
        self._settings = settings
        self._handlers = handlers
        self._backend = backend
        self._icon = icon
        self._in_front = in_front
        self._lock = threading.Lock()
        self.shown: list[str] = []          # item ids, newest last (Settings status, tests)
        self.last_error = ""

    @property
    def backend(self) -> ToastBackend:
        with self._lock:
            if self._backend is None:
                self._backend = default_backend(self._icon)
            return self._backend

    def enabled(self) -> bool:
        return bool(getattr(self._settings(), "todo_windows_notify", False))

    def describe(self) -> dict:
        b = self.backend
        return {"enabled": self.enabled(), "available": b.available,
                "detail": self.last_error or b.reason}

    def notify(self, item: dict, now: datetime, *, in_app: bool) -> str:
        """'shown', 'off', 'unavailable', 'skipped (Monkey is in front)' or 'failed'."""
        if not self.enabled():
            return "off"
        b = self.backend
        if not b.available:
            return "unavailable"
        if in_app and self._in_front():
            return "skipped (Monkey is in front)"
        return self._show(item, now)

    def test(self, now: datetime | None = None) -> dict:
        """Settings → Send a test Windows notification."""
        b = self.backend
        if not b.available:
            return {"ok": False, "error": b.reason}
        now = now or datetime.now()
        res = self._show({"id": "test", "text": "Test reminder from Monkey", "due": now.strftime("%Y-%m-%dT%H:%M"),
                          "priority": "normal"}, now, test=True)
        return {"ok": res == "shown", "error": self.last_error if res != "shown" else ""}

    def _show(self, item: dict, now: datetime, test: bool = False) -> str:
        iid = str(item["id"])
        lines = [str(item.get("text", "")), "Reminder · " + due_phrase(item, now)
                 + (" · high priority" if item.get("priority") == "high" else "")]
        buttons = [] if test else [("Done", f"done:{iid}"), (f"Snooze {SNOOZE_MIN} min", f"snooze:{iid}")]
        try:
            self.backend.show(iid, lines, high=item.get("priority") == "high" and not test,
                              expires=now + timedelta(hours=12), buttons=buttons,
                              on_click=lambda args: self.on_click(args, iid))
        except Exception as exc:  # noqa: BLE001 - a broken toast must not stop the in-app reminder
            self.last_error = f"The last Windows notification failed ({type(exc).__name__})."
            log.warning("windows notification failed: %s", type(exc).__name__)
            return "failed"
        self.last_error = ""
        self.shown.append(iid)
        del self.shown[:-50]
        return "shown"

    def on_click(self, args: str, iid: str) -> None:
        """'done:<id>' / 'snooze:<id>' from a button; anything else (the body) opens the To-do panel."""
        try:
            kind, _, target = (args or "").partition(":")
            if kind == "done" and target:
                self._handlers.done(target)
            elif kind == "snooze" and target:
                self._handlers.snooze(target, SNOOZE_MIN)
            elif iid != "test":
                self._handlers.open(iid)
            else:
                self._handlers.open("")
        except Exception:  # noqa: BLE001 - runs on a WinRT thread: never raise into it
            log.warning("windows notification click failed", exc_info=True)

    def retract(self, item_id: str) -> None:
        """The item was done, snoozed or deleted in Monkey: take its notification out of Action Center."""
        if item_id not in self.shown:
            return
        self.shown = [x for x in self.shown if x != item_id]
        try:
            self.backend.remove(item_id)
        except Exception:  # noqa: BLE001
            log.debug("couldn't remove a windows notification", exc_info=True)

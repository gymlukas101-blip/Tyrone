"""Automatic updates via Velopack + GitHub Releases (public repo).

On startup and every few hours: check GitHub Releases for a newer version, download it
(deltas when possible) in the background, then tell the UI "update ready". Applying it
restarts Monkey into the new version in a few seconds. Memory, settings and keys live in
%APPDATA%\\Monkey and Windows Credential Manager, so updates never touch them.

When Monkey isn't installed through Velopack (dev runs, the old Inno Setup installer),
Velopack's UpdateManager raises; the updater then reports "not available" instead.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

REPO_URL = "https://github.com/gymlukas101-blip/Tyrone"
CHECK_EVERY_S = 6 * 3600


class Updater:
    def __init__(self, emit: Callable[[str, dict], None], enabled: Callable[[], bool] = lambda: True,
                 manager_factory: Callable[[], object] | None = None):
        self.emit = emit
        self.enabled = enabled
        self._factory = manager_factory or self._default_factory
        self._mgr = None
        self._pending = None          # UpdateInfo that has been downloaded
        self.status = "idle"          # idle | checking | up_to_date | downloading | ready | unavailable | error
        self.detail = ""
        self.available_version = ""
        self._lock = threading.Lock()

    @staticmethod
    def _default_factory():
        import velopack

        return velopack.UpdateManager(velopack.GithubSource(REPO_URL, None, False))

    def _manager(self):
        if self._mgr is None:
            try:
                self._mgr = self._factory()
            except Exception as exc:  # noqa: BLE001 - not a Velopack install
                self.status, self.detail = "unavailable", str(exc).splitlines()[0][:200]
                return None
        return self._mgr

    def current_version(self) -> str:
        m = self._manager()
        try:
            return str(m.get_current_version()) if m else ""
        except Exception:  # noqa: BLE001
            return ""

    def state(self) -> dict:
        return {"status": self.status, "detail": self.detail, "current": self.current_version(),
                "available": self.available_version, "enabled": bool(self.enabled())}

    def check(self, download: bool = True) -> dict:
        """Check (and by default download) an update. Safe to call from any thread."""
        with self._lock:
            m = self._manager()
            if m is None:
                return self.state()
            try:
                self.status = "checking"
                info = m.check_for_updates()
                if not info:
                    self.status, self.available_version = "up_to_date", ""
                    return self.state()
                self.available_version = str(info.TargetFullRelease.Version)
                if download:
                    self.status = "downloading"
                    self.emit("update", self.state())
                    m.download_updates(info)
                    self._pending = info
                    self.status = "ready"
                    self.emit("update", self.state())
                return self.state()
            except Exception as exc:  # noqa: BLE001 - offline, GitHub rate limit, etc.
                self.status, self.detail = "error", str(exc).splitlines()[0][:200]
                log.warning("update check failed: %s", exc)
                return self.state()

    def apply(self) -> dict:
        """Restart into the downloaded version (the process exits on success)."""
        m = self._manager()
        if m is None or self._pending is None:
            return {**self.state(), "error": "No update has been downloaded yet."}
        m.apply_updates_and_restart(self._pending)
        return self.state()

    def start_background(self) -> None:
        def loop():
            time.sleep(20)  # let the app finish starting
            while True:
                if self.enabled() and self.status not in ("ready", "unavailable"):
                    self.check(download=True)
                time.sleep(CHECK_EVERY_S)

        threading.Thread(target=loop, name="updater", daemon=True).start()


FIRST_RUN = threading.Event()   # set when Velopack says this is the first launch after installing


def velopack_startup() -> None:
    """Must run first thing in the frozen app (handles install/update/uninstall hooks)."""
    try:
        import velopack

        velopack.App().on_first_run(lambda *_: FIRST_RUN.set()).run()
    except Exception as exc:  # noqa: BLE001 - dev runs / missing package
        log.debug("velopack startup skipped: %s", exc)

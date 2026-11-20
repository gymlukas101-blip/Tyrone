"""Clean exits, so updates can replace the app folder.

Velopack swaps %LOCALAPPDATA%\\Monkey\\current for the new version only if nothing in it is still running. Monkey
used to exit with os._exit(), which skipped closing the computer-task browser, so Playwright's driver (node.exe, which
lives inside the app folder) outlived Monkey, kept the folder locked, and every "Restart & update" came back on the old
version. Every exit path now goes through release_for_exit(), and startup clears such leftovers from earlier runs.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("monkey.lifecycle")


def install_dir() -> Path | None:
    """The folder the frozen app runs from (None when running from source)."""
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None


def release_for_exit(app=None, timeout: float = 6.0, keep: set[int] | None = None) -> int:
    """Close what Monkey started: computer-task sessions (gracefully, bounded), then any child processes left
    (except `keep`, e.g. the helper that relaunches Monkey). Returns how many child processes had to be ended."""
    if app is not None and getattr(app, "automation", None) is not None:
        th = threading.Thread(target=lambda: _quiet(app.automation.shutdown), daemon=True)
        th.start()
        th.join(timeout)
    return kill_children(keep=keep)


def spawn_detached(args: list[str], delay_s: float = 2.0):
    """Start `args` after `delay_s`, in a process that outlives Monkey (its own process group / session)."""
    import subprocess

    if sys.platform == "win32":
        # No DETACHED_PROCESS: combined with CREATE_NO_WINDOW it's ignored at best, and a fully detached cmd.exe gets
        # no hidden console for `timeout` to read, which then fails instantly. A new process group outlives our exit.
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200) | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        cmd = f'cmd /c timeout /t {int(delay_s)} /nobreak >nul & start "" {subprocess.list2cmdline(args)}'
        return subprocess.Popen(cmd, shell=False, creationflags=flags, close_fds=True)
    return subprocess.Popen(["sh", "-c", f'sleep {delay_s}; exec "$@"', "sh", *args], start_new_session=True,
                            close_fds=True)


def kill_children(grace: float = 2.0, keep: set[int] | None = None) -> int:
    try:
        import psutil
    except ImportError:
        return 0
    try:
        keep = set(keep or ())
        kids = [p for p in psutil.Process().children(recursive=True) if p.pid not in keep]
        for k in list(kids):                           # nor anything the kept helper started
            if any(a.pid in keep for a in _ancestors(k)):
                kids.remove(k)
    except Exception:  # noqa: BLE001
        return 0
    for p in kids:
        _quiet(p.terminate)
    _, alive = psutil.wait_procs(kids, timeout=grace)
    for p in alive:
        _quiet(p.kill)
    return len(kids)


def _ancestors(p) -> list:
    try:
        return p.parents()
    except Exception:  # noqa: BLE001
        return []


def kill_leftovers(folder: Path | None = None) -> list[str]:
    """Processes still running from Monkey's own app folder after an earlier run (e.g. an orphaned node.exe).
    Never touches another Monkey.exe (the single-instance lock handles that) or anything outside the folder."""
    folder = folder or install_dir()
    if folder is None:
        return []
    try:
        import psutil
    except ImportError:
        return []
    me, ended = os.getpid(), []
    root = str(folder.resolve()).lower()
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            exe = (p.info.get("exe") or "").lower()
            if not exe.startswith(root + os.sep) or p.info["pid"] == me:
                continue
            if (p.info.get("name") or "").lower() in ("monkey.exe", "update.exe"):
                continue
            p.kill()
            ended.append(p.info.get("name") or str(p.info["pid"]))
        except Exception:  # noqa: BLE001 - gone already, or not ours to touch
            continue
    if ended:
        log.info("ended leftover processes from the app folder: %s", ended)
    return ended


# ---- did the last update actually install? ------------------------------------------------------------------------
def record_update_attempt(data_dir: Path, from_version: str, to_version: str) -> None:
    try:
        (Path(data_dir) / "update-attempt.json").write_text(json.dumps(
            {"from": from_version, "to": to_version, "ts": time.time()}), "utf-8")
    except OSError:
        pass


def check_update_attempt(data_dir: Path, current: str) -> str:
    """'' if fine; otherwise a message saying the update didn't install (and the attempt is cleared)."""
    p = Path(data_dir) / "update-attempt.json"
    try:
        d = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return ""
    _quiet(p.unlink)
    if time.time() - float(d.get("ts", 0)) > 3600 or not d.get("to") or current == d["to"]:
        return ""
    if _ver(current) >= _ver(d["to"]):
        return ""
    return (f"The update to {d['to']} didn't install (Monkey is still {current}): something was keeping Monkey's "
            "folder busy. I've cleaned that up, so press Restart & update once more.")


def _ver(v: str) -> tuple:
    out = []
    for part in str(v).split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


def _quiet(fn) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001
        pass

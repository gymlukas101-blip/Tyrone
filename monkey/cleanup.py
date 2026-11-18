"""Remove old Monkey/Tyrone installs and downloads after switching to the Velopack install.

What it looks for (and nothing else):
  * old Inno Setup installs (per-user, AppId from installer/monkey.iss) - uninstalled silently
  * orphaned old app folders %LocalAppData%\\Programs\\Monkey | Tyrone
  * old Startup-folder shortcuts that point into those folders
  * old downloads at the top level of the Downloads folder, by exact name pattern
    (MonkeySetup*.zip/.exe, TyroneSetup*.zip/.exe, Monkey-win-Setup*.exe, Monkey-win-Portable*.zip,
     and MonkeySetup*/TyroneSetup* folders that contain only .exe/.zip files)

It never touches %APPDATA%\\Monkey (memory, settings), Windows Credential Manager (keys),
or the current Velopack install (%LocalAppData%\\Monkey). Downloads go to the Recycle Bin.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

# AppId of the old Inno Setup installer (installer/monkey.iss); same GUID for "Tyrone" and "Monkey".
INNO_APP_ID = "{6E2C3F1B-6B7A-4E2B-9D4C-7A1F0C5E9A11}"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{INNO_APP_ID}_is1"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
DOWNLOADS_GUID = "{374DE290-123F-4565-9164-39C4925E467B}"

FILE_PATTERNS = ["monkeysetup*.zip", "monkeysetup*.exe", "tyronesetup*.zip", "tyronesetup*.exe",
                 "monkey-win-setup*.exe", "monkey-win-portable*.zip"]
FOLDER_PATTERNS = ["monkeysetup*", "tyronesetup*"]
APP_NAMES = ("Monkey", "Tyrone")


@dataclass
class Item:
    kind: str            # "app" | "folder" | "shortcut" | "download"
    label: str
    path: str = ""
    uninstall: str = ""  # Inno uninstaller command (kind == "app")
    status: str = "found"
    detail: str = ""


@dataclass
class Plan:
    items: list[Item] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"items": [asdict(i) for i in self.items], "count": len(self.items)}


# ----------------------------------------------------------------------------- discovery
def _winreg_reader(hive_name: str, key: str) -> dict | None:
    """Read all values of a registry key; None if missing or not on Windows."""
    if sys.platform != "win32":
        return None
    import winreg

    hive = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}[hive_name]
    try:
        with winreg.OpenKey(hive, key) as k:
            out, i = {}, 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[name] = value
                i += 1
            return out
    except OSError:
        return None


def find_legacy_installs(reg: Callable[[str, str], dict | None] = _winreg_reader,
                         local_appdata: Path | None = None) -> list[Item]:
    items: list[Item] = []
    seen_dirs: set[str] = set()
    for hive in ("HKCU", "HKLM"):
        vals = reg(hive, UNINSTALL_KEY)
        if not vals or not vals.get("UninstallString"):
            continue
        name = vals.get("DisplayName", "Monkey")
        ver = vals.get("DisplayVersion", "")
        loc = str(vals.get("InstallLocation", "")).rstrip("\\/")
        items.append(Item("app", f"Old app: {name} {ver} (previous installer)".replace("  ", " ").strip(),
                          path=loc, uninstall=vals["UninstallString"]))
        if loc:
            seen_dirs.add(os.path.normcase(os.path.normpath(loc)))
    base = local_appdata or Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    for app in APP_NAMES:
        d = base / "Programs" / app
        if d.is_dir() and any((d / f"{n}.exe").exists() for n in APP_NAMES):
            if os.path.normcase(os.path.normpath(str(d))) not in seen_dirs:
                items.append(Item("folder", f"Leftover app folder: Programs\\{app}", path=str(d)))
    return items


def downloads_dir(reg: Callable[[str, str], dict | None] = _winreg_reader) -> Path:
    vals = reg("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") or {}
    raw = vals.get(DOWNLOADS_GUID)
    if raw:
        return Path(os.path.expandvars(str(raw)))
    return Path.home() / "Downloads"


def _matches(name: str, patterns: list[str]) -> bool:
    n = name.lower()
    return any(fnmatch.fnmatch(n, p) for p in patterns)


def find_legacy_downloads(folder: Path) -> list[Item]:
    items: list[Item] = []
    if not folder.is_dir():
        return items
    for p in sorted(folder.iterdir()):
        try:
            if p.is_file() and _matches(p.name, FILE_PATTERNS):
                items.append(Item("download", f"Download: {p.name}", path=str(p)))
            elif p.is_dir() and _matches(p.name, FOLDER_PATTERNS):
                contents = [c for c in p.rglob("*") if c.is_file()]
                if contents and all(c.suffix.lower() in (".exe", ".zip") for c in contents):
                    items.append(Item("download", f"Unzipped folder: {p.name}\\", path=str(p)))
        except OSError:
            continue
    return items


def find_startup_shortcuts(startup: Path | None = None) -> list[Item]:
    """Old 'start with Windows' shortcuts made by the previous installer (they point into Programs\\Monkey|Tyrone)."""
    startup = startup or Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"
    items = []
    for app in APP_NAMES:
        lnk = startup / f"{app}.lnk"
        try:
            raw = lnk.read_bytes()
        except OSError:
            continue
        text = (raw.decode("utf-16-le", "ignore") + raw.decode("latin-1", "ignore")).lower()
        if any(f"programs\\{a.lower()}\\" in text for a in APP_NAMES):
            items.append(Item("shortcut", f"Old startup shortcut: {lnk.name}", path=str(lnk)))
    return items


def plan_cleanup(reg=_winreg_reader, local_appdata: Path | None = None, downloads: Path | None = None,
                 startup: Path | None = None) -> Plan:
    items = (find_legacy_installs(reg, local_appdata) + find_startup_shortcuts(startup)
             + find_legacy_downloads(downloads or downloads_dir(reg)))
    return Plan(items)


# ----------------------------------------------------------------------------- actions
def _new_install_dir() -> str:
    return os.path.normcase(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Monkey"))


def close_legacy_processes(install_dirs: list[str], processes=None, me: int | None = None) -> int:
    """End processes running from old install dirs (never this process or the new install)."""
    if processes is None:
        try:
            import psutil
        except ImportError:
            return 0
        processes = psutil.process_iter(["pid", "exe"])
    me = os.getpid() if me is None else me
    dirs = [os.path.normcase(os.path.normpath(d)) + os.sep for d in install_dirs if d]
    new_dir = _new_install_dir() + os.sep
    killed = 0
    for proc in processes:
        try:
            info = proc.info if hasattr(proc, "info") else proc
            exe = os.path.normcase(os.path.normpath(info.get("exe") or ""))
            if not exe or info.get("pid") == me or exe.startswith(new_dir):
                continue
            if any(exe.startswith(d) for d in dirs):
                proc.kill()
                killed += 1
        except Exception:  # noqa: BLE001 - process vanished / access denied
            continue
    return killed


def _default_run(args: list[str]) -> int:
    return subprocess.run(args, shell=False, timeout=60).returncode  # noqa: S603


def uninstaller_exe(uninstall_string: str) -> str:
    """'"C:\\...\\unins000.exe"' or 'C:\\...\\unins000.exe /SILENT' -> path to the exe."""
    s = uninstall_string.strip()
    if s.startswith('"'):
        return s[1:s.index('"', 1)] if '"' in s[1:] else s.strip('"')
    return s.split(" /")[0].strip()


def _default_trash(path: str) -> None:
    from send2trash import send2trash

    send2trash(path)


def clean(plan: Plan, *, run: Callable[[list[str]], int] = _default_run, trash: Callable[[str], None] = _default_trash,
          kill: Callable[[list[str]], int] = close_legacy_processes) -> Plan:
    """Carry out the plan. Each item gets status ok / error; one failure never stops the rest."""
    app_dirs = [i.path for i in plan.items if i.kind in ("app", "folder") and i.path]
    try:
        kill(app_dirs)
    except Exception:  # noqa: BLE001
        pass
    for item in plan.items:
        try:
            if item.kind == "app":
                code = run([uninstaller_exe(item.uninstall), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
                item.status, item.detail = ("ok", "uninstalled") if code == 0 else ("error", f"uninstaller exit {code}")
            elif item.kind == "folder":
                shutil.rmtree(item.path)
                item.status, item.detail = "ok", "removed"
            elif item.kind == "shortcut":
                Path(item.path).unlink()
                item.status, item.detail = "ok", "removed"
            elif item.kind == "download":
                trash(item.path)
                item.status, item.detail = "ok", "moved to Recycle Bin"
        except Exception as exc:  # noqa: BLE001
            item.status, item.detail = "error", str(exc)[:200]
    return plan


# ----------------------------------------------------------------------------- start with Windows
def set_autostart(enabled: bool, exe_path: str | None = None, reg_set=None, reg_del=None) -> bool:
    """Add/remove HKCU Run entry 'Monkey' pointing at the Velopack launcher."""
    if reg_set is None or reg_del is None:
        if sys.platform != "win32":
            return False
        import winreg

        def reg_set(name, value):  # noqa: F811
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

        def reg_del(name):  # noqa: F811
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, name)
            except OSError:
                pass
    if enabled:
        exe = exe_path or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Monkey", "Monkey.exe")
        reg_set("Monkey", f'"{exe}"')
    else:
        reg_del("Monkey")
    return True

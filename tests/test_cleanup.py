import os
from pathlib import Path

from monkey import cleanup
from monkey.cleanup import (INNO_APP_ID, Item, Plan, clean, close_legacy_processes, find_legacy_downloads,
                            find_legacy_installs, plan_cleanup, set_autostart, uninstaller_exe)

KEY = cleanup.UNINSTALL_KEY


def fake_reg(table):
    return lambda hive, key: table.get((hive, key))


def test_finds_inno_install_and_orphan_folder(tmp_path):
    progs = tmp_path / "Programs"
    (progs / "Monkey").mkdir(parents=True)
    (progs / "Monkey" / "Monkey.exe").write_bytes(b"x")
    (progs / "Tyrone").mkdir()
    (progs / "Tyrone" / "Tyrone.exe").write_bytes(b"x")
    reg = fake_reg({("HKCU", KEY): {"DisplayName": "Monkey", "DisplayVersion": "0.1.0-dev",
                                     "InstallLocation": str(progs / "Monkey") + "\\",
                                     "UninstallString": f'"{progs / "Monkey" / "unins000.exe"}"'}})
    items = find_legacy_installs(reg, tmp_path)
    kinds = [(i.kind, Path(i.path).name) for i in items]
    assert ("app", "Monkey") in kinds and ("folder", "Tyrone") in kinds
    assert ("folder", "Monkey") not in kinds  # covered by its uninstaller
    assert INNO_APP_ID in KEY


def test_download_patterns_are_exact(tmp_path):
    for name in ["MonkeySetup.zip", "monkeysetup-0.1.0-dev.exe", "TyroneSetup.zip", "Monkey-win-Setup (1).exe",
                 "Monkey-win-Portable.zip", "my-notes.zip", "Monkey report.docx", "setup.exe"]:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "MonkeySetup").mkdir()
    (tmp_path / "MonkeySetup" / "MonkeySetup-0.1.0-dev.exe").write_bytes(b"x")
    (tmp_path / "TyroneSetup (2)").mkdir()
    (tmp_path / "TyroneSetup (2)" / "TyroneSetup.exe").write_bytes(b"x")
    (tmp_path / "MonkeySetup-mixed").mkdir()
    (tmp_path / "MonkeySetup-mixed" / "a.exe").write_bytes(b"x")
    (tmp_path / "MonkeySetup-mixed" / "essay.docx").write_bytes(b"x")  # user file -> folder kept
    names = sorted(Path(i.path).name for i in find_legacy_downloads(tmp_path))
    assert names == sorted(["MonkeySetup.zip", "monkeysetup-0.1.0-dev.exe", "TyroneSetup.zip",
                            "Monkey-win-Setup (1).exe", "Monkey-win-Portable.zip", "MonkeySetup", "TyroneSetup (2)"])


def test_startup_shortcut_detection(tmp_path):
    (tmp_path / "Monkey.lnk").write_bytes("C:\\Users\\me\\AppData\\Local\\Programs\\Monkey\\Monkey.exe".encode("utf-16-le"))
    (tmp_path / "Tyrone.lnk").write_bytes("C:\\elsewhere\\thing.exe".encode("utf-16-le"))
    plan = plan_cleanup(fake_reg({}), tmp_path / "none", tmp_path / "dl", tmp_path)
    assert [Path(i.path).name for i in plan.items] == ["Monkey.lnk"]


def test_uninstaller_exe_parsing():
    assert uninstaller_exe('"C:\\A B\\unins000.exe"') == "C:\\A B\\unins000.exe"
    assert uninstaller_exe("C:\\A\\unins000.exe /SILENT") == "C:\\A\\unins000.exe"


def test_clean_runs_everything_and_survives_failures(tmp_path):
    orphan = tmp_path / "Programs" / "Tyrone"
    orphan.mkdir(parents=True)
    plan = Plan([
        Item("app", "Old app", path="C:\\old", uninstall='"C:\\old\\unins000.exe"'),
        Item("folder", "orphan", path=str(orphan)),
        Item("download", "zip", path="C:\\dl\\MonkeySetup.zip"),
        Item("download", "locked", path="C:\\dl\\TyroneSetup.zip"),
    ])
    calls, trashed, killed = [], [], []

    def trash(p):
        if "Tyrone" in p:
            raise PermissionError("in use")
        trashed.append(p)

    clean(plan, run=lambda args: calls.append(args) or 0, trash=trash, kill=lambda dirs: killed.append(dirs) or 0)
    assert calls == [["C:\\old\\unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]]
    assert not orphan.exists() and trashed == ["C:\\dl\\MonkeySetup.zip"]
    assert [i.status for i in plan.items] == ["ok", "ok", "ok", "error"]
    assert killed and "C:\\old" in killed[0]


class P:
    def __init__(self, pid, exe):
        self.info = {"pid": pid, "exe": exe}
        self.killed = False

    def kill(self):
        self.killed = True


def test_process_filter_spares_self_and_new_install(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    old = str(tmp_path / "Programs" / "Monkey")
    procs = [P(1, os.path.join(old, "Monkey.exe")), P(2, os.path.join(old, "Monkey.exe")),
             P(3, str(tmp_path / "Monkey" / "current" / "Monkey.exe")), P(4, "/usr/bin/other")]
    n = close_legacy_processes([old], processes=procs, me=2)
    assert n == 1 and [p.killed for p in procs] == [True, False, False, False]


def test_autostart_set_and_remove():
    store = {}
    set_autostart(True, "C:\\Users\\me\\AppData\\Local\\Monkey\\Monkey.exe",
                  reg_set=lambda k, v: store.__setitem__(k, v), reg_del=lambda k: store.pop(k, None))
    assert store == {"Monkey": '"C:\\Users\\me\\AppData\\Local\\Monkey\\Monkey.exe"'}
    set_autostart(False, reg_set=lambda k, v: None, reg_del=lambda k: store.pop(k, None))
    assert store == {}

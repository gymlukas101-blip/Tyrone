"""Move to a new PC: one encrypted file carries memory, chats, settings, voice, Garmin, skills and (opt-in) keys;
import is staged and swapped in at the next start."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import zipfile

import pytest
from cryptography.fernet import Fernet

from monkey.memory import export as X


def make_old_pc(root):
    d = root / "old"
    (d / "memory" / "memories").mkdir(parents=True)
    (d / "memory" / "memories" / "profile.md").write_text("- likes bananas\n", encoding="utf-8")
    (d / "memory" / "backups" / "import-1").mkdir(parents=True)
    (d / "memory" / "backups" / "import-1" / "profile.md").write_text("old\n", encoding="utf-8")
    (d / "settings.json").write_text(json.dumps({"voice_volume": 140, "memory_dir_override": "C:/old/OneDrive"}))
    (d / "voice").mkdir()
    (d / "voice" / "monkey-ref.wav").write_bytes(b"RIFF....WAVE")
    (d / "garmin").mkdir()
    (d / "garmin" / "garmin_tokens.json").write_text("{}")
    (d / "skills" / "mine").mkdir(parents=True)
    (d / "skills" / "mine" / "SKILL.md").write_text("---\nname: mine\n---\n")
    (d / "secrets.dat").write_text('{"anthropic": "dpapi:xxx"}')
    (d / "monkey.log").write_text("log")
    (d / "cache").mkdir()
    (d / "cache" / "big.bin").write_bytes(b"x" * 10)
    db = sqlite3.connect(d / "monkey.db")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE messages (t TEXT)")
    db.execute("INSERT INTO messages VALUES ('hello from the old pc')")
    db.commit()
    return d, db      # db stays open: its last write is still in the WAL file, like a running Monkey


def names_in(bundle, password):
    with X._open(bundle, password) as z:
        return set(z.namelist()), z


def test_round_trip_with_keys(tmp_path):
    old, live = make_old_pc(tmp_path)
    assert (old / "monkey.db-wal").exists()
    b = X.export_bundle(old, old / "memory", tmp_path / "t.monkey", "correct horse",
                        keys={"anthropic": "sk-ant-1", "google_client": '{"installed": {}}', "export_password": "no",
                              "fish": ""}, version="0.3.36")
    live.close()
    names, _ = names_in(b, "correct horse")
    assert {"settings.json", "monkey.db", "voice/monkey-ref.wav", "garmin/garmin_tokens.json",
            "skills/mine/SKILL.md", "memory/memories/profile.md", "memory/backups/import-1/profile.md",
            "keys.json", "manifest.json"} <= names
    assert not any(n.startswith(("cache", "secrets")) or n.endswith((".log", "-wal", "-shm")) for n in names)

    new = tmp_path / "new"
    new.mkdir()
    staged = X.stage_import(b, new, "correct horse")
    assert staged["keys"] == {"anthropic": "sk-ant-1", "google_client": '{"installed": {}}'}
    assert staged["manifest"]["keys"] == ["anthropic", "google_client"] and staged["manifest"]["version"] == "0.3.36"
    assert not (new / "settings.json").exists() and X.pending(new)          # nothing live touched yet

    done = X.apply_pending_transfer(new)
    assert not (new / X.INCOMING).exists() and not X.pending(new)
    assert (new / "memory" / "memories" / "profile.md").read_text(encoding="utf-8") == "- likes bananas\n"
    assert (new / "voice" / "monkey-ref.wav").exists() and (new / "skills" / "mine" / "SKILL.md").exists()
    s = json.loads((new / "settings.json").read_text())
    assert s["voice_volume"] == 140 and s["memory_dir_override"] == ""    # old PC's path dropped
    rows = sqlite3.connect(new / "monkey.db").execute("SELECT t FROM messages").fetchall()
    assert rows == [("hello from the old pc",)]                            # WAL contents made it
    assert done["keys"] == ["anthropic", "google_client"] and json.loads((new / "last_transfer.json").read_text())


def test_keys_left_out_when_unchecked(tmp_path):
    old, live = make_old_pc(tmp_path)
    b = X.export_bundle(old, old / "memory", tmp_path / "t.monkey", "correct horse")
    live.close()
    names, _ = names_in(b, "correct horse")
    assert "keys.json" not in names
    assert X.stage_import(b, tmp_path / "n", "correct horse")["keys"] == {}


def test_wrong_password_and_short_password(tmp_path):
    old, live = make_old_pc(tmp_path)
    with pytest.raises(ValueError, match="8 characters"):
        X.export_bundle(old, old / "memory", tmp_path / "t.monkey", "short")
    b = X.export_bundle(old, old / "memory", tmp_path / "t.monkey", "correct horse")
    live.close()
    with pytest.raises(ValueError, match="Wrong password"):
        X.stage_import(b, tmp_path / "n", "nope nope nope")
    assert not (tmp_path / "n" / X.INCOMING).exists()


def _bundle_with(tmp_path, entries: dict[str, bytes], magic=X.MAGIC2, password="correct horse"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, data in entries.items():
            z.writestr(n, data)
    salt = os.urandom(X.SALT_LEN)
    p = tmp_path / "evil.monkey"
    p.write_bytes(magic + salt + Fernet(X._key(password, salt)).encrypt(buf.getvalue()))
    return p


@pytest.mark.parametrize("bad", ["../escape.txt", "/abs.txt", "memory/../../x", "secrets.dat", "random.txt",
                                 "voice/../secrets.dat", "C:/Windows/x"])
def test_rejects_unsafe_entries(tmp_path, bad):
    p = _bundle_with(tmp_path, {"settings.json": b"{}", bad: b"x"})
    with pytest.raises(ValueError, match="unexpected"):
        X.stage_import(p, tmp_path / "n", "correct horse")
    assert not (tmp_path / "n" / X.INCOMING).exists()


def test_old_monkey1_files_still_import(tmp_path):
    p = _bundle_with(tmp_path, {"memory/memories/profile.md": b"- hi\n", "settings.json": b"{}"}, magic=X.MAGIC1)
    new = tmp_path / "n"
    files = X.import_bundle(p, new, new / "memory", "correct horse")
    assert "memory/memories/profile.md" in files and (new / "memory" / "memories" / "profile.md").exists()


def test_apply_backs_up_current_files_and_stale_wal(tmp_path):
    new = tmp_path / "n"
    (new / "memory").mkdir(parents=True)
    (new / "memory" / "x.md").write_text("fresh install\n")
    (new / "monkey.db").write_bytes(b"old db")
    (new / "monkey.db-wal").write_bytes(b"stale wal")
    p = _bundle_with(tmp_path, {"memory/y.md": b"moved\n", "monkey.db": b"new db"})
    X.stage_import(p, new, "correct horse")
    done = X.apply_pending_transfer(new)
    backup = tmp_path / "n" / "backups" / done["backup"].split("backups")[-1].strip("/\\")
    assert (backup / "memory" / "x.md").read_text() == "fresh install\n"
    assert (backup / "monkey.db").read_bytes() == b"old db" and (backup / "monkey.db-wal").exists()
    assert not (new / "monkey.db-wal").exists() and (new / "monkey.db").read_bytes() == b"new db"
    assert (new / "memory" / "y.md").exists()


def test_apply_resumes_after_crash_and_ignores_unfinished_unpack(tmp_path):
    new = tmp_path / "n"
    new.mkdir()
    (new / "settings.json").write_text('{"a": 1}')
    p = _bundle_with(tmp_path, {"settings.json": b'{"a": 2}', "voice/v.wav": b"v"})
    X.stage_import(p, new, "correct horse")
    # crash after the first item moved: simulate by doing the first move by hand with the backup ref written
    inc = new / X.INCOMING
    backup = new / "backups" / "pre-transfer-crash"
    (inc / X.BACKUP_REF).write_text(str(backup))
    backup.mkdir(parents=True)
    os.replace(new / "settings.json", backup / "settings.json")
    os.replace(inc / "settings.json", new / "settings.json")
    X.apply_pending_transfer(new)
    assert json.loads((new / "settings.json").read_text()) == {"a": 2}
    assert (new / "voice" / "v.wav").exists() and json.loads((backup / "settings.json").read_text()) == {"a": 1}

    (new / X.INCOMING / "memory").mkdir(parents=True)          # unpack died before .ready was written
    assert X.apply_pending_transfer(new) is None and not (new / X.INCOMING).exists()


def test_never_includes_secrets_even_if_memory_dir_has_one(tmp_path):
    old, live = make_old_pc(tmp_path)
    (old / "memory" / "secrets.dat").write_text("nope")
    b = X.export_bundle(old, old / "memory", tmp_path / "t.monkey", "correct horse")
    live.close()
    names, _ = names_in(b, "correct horse")
    assert not any("secrets" in n for n in names)


def test_app_export_carries_keys_and_import_saves_them(tmp_path, monkeypatch):
    """Through the app API: keys go out from the old PC's store and land in the new PC's store."""
    import sys
    import types
    from types import SimpleNamespace

    from monkey import app as app_mod, keys

    old, live = make_old_pc(tmp_path)
    live.close()
    monkeypatch.setattr(app_mod.Path, "home", staticmethod(lambda: tmp_path / "home"))
    for env in keys.KNOWN_KEYS.values():
        monkeypatch.delenv(env, raising=False)
    try:
        keys.use_store(tmp_path / "old-secrets.dat")
        keys.set("anthropic", "sk-ant-old")
        keys.set("calendar_ics", "https://example.com/a.ics")
        keys.set("export_password", "never-travels")
        old_app = SimpleNamespace(cfg=SimpleNamespace(data_dir=old, memory_dir=old / "memory"))
        r = app_mod.Api(old_app).export_memory("correct horse", True)
        assert r["ok"] and r["keys"] == ["anthropic", "calendar_ics"], r

        keys.use_store(tmp_path / "new-secrets.dat")
        new = tmp_path / "new"
        new.mkdir()
        window = SimpleNamespace(create_file_dialog=lambda *a, **k: [r["path"]])
        new_app = SimpleNamespace(cfg=SimpleNamespace(data_dir=new, memory_dir=new / "memory"),
                                  ui=SimpleNamespace(window=window))
        monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(OPEN_DIALOG=10))
        got = app_mod.Api(new_app).import_memory("correct horse")
        assert got["ok"] and got["restart"] and sorted(got["keys"]) == ["anthropic", "calendar_ics"], got
        assert keys.get("anthropic") == "sk-ant-old" and keys.get("export_password") is None
        assert X.pending(new)
    finally:
        keys.use_store(None)

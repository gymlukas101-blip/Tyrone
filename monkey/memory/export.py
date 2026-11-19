"""Move Monkey to another PC: one encrypted file with everything personal.

The bundle (a .monkey file) is a zip, encrypted with your password (scrypt + Fernet). Format MONKEY2 holds:
  memory/        your memory files (and their import backups)
  settings.json
  monkey.db      chats + memory index, copied with SQLite's online backup (consistent while Monkey runs)
  voice/         the voice reference + vocal set
  garmin/        Garmin sign-in tokens
  skills/        your own skills
  keys.json      optional: your API keys and sign-ins. They normally live in secrets.dat, which Windows DPAPI
                 ties to this PC and this Windows account, so it can't be copied. Inside this bundle they're
                 protected by the bundle password instead.
  manifest.json  what's inside (key NAMES only)
Never included: secrets.dat, logs, cache/, the offline voice pack (re-downloadable).

Import is staged: files are unpacked into <data>/_incoming/ and swapped in on the next start, before settings or
the database are opened (apply_pending_transfer). The files they replace go to <data>/backups/pre-transfer-<time>/.
Old MONKEY1 bundles (memory + settings + db) still import.
"""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC1, MAGIC2 = b"MONKEY1", b"MONKEY2"
SALT_LEN = 16
DIRS = ("voice", "garmin", "skills")             # folders under the data dir that move with you
TOP = {"memory", "settings.json", "monkey.db", "keys.json", "manifest.json", *DIRS}
NEVER = {"secrets.dat", "_incoming", "cache", "voice-pack"}
INCOMING, READY, BACKUP_REF = "_incoming", ".ready", ".backup_dir"
MAX_BYTES = 1_500_000_000                        # unpacked size cap (a normal bundle is a few MB)
NO_KEY = {"export_password"}


def _key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _add_tree(z: zipfile.ZipFile, root: Path, arc: str) -> list[str]:
    out = []
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or any(part in NEVER for part in rel.parts) or p.name.endswith((".log", "-wal", "-shm")):
            continue
        name = f"{arc}/{rel.as_posix()}"
        z.write(p, name)
        out.append(name)
    return out


def _db_snapshot(db: Path, tmp: Path) -> Path | None:
    """A consistent copy of a live SQLite database (includes rows still in the WAL file)."""
    if not db.exists():
        return None
    dest = tmp / "monkey.db"
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    return dest


def export_bundle(data_dir: Path, memory_dir: Path, out_file: Path, password: str,
                  keys: dict[str, str] | None = None, version: str = "") -> Path:
    """Write the encrypted bundle. `keys` (name -> value) is included only if given."""
    if len(password) < 8:
        raise ValueError("Use a password of at least 8 characters")
    data_dir, memory_dir = Path(data_dir), Path(memory_dir)
    buf = io.BytesIO()
    files: list[str] = []
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        files += _add_tree(z, memory_dir, "memory")
        if (data_dir / "settings.json").exists():
            z.write(data_dir / "settings.json", "settings.json")
            files.append("settings.json")
        snap = _db_snapshot(data_dir / "monkey.db", Path(tmp))
        if snap is not None:
            z.write(snap, "monkey.db")
            files.append("monkey.db")
        for d in DIRS:
            files += _add_tree(z, data_dir / d, d)
        keys = {k: v for k, v in (keys or {}).items() if v and k not in NO_KEY}
        if keys:
            z.writestr("keys.json", json.dumps(keys))
        z.writestr("manifest.json", json.dumps({
            "format": 2, "version": version, "created": datetime.now().isoformat(timespec="seconds"),
            "files": files, "keys": sorted(keys)}, indent=1))
    salt = os.urandom(SALT_LEN)
    token = Fernet(_key(password, salt)).encrypt(buf.getvalue())
    del buf
    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(MAGIC2 + salt + token)
    return out_file


def _open(bundle: Path, password: str) -> zipfile.ZipFile:
    raw = Path(bundle).read_bytes()
    magic = raw[:len(MAGIC2)]
    if magic not in (MAGIC1, MAGIC2):
        raise ValueError("That isn't a Monkey transfer file (.monkey).")
    salt = raw[len(magic): len(magic) + SALT_LEN]
    try:
        data = Fernet(_key(password, salt)).decrypt(raw[len(magic) + SALT_LEN:])
    except InvalidToken as exc:
        raise ValueError("Wrong password for this transfer file.") from exc
    return zipfile.ZipFile(io.BytesIO(data))


def _safe_parts(name: str) -> tuple[str, ...] | None:
    p = Path(name.replace("\\", "/"))
    if p.is_absolute() or not p.parts or ".." in p.parts or p.drive or p.parts[0] not in TOP \
            or any(part in NEVER for part in p.parts):
        return None
    return p.parts


def stage_import(bundle: Path, data_dir: Path, password: str) -> dict:
    """Decrypt + check the bundle and unpack it into <data>/_incoming. Returns
    {"files": [...], "keys": {name: value}, "manifest": {...}}. Nothing live is touched until the next start."""
    data_dir = Path(data_dir)
    with _open(bundle, password) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > MAX_BYTES:
            raise ValueError("This transfer file is unexpectedly large; not importing it.")
        bad = [i.filename for i in infos if _safe_parts(i.filename) is None]
        if bad:
            raise ValueError(f"This transfer file has unexpected entries ({bad[0]}); not importing it.")
        keys = json.loads(z.read("keys.json")) if "keys.json" in z.namelist() else {}
        manifest = json.loads(z.read("manifest.json")) if "manifest.json" in z.namelist() else {"format": 1}
        inc = data_dir / INCOMING
        if inc.exists():
            shutil.rmtree(inc)
        inc.mkdir(parents=True)
        files = []
        for info in infos:
            parts = _safe_parts(info.filename)
            if parts[0] in ("keys.json", "manifest.json"):
                continue
            target = inc.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            files.append("/".join(parts))
        (inc / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        (inc / READY).write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")   # written last
    keys = {k: str(v) for k, v in keys.items() if isinstance(k, str) and k not in NO_KEY and v}
    return {"files": files, "keys": keys, "manifest": manifest}


def pending(data_dir: Path) -> bool:
    return (Path(data_dir) / INCOMING / READY).exists()


def _fix_settings(path: Path) -> None:
    """Settings that point at the old PC: the memory folder override (memory now lives in the data folder)."""
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if s.get("memory_dir_override"):
        s["memory_dir_override"] = ""
        path.write_text(json.dumps(s, indent=2), encoding="utf-8")


def apply_pending_transfer(data_dir: Path) -> dict | None:
    """Run at startup before anything opens settings or the database. Swaps the staged files in; what they
    replace goes to backups/pre-transfer-<time>/. Safe to re-run after a crash: it continues where it stopped."""
    data_dir = Path(data_dir)
    inc = data_dir / INCOMING
    if not inc.exists():
        return None
    if not (inc / READY).exists():          # unpacking never finished: throw it away
        shutil.rmtree(inc, ignore_errors=True)
        return None
    ref = inc / BACKUP_REF
    if ref.exists():
        backup = Path(ref.read_text(encoding="utf-8").strip())
    else:
        backup = data_dir / "backups" / f"pre-transfer-{datetime.now():%Y%m%d-%H%M%S}"
        ref.write_text(str(backup), encoding="utf-8")
    backup.mkdir(parents=True, exist_ok=True)
    if (inc / "settings.json").exists():
        _fix_settings(inc / "settings.json")
    moved = []
    for item in sorted(inc.iterdir()):
        if item.name in (READY, BACKUP_REF, "manifest.json"):
            continue
        target = data_dir / item.name
        extra = [data_dir / f"monkey.db{s}" for s in ("-wal", "-shm")] if item.name == "monkey.db" else []
        for old in [target, *extra]:        # a stale WAL next to the new database would corrupt it
            if old.exists():
                dest = backup / old.name
                if dest.exists():
                    shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
                shutil.move(str(old), str(dest))
        shutil.move(str(item), str(target))
        moved.append(item.name)
    manifest = {}
    if (inc / "manifest.json").exists():
        manifest = json.loads((inc / "manifest.json").read_text(encoding="utf-8"))
    result = {"at": datetime.now().isoformat(timespec="seconds"), "backup": str(backup), "moved": moved,
              "from_version": manifest.get("version", ""), "keys": manifest.get("keys", []), "seen": False}
    (data_dir / "last_transfer.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    shutil.rmtree(inc, ignore_errors=True)
    return result


# ---- kept for older callers/tests -------------------------------------------------------------------------
def import_bundle(bundle: Path, data_dir: Path, memory_dir: Path, password: str) -> list[str]:  # noqa: ARG001
    """Stage + apply immediately (only safe when Monkey isn't running, e.g. in tests)."""
    staged = stage_import(bundle, data_dir, password)
    apply_pending_transfer(data_dir)
    return staged["files"]

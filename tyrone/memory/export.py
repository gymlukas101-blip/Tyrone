"""Encrypted export/import of everything personal, for moving to another PC.

The bundle (a .tyrone file) contains memory/, settings.json and tyrone.db, zipped
and encrypted with a password (scrypt + Fernet). API keys are NOT included - they
stay in each PC's Credential Manager.
"""
from __future__ import annotations

import base64
import io
import os
import shutil
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"TYRONE1"
SALT_LEN = 16


def _key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def export_bundle(data_dir: Path, memory_dir: Path, out_file: Path, password: str) -> Path:
    if len(password) < 8:
        raise ValueError("Use a password of at least 8 characters")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in Path(memory_dir).rglob("*"):
            if p.is_file():
                z.write(p, Path("memory") / p.relative_to(memory_dir))
        for name in ("settings.json", "tyrone.db"):
            p = Path(data_dir) / name
            if p.exists():
                z.write(p, name)
    salt = os.urandom(SALT_LEN)
    token = Fernet(_key(password, salt)).encrypt(buf.getvalue())
    out_file = Path(out_file)
    out_file.write_bytes(MAGIC + salt + token)
    return out_file


def import_bundle(bundle: Path, data_dir: Path, memory_dir: Path, password: str) -> list[str]:
    raw = Path(bundle).read_bytes()
    if not raw.startswith(MAGIC):
        raise ValueError("Not a Tyrone export file")
    salt = raw[len(MAGIC): len(MAGIC) + SALT_LEN]
    try:
        data = Fernet(_key(password, salt)).decrypt(raw[len(MAGIC) + SALT_LEN:])
    except InvalidToken as exc:
        raise ValueError("Wrong password") from exc
    restored: list[str] = []
    memory_dir, data_dir = Path(memory_dir), Path(data_dir)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = Path(info.filename)
            if name.is_absolute() or ".." in name.parts:
                continue  # never write outside the target folders
            if name.parts[0] == "memory":
                target = memory_dir.joinpath(*name.parts[1:])
            elif str(name) in ("settings.json", "tyrone.db"):
                target = data_dir / name
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            restored.append(str(name))
    return restored

"""A small encrypted key store that reliably survives restarts and updates.

Secrets live in `%APPDATA%\\Monkey\\secrets.dat` as JSON {name: "dpapi:<base64>"}. On Windows each value is
encrypted with DPAPI (CryptProtectData), Windows' own per-user encryption: only the same Windows account on
the same PC can decrypt it, and nothing extra needs to be installed or bundled. There's no size limit, unlike
Windows Credential Manager (~2.5 KB per secret, too small for a Google sign-in token).

On other systems (development, CI tests on Linux) values are only base64-encoded ("plain:"), clearly marked
as dev-only. Writes are atomic: a crash mid-save never leaves a half-written file.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

_IS_WIN = sys.platform == "win32"


# ---------------------------------------------------------------------------- DPAPI (Windows)
if _IS_WIN:  # pragma: no cover - exercised by the Windows CI selftest
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CRYPTPROTECT_UI_FORBIDDEN = 0x01
    _ENTROPY = b"Monkey assistant secrets v1"

    def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
        buf = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _call(fn, data: bytes) -> bytes:
        inp, _keep = _blob(data)
        ent, _keep2 = _blob(_ENTROPY)
        out = _Blob()
        if not fn(ctypes.byref(inp), None, ctypes.byref(ent), None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
            raise OSError(ctypes.get_last_error(), "Windows couldn't encrypt/decrypt the secret (DPAPI)")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(out.pbData)

    def _protect(data: bytes) -> str:
        return "dpapi:" + base64.b64encode(_call(_crypt32.CryptProtectData, data)).decode()

    def _unprotect(token: str) -> bytes:
        kind, _, b64 = token.partition(":")
        if kind != "dpapi":
            raise ValueError("not a DPAPI value")
        return _call(_crypt32.CryptUnprotectData, base64.b64decode(b64))
else:
    def _protect(data: bytes) -> str:
        return "plain:" + base64.b64encode(data).decode()

    def _unprotect(token: str) -> bytes:
        kind, _, b64 = token.partition(":")
        if kind != "plain":
            raise ValueError("value was encrypted on another system")
        return base64.b64decode(b64)


BACKEND = "Windows DPAPI" if _IS_WIN else "plain file (development only)"


class SecretStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()

    # Re-read the file on every call: it's tiny, and it means a value saved by another Monkey process
    # (or before a restart) is always what we see.
    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".secrets-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def get(self, name: str) -> str | None:
        token = self._load().get(name)
        if token is None:
            return None
        try:
            return _unprotect(token).decode("utf-8")
        except Exception:  # noqa: BLE001 - e.g. file copied from another PC/account: treat as not set
            return None

    def set(self, name: str, value: str) -> None:  # noqa: A003
        with self._lock:
            data = self._load()
            data[name] = _protect(value.encode("utf-8"))
            self._save(data)

    def delete(self, name: str) -> None:
        with self._lock:
            data = self._load()
            if data.pop(name, None) is not None:
                self._save(data)

    def names(self) -> list[str]:
        return sorted(self._load())

"""API keys and tokens.

Saved in an encrypted file in Monkey's data folder (`%APPDATA%\\Monkey\\secrets.dat`, Windows DPAPI, see
secretstore.py), so they survive restarts, updates and reinstalls. Keys saved by older versions in Windows
Credential Manager (service "Monkey" or "Tyrone") are moved over automatically the first time they're read.

Environment variables override saved keys, which is handy for development:
ANTHROPIC_API_KEY, FISH_API_KEY, DEEPGRAM_API_KEY, YOUTUBE_API_KEY, BRAVE_API_KEY, ...
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from .secretstore import SecretStore

SERVICE = "Monkey"
OLD_SERVICE = "Tyrone"  # keys saved before the rename

KNOWN_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "fish": "FISH_API_KEY",
    "deepgram": "DEEPGRAM_API_KEY",
    "youtube": "YOUTUBE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "brave": "BRAVE_API_KEY",
    "canvas_token": "CANVAS_TOKEN",
    "google_token": "MONKEY_GOOGLE_TOKEN",     # OAuth token JSON (refresh token)
    "google_client": "MONKEY_GOOGLE_CLIENT",   # OAuth client JSON (Desktop app)
    "export_password": "MONKEY_EXPORT_PASSWORD",
    "calendar_ics": "MONKEY_CALENDAR_ICS",     # private iCal link(s), one per line (Google "secret address")
}
# Shown in Settings as "••••abcd" so you can tell which key is saved. Not for JSON blobs or passwords.
HINTABLE = {"anthropic", "fish", "deepgram", "youtube", "openai", "brave", "canvas_token"}

_store: SecretStore | None = None
_store_lock = threading.Lock()
_migrated: set[str] = set()


class KeySaveError(RuntimeError):
    pass


def store() -> SecretStore:
    global _store
    with _store_lock:
        if _store is None:
            from .config import default_data_dir

            _store = SecretStore(default_data_dir() / "secrets.dat")
        return _store


def use_store(path: Path | str | None) -> None:
    """Point at a different secrets file (tests, selftest). None = back to the default location."""
    global _store
    with _store_lock:
        _store = SecretStore(path) if path is not None else None
        _migrated.clear()


def _keyring():
    try:
        import keyring  # noqa: WPS433

        return keyring
    except Exception:  # pragma: no cover - keyring backend missing
        return None


def _from_old_keychain(name: str) -> str | None:
    """One-time move of a key from Windows Credential Manager (how versions <= 0.3.11 saved keys)."""
    if name in _migrated:
        return None
    _migrated.add(name)
    kr = _keyring()
    if kr is None:
        return None
    for service in (SERVICE, OLD_SERVICE):
        try:
            value = kr.get_password(service, name)
        except Exception:  # noqa: BLE001
            value = None
        if value:
            try:
                store().set(name, value)
            except Exception:  # noqa: BLE001 - still usable this session
                pass
            return value
    return None


def saved(name: str) -> str | None:
    """The saved value, ignoring environment overrides."""
    value = store().get(name)
    if value is None:
        value = _from_old_keychain(name)
    return value


def get(name: str) -> str | None:
    env = KNOWN_KEYS.get(name)
    if env and os.environ.get(env):
        return os.environ[env]
    return saved(name)


def set(name: str, value: str) -> None:  # noqa: A001 - mirrors keyring API
    """Save and read back. Raises KeySaveError if it wouldn't survive a restart."""
    try:
        store().set(name, value)
    except Exception as exc:  # noqa: BLE001
        raise KeySaveError(f"Couldn't save the {name} key: {exc}") from exc
    if store().get(name) != value:
        raise KeySaveError(f"The {name} key didn't read back correctly after saving.")
    _migrated.add(name)


def delete(name: str) -> None:
    try:
        store().delete(name)
    except Exception:  # noqa: BLE001
        pass
    _migrated.add(name)  # don't resurrect it from the old keychain
    kr = _keyring()
    if kr is None:
        return
    for service in (SERVICE, OLD_SERVICE):
        try:
            kr.delete_password(service, name)
        except Exception:  # noqa: BLE001
            pass


def status() -> dict[str, bool]:
    """Which keys are configured (never returns the values)."""
    return {name: bool(get(name)) for name in KNOWN_KEYS}


def hints() -> dict[str, str]:
    """Last 4 characters of saved keys, e.g. {"fish": "4s0I"}, so Settings can show which key is stored."""
    out: dict[str, str] = {}
    for name in HINTABLE:
        v = get(name)
        if v and len(v) >= 12:
            out[name] = v[-4:]
    return out

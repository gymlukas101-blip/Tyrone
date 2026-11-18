"""API keys and tokens, stored in Windows Credential Manager (via keyring).

Environment variables override the keychain, which is handy for development:
ANTHROPIC_API_KEY, FISH_API_KEY, DEEPGRAM_API_KEY, YOUTUBE_API_KEY, BRAVE_API_KEY.
"""
from __future__ import annotations

import os

SERVICE = "Tyrone"

KNOWN_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "fish": "FISH_API_KEY",
    "deepgram": "DEEPGRAM_API_KEY",
    "youtube": "YOUTUBE_API_KEY",
    "brave": "BRAVE_API_KEY",
    "google_token": "TYRONE_GOOGLE_TOKEN",     # OAuth token JSON (refresh token)
    "google_client": "TYRONE_GOOGLE_CLIENT",   # OAuth client JSON (Desktop app)
    "export_password": "TYRONE_EXPORT_PASSWORD",
}


def _keyring():
    try:
        import keyring  # noqa: WPS433

        return keyring
    except Exception:  # pragma: no cover - keyring backend missing
        return None


def get(name: str) -> str | None:
    env = KNOWN_KEYS.get(name)
    if env and os.environ.get(env):
        return os.environ[env]
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(SERVICE, name)
    except Exception:
        return None


def set(name: str, value: str) -> None:  # noqa: A001 - mirrors keyring API
    kr = _keyring()
    if kr is None:
        raise RuntimeError("No secure keychain available on this system")
    kr.set_password(SERVICE, name, value)


def delete(name: str) -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, name)
    except Exception:
        pass


def status() -> dict[str, bool]:
    """Which keys are configured (never returns the values)."""
    return {name: bool(get(name)) for name in KNOWN_KEYS}

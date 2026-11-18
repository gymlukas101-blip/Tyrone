"""Paths and non-secret settings.

Personal data (memory, database, settings) lives in the user's data folder,
never in the code repo:
  Windows: %APPDATA%\\Tyrone
  other:   ~/.tyrone
Secrets (API keys, OAuth tokens) live in the OS keychain - see secrets.py.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    override = os.environ.get("TYRONE_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "Tyrone"
    return Path.home() / ".tyrone"


@dataclass
class Settings:
    # Identity
    user_name: str = ""
    # Voice
    fish_voice_id: str = ""          # Fish Audio reference_id of Tyrone's designed voice
    fish_model: str = "s2.1-pro"      # Fish TTS model header value
    stt_engine: str = "whisper"       # "whisper" (local, free) | "deepgram" (faster, paid)
    whisper_model: str = "small.en"
    # Wake word
    wakeword_model: str = "yo_tyrone"  # falls back to "hey_jarvis" until the custom model is bundled
    wakeword_threshold: float = 0.5
    push_to_talk_hotkey: str = "ctrl+alt+space"
    # Brain
    monthly_budget_usd: float = 25.0
    force_model: str = ""             # "" = automatic routing
    # Integrations
    use_gmail: bool = True
    use_outlook: bool = True
    canvas_ics_url: str = ""
    home_location: str = "Madison, WI"
    latitude: float = 43.0766          # UW-Madison campus
    longitude: float = -89.4125
    # Memory
    memory_dir_override: str = ""     # e.g. a OneDrive folder to sync memory across PCs
    # App
    start_with_windows: bool = True
    first_run_complete: bool = False
    extra: dict = field(default_factory=dict)


class Config:
    """Loads/saves settings.json and exposes well-known paths."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.settings = self._load()

    # ---- paths -------------------------------------------------------
    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def memory_dir(self) -> Path:
        """Folder that holds /memories (the Claude memory tool root lives inside it)."""
        if self.settings.memory_dir_override:
            return Path(self.settings.memory_dir_override)
        return self.data_dir / "memory"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tyrone.db"

    @property
    def cache_dir(self) -> Path:
        p = self.data_dir / "cache"
        p.mkdir(exist_ok=True)
        return p

    # ---- load/save ---------------------------------------------------
    def _load(self) -> Settings:
        if self.settings_path.exists():
            try:
                raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
                known = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
                return Settings(**known)
            except (json.JSONDecodeError, TypeError):
                pass
        return Settings()

    def save(self) -> None:
        with self._lock:
            tmp = self.settings_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self.settings), indent=2), encoding="utf-8")
            tmp.replace(self.settings_path)

    def update(self, **changes) -> Settings:
        for k, v in changes.items():
            if k in Settings.__dataclass_fields__:
                setattr(self.settings, k, v)
        self.save()
        return self.settings

    def as_dict(self) -> dict:
        return asdict(self.settings)


def resource_path(*parts: str) -> Path:
    """Path to a bundled resource, working both from source and from a PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)

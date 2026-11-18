"""Paths and non-secret settings.

Personal data (memory, database, settings) lives in the user's data folder,
never in the code repo:
  Windows: %APPDATA%\\Monkey
  other:   ~/.monkey
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
    override = os.environ.get("MONKEY_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
        new, old = base / "Monkey", base / "Tyrone"
    else:
        new, old = Path.home() / ".monkey", Path.home() / ".tyrone"
    if not new.exists() and old.exists():
        # One-time move from the app's old name, so memory and settings carry over.
        try:
            old.rename(new)
        except OSError:
            pass
    return new


@dataclass
class Settings:
    # Identity
    user_name: str = ""
    # Voice
    fish_voice_id: str = "4a396e7e91a640a2b1e0f06249cbcd14"  # Fish Audio voice (reference_id) - your pick
    fish_model: str = "s2.1-pro"      # Fish TTS model header value
    stt_engine: str = "whisper"       # "whisper" (local, free) | "deepgram" (faster, paid)
    whisper_model: str = "small.en"
    # Wake word
    wakeword_phrase: str = "hey monkey"   # spotted with sherpa-onnx, no training needed
    wakeword_model: str = "hey_monkey"    # optional trained openWakeWord model (falls back to hey_jarvis)
    wakeword_threshold: float = 0.5
    push_to_talk_hotkey: str = "ctrl+alt+space"
    # Brain
    monthly_budget_usd: float = 25.0
    force_model: str = ""             # "" = automatic routing
    max_credits: bool = False         # paying with Claude Max's monthly API credits ($100): budget kept under it
    brain_profile: str = "best"       # "best" (Opus for heavy work) | "saver" (Sonnet for heavy work)
    # Updates + images
    auto_update: bool = True
    image_model: str = "gpt-image-2.6-sunburst"   # or "gpt-image-2.6-flare" (faster drafts)
    favorite_prototype: str = ""
    cleanup_done: bool = False        # old installs/downloads cleanup offered and run
    prototype_notes: dict = field(default_factory=dict)
    # Integrations
    use_gmail: bool = True
    use_outlook: bool = True
    canvas_ics_url: str = ""
    canvas_base_url: str = "https://canvas.wisc.edu"
    anthropic_workspace_id: str = ""  # only for Console keys not tied to a workspace (found automatically)
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
        return self.data_dir / "monkey.db"

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

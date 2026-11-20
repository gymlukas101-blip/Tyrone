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
    fish_model: str = "s2.1-pro-free"  # Fish TTS model header: "s2.1-pro-free" ($0, Fish may use text for training) | "s2.1-pro" (paid)
    fish_allow_free: bool = True      # allow Fish's free model (else offline voice only)
    fish_paid_confirmed: bool = False # user explicitly chose the paid model (skip the free migration)
    stt_engine: str = "whisper"       # "whisper" (local, free) | "deepgram" (faster, paid)
    whisper_model: str = "small.en"
    # Wake word
    wakeword_phrase: str = "hey monkey"   # spotted with sherpa-onnx, no training needed
    wakeword_model: str = "hey_monkey"    # optional trained openWakeWord model (falls back to hey_jarvis)
    wakeword_threshold: float = 0.5
    push_to_talk_hotkey: str = "ctrl+alt+space"
    conversation_mode: bool = True    # after "Hey Monkey" once, keep listening (no wake word) until the chat is over
    conversation_idle_s: int = 90     # ...which is when you say "thanks"/"bye", or after this many seconds of quiet
    end_silence: str = "normal"       # how long a pause ends your turn: "quick" 0.9 s | "normal" 1.4 s | "patient" 2 s
    # Brain
    monthly_budget_usd: float = 25.0
    force_model: str = ""             # "" = automatic routing
    juice_level: str = "auto"         # animation/VFX/SFX intensity: auto (follows Windows) | full | calm | minimal
    google_account: str = ""         # shown in Settings after sign-in ("Connected as …")
    show_tech_details: bool = False   # model chip, memory-file chips, Avatar Lab, raw task XML (for developers)
    voice_match_loudness: bool = True  # level his voice to streaming loudness (~-14 LUFS, like YouTube)
    voice_volume: int = 100           # 25-200 %, on top of the matched level
    sfx_volume: int = 70              # 0-100, Monkey's sound effects (his voice has its own level)
    sleep_after_min: int = 8          # idle minutes before he dozes off (ZZZ)
    offline_voice: str = "fallback"   # Pocket TTS clone: "fallback" (when Fish fails), "only" (never use Fish), "off"
    sfx_rejects: list = field(default_factory=list)  # sound takes you turned off in the Sound Lab ("laugh_2", ...)
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
    use_outlook: bool = True          # legacy, ignored (it never gated anything)
    outlook_connected: bool = False   # opt-in: Monkey touches Outlook only after you click Connect
    canvas_ics_url: str = ""
    canvas_base_url: str = "https://canvas.wisc.edu"
    canvas_token_expires: str = ""    # YYYY-MM-DD; UW tokens are short-lived, Monkey warns before expiry
    # Morning brief (America/Chicago): timed only from a schedule you confirmed; never pushes notifications.
    brief_enabled: bool = True        # build/preview the brief in the app
    brief_lead_min: int = 90          # minutes before your earliest verified class
    brief_schedule: dict = field(default_factory=dict)   # {"by_day": {"mon": "08:50"}, "source": .., "confirmed_at": ..}
    brief_speak_on_open: bool = False # say a 2-sentence version when you open Monkey (opt-in)
    anthropic_workspace_id: str = ""  # only for Console keys not tied to a workspace (found automatically)
    home_location: str = "Madison, WI"
    latitude: float = 43.0766          # UW-Madison campus
    longitude: float = -89.4125
    # Memory
    memory_dir_override: str = ""     # e.g. a OneDrive folder to sync memory across PCs
    history_enabled: bool = True      # keep a searchable local history of conversations (monkey.db)
    history_retention_days: int = 365 # older conversations are deleted automatically (0 = keep forever)
    # Computer tasks (docs/adr/0001-computer-agent.md). Off until the user turns it on; nothing else depends on it.
    computer_access: bool = False
    automation_stop_hotkey: str = "ctrl+alt+q"   # emergency stop: refuse every action and stop every task
    automation_browser: str = "chrome"  # chrome | edge: Monkey's own window | my_chrome: your Chrome via the extension
    chrome_bridge_port: int = 47615     # local port the Monkey for Chrome extension connects to
    overlay_enabled: bool = True      # the small always-on-top companion window (when computer access is on)
    overlay_mode: str = "compact"     # compact | expanded | minimized
    overlay_geom: dict = field(default_factory=dict)    # {"x", "y", "w", "h"} remembered position
    # Animated banana cursor (feedback while Monkey controls something; never replaces the Windows mouse)
    cursor_mode: str = "control"      # off | control
    cursor_scale: float = 1.0         # 0.75 - 1.6
    cursor_glow: float = 0.7          # 0 - 1
    cursor_motion: str = "auto"       # auto (follows Windows animation settings) | full | reduced
    cursor_click_fx: bool = True
    cursor_busy_fx: bool = True
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
    def voice_pack_dir(self) -> Path:
        """Offline voice model (~200 MB): machine-local (%LOCALAPPDATA%), never in the roaming profile."""
        import os

        local = os.environ.get("LOCALAPPDATA")
        return Path(local) / "Monkey" / "voice-pack" if local else self.data_dir / "voice-pack"

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
                # One-time move to Fish's free model (the API is pay-as-you-go; subscriptions don't include it).
                if known.get("fish_model") == "s2.1-pro" and not known.get("fish_paid_confirmed"):
                    known["fish_model"] = "s2.1-pro-free"
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

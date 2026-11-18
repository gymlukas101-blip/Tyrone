"""Monkey desktop app: wires the brain, audio, integrations and UI together."""
from __future__ import annotations

import base64
import json
import logging
import os
import queue
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import numpy as np

from . import __version__, keys, secretstore
from .brain import workspace
from .brain.agent import Agent
from .brain.approval import ApprovalGate
from .brain.costs import HAIKU, Ledger, Usage
from .brain.policy import ModelPolicy
from .brain.router import Router, classify_with_haiku
from .brain.tools import Services, ToolRunner
from .config import Config, resource_path
from .integrations.canvas_api import AssignmentBoard, CanvasAPI, LocalChecks
from .integrations.canvas_ics import CanvasCalendar
from .integrations.garmin import GarminHealth
from .integrations.google import GmailProvider, GoogleAuth, GoogleCalendarProvider
from .integrations.outlook_com import OutlookProvider
from .integrations.web_media import NWSWeather, brave_images, commons_images, youtube_search
from .memory.store import MonkeyMemory
from .updater import Updater

log = logging.getLogger("monkey")


# ---------------------------------------------------------------------------- UI bus
class UIBus:
    """Batches events to the web UI (~30 per second), coalescing mouth levels."""

    def __init__(self):
        self.window = None
        self._q: queue.Queue[tuple[str, dict]] = queue.Queue()
        self._level: float | None = None
        self._visemes: dict | None = None
        threading.Thread(target=self._loop, name="ui-bus", daemon=True).start()

    def emit(self, name: str, payload: dict | None = None) -> None:
        self._q.put((name, payload or {}))

    def level(self, v: float) -> None:
        self._level = v

    def visemes(self, w: dict) -> None:
        self._visemes = w

    def _loop(self) -> None:
        while True:
            time.sleep(1 / 30)
            if self.window is None:
                continue
            batch: list[tuple[str, dict]] = []
            while not self._q.empty() and len(batch) < 200:
                batch.append(self._q.get_nowait())
            if self._level is not None:
                batch.append(("level", {"v": round(self._level, 3)}))
                self._level = None
            if self._visemes is not None:
                batch.append(("visemes", self._visemes))
                self._visemes = None
            if batch:
                try:
                    self.window.evaluate_js(f"window.__monkeyEvents && window.__monkeyEvents({json.dumps(batch, default=str)})")
                except Exception as exc:  # noqa: BLE001 - window may be closing
                    log.debug("evaluate_js failed: %s", exc)


# ---------------------------------------------------------------------------- app
class MonkeyApp:
    def __init__(self, data_dir: Path | None = None, headless: bool = False):
        self.cfg = Config(data_dir)
        self._setup_logging()
        self.headless = headless
        self.ui = UIBus()
        self.memory = MonkeyMemory(self.cfg.memory_dir)
        self.ledger = Ledger(self.cfg.db_path)
        self._bot_text: list[str] = []
        self._calibration = None

        # Integrations
        self.google = GoogleAuth()
        self.gmail = GmailProvider(self.google)
        self.gcal = GoogleCalendarProvider(self.google)
        self.outlook = OutlookProvider()
        self.canvas = CanvasCalendar(lambda: self.cfg.settings.canvas_ics_url)
        self.canvas_api = CanvasAPI(lambda: self.cfg.settings.canvas_base_url, lambda: keys.get("canvas_token"))
        self.board = AssignmentBoard(self.canvas_api, self.canvas, LocalChecks(self.cfg.db_path))
        self.garmin = GarminHealth(self.cfg.data_dir / "garmin")
        self.approval = ApprovalGate({
            "gmail": lambda d: self.gmail.send_draft(d.provider_draft_id, d.to, d.cc, d.subject, d.body),
            "outlook": lambda d: self.outlook.send_draft(d.provider_draft_id, d.to, d.cc, d.subject, d.body),
        })
        self.client = None
        self.services = Services(
            emit=self._emit, memory=self.memory, approval=self.approval,
            mail={"gmail": self.gmail, "outlook": self.outlook},
            calendars=[self.gcal, self.outlook, self.canvas],
            image_search=self._images, video_search=self._videos if keys.get("youtube") else None,
            image_gen=self._generate_images,
            weather=NWSWeather(lambda: (self.cfg.settings.latitude, self.cfg.settings.longitude)),
            record_usage=self._record_usage, open_url=self._open_url,
            assignments=self.board, health=self.garmin,
        )
        self.policy = ModelPolicy(self.cfg.data_dir / "model_policy.json")
        self.services.policy = self.policy
        self.policy.write_memory_note(self.memory)
        self.router = Router(
            classify=self._classify,
            budget_usd=lambda: self.cfg.settings.monthly_budget_usd,
            spent_usd=self.ledger.month_to_date,
            forced_model=lambda: self.cfg.settings.force_model,
            profile=lambda: self.cfg.settings.brain_profile,
            policy=self.policy,
        )
        self.agent = Agent(None, self.router, ToolRunner(self.services), self.memory, self.ledger,
                           emit=self._emit, speak=self._say, user_name=lambda: self.cfg.settings.user_name)
        self._ensure_client()

        # Audio (created in start_audio so tests/selftest don't need devices)
        self.speaker = None
        self.listener = None
        self.stt = None
        self.wakeword_label = "starting…"
        self._agent_state = "idle"
        self._listening = False
        self._waved = False
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent")
        self._voice_candidates: list[bytes] = []
        self.updater = Updater(self.ui.emit, enabled=lambda: self.cfg.settings.auto_update)

    # ------------------------------------------------------------------ setup
    def _setup_logging(self) -> None:
        handler = RotatingFileHandler(self.cfg.data_dir / "monkey.log", maxBytes=2_000_000, backupCount=2,
                                      encoding="utf-8")
        handlers: list[logging.Handler] = [handler]
        if sys.stderr is not None:  # a windowed .exe has no console
            handlers.append(logging.StreamHandler())
        logging.basicConfig(level=logging.INFO, handlers=handlers,
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def _ensure_client(self):
        key = keys.get("anthropic")
        if not key:
            return None
        import anthropic

        ws = (self.cfg.settings.anthropic_workspace_id or "").strip()
        sig = (key, ws)
        if self.client is None or getattr(self, "_client_sig", None) != sig:
            headers = {workspace.HEADER: ws} if ws else None
            self.client = anthropic.Anthropic(api_key=key, max_retries=2, default_headers=headers)
            self._client_sig = sig
            self.agent.client = self.client
            self.services.anthropic_client = self.client
        return self.client

    def _fix_workspace(self) -> bool:
        """Org-wide Console key without a workspace header? Find the workspace, save it, rebuild the client."""
        if self.cfg.settings.anthropic_workspace_id or self._ensure_client() is None:
            return False
        ws, note = workspace.discover(self.client)
        log.info("workspace discovery: %s %s", ws, note)
        if not ws:
            return False
        self.cfg.update(anthropic_workspace_id=ws)
        self._ensure_client()
        return True

    def verify_anthropic(self) -> dict:
        """Free check (token counting) that the key works; fixes the workspace header automatically."""
        import anthropic

        client = self._ensure_client()
        if client is None:
            return {"ok": False, "error": "No Anthropic key saved yet."}
        probe = {"model": HAIKU, "messages": [{"role": "user", "content": "hi"}]}
        try:
            client.messages.count_tokens(**probe)
            return {"ok": True}
        except anthropic.APIStatusError as exc:
            if workspace.needs_workspace(exc) and self._fix_workspace():
                try:
                    self.client.messages.count_tokens(**probe)
                    return {"ok": True, "note": "Your key is organization-wide, so Monkey found your workspace and "
                                                "saved its ID. You're all set."}
                except anthropic.APIStatusError as exc2:
                    return {"ok": False, "error": workspace.describe(exc2)}
            return {"ok": False, "error": workspace.describe(exc)}
        except anthropic.APIConnectionError:
            return {"ok": False, "error": "Couldn't reach Anthropic. Check your internet connection."}

    def start_audio(self) -> None:
        from .audio.listener import Listener, load_wakeword
        from .audio.speaker import Speaker
        from .audio.stt import DeepgramSTT, WhisperSTT
        from .audio.tts import FishTTS, SystemTTS

        s = self.cfg.settings
        fish = FishTTS(lambda: keys.get("fish"), lambda: self.cfg.settings.fish_voice_id,
                       lambda: self.cfg.settings.fish_model, allow_free=lambda: self.cfg.settings.fish_allow_free,
                       on_model_change=lambda m: self.cfg.update(fish_model=m))
        fish.enabled = lambda: self.cfg.settings.offline_voice != "only"
        self.offline_voice = self._make_offline_voice()
        self.speaker = Speaker(
            [fish, self.offline_voice, SystemTTS()],
            on_level=self.ui.level, on_state=lambda _: self._publish_state(), on_visemes=self.ui.visemes,
            on_fallback=self._voice_fallback,
        )
        try:
            self.speaker.start()
        except Exception as exc:  # noqa: BLE001
            self._emit("error", {"message": f"No speaker/headphones found: {exc}"})
        self._warm_offline_voice()
        whisper = WhisperSTT(s.whisper_model, download_root=str(self.cfg.data_dir / "models"))
        deepgram = DeepgramSTT(lambda: keys.get("deepgram"))
        self.stt = lambda: deepgram if (self.cfg.settings.stt_engine == "deepgram" and keys.get("deepgram")) else whisper
        threading.Thread(target=whisper.warm_up, name="whisper-warmup", daemon=True).start()

        def init_listener():
            model, label = load_wakeword(s.wakeword_model, resource_path("wakeword"), self.cfg.data_dir / "wakeword",
                                         phrase=s.wakeword_phrase, sensitivity=s.wakeword_threshold,
                                         work_dir=self.cfg.data_dir / "wakeword")
            self.wakeword_label = label
            self.listener = Listener(
                on_wake=self._on_wake, on_utterance=self._on_utterance, on_timeout=self._on_timeout,
                wakeword_model=model, threshold=lambda: self.cfg.settings.wakeword_threshold,
                is_speaking=lambda: bool(self.speaker and self.speaker.speaking),
            )
            try:
                self.listener.start()
                self._emit("hint", {"text": f"Say “{label.split(' (')[0]}” or press {s.push_to_talk_hotkey}"})
            except Exception as exc:  # noqa: BLE001
                self._emit("error", {"message": f"Microphone unavailable: {exc}"})

        threading.Thread(target=init_listener, name="listener-init", daemon=True).start()
        self._register_hotkey()

    def _register_hotkey(self) -> None:
        try:
            import keyboard

            keyboard.add_hotkey(self.cfg.settings.push_to_talk_hotkey, self.push_to_talk)
        except Exception as exc:  # noqa: BLE001
            log.warning("hotkey unavailable: %s", exc)

    # ------------------------------------------------------------------ state + events
    def _emit(self, name: str, payload: dict | None = None) -> None:
        if name == "state":
            self._agent_state = (payload or {}).get("state", "idle")
            self._publish_state()
            return
        if name in ("user", "delta", "done"):
            self._remember_chat(name, payload or {})
        self.ui.emit(name, payload)

    def _warm_offline_voice(self) -> None:
        """Load the offline model in the background so the first fallback sentence starts quickly."""
        v = self.offline_voice

        def warm():
            try:
                with v._lock:
                    if v._tts is None:
                        v._load()
            except Exception as exc:  # noqa: BLE001
                log.info("offline voice not ready: %s", exc)

        if v.enabled() and v.available():
            threading.Thread(target=warm, name="pocket-warm", daemon=True).start()

    def _make_offline_voice(self):
        from .audio.offline_voice import PocketVoice

        v = PocketVoice(self.cfg.voice_pack_dir, lambda: self.cfg.data_dir / "voice" / "monkey-ref.wav")
        v.enabled = lambda: self.cfg.settings.offline_voice != "off"
        return v

    def _voice_fallback(self, engine: str, exc: Exception) -> None:
        """Monkey's Fish voice failed: say why (at most once a minute) instead of silently switching voices."""
        from .audio.tts import explain_fish_error

        now = time.time()
        if now - getattr(self, "_last_voice_warn", 0) < 60:
            return
        self._last_voice_warn = now
        ov = getattr(self, "offline_voice", None)
        backup = "Monkey's offline voice" if ov is not None and ov.enabled() and ov.available() else "the Windows voice"
        self._emit("warning", {"message": f"{explain_fish_error(exc)} Using {backup} for now."})

    def _remember_chat(self, name: str, p: dict) -> None:
        """Keep the chat (exactly as shown on screen) so it's still there next time Monkey opens."""
        if name == "delta":
            self._bot_text.append(str(p.get("text", "")))
            return
        try:
            if name == "user":
                self._bot_text = []
                self.ledger.add_transcript("user", str(p.get("text", "")))
            else:
                self.ledger.add_transcript("bot", "".join(self._bot_text) or str(p.get("text", "")))
                self._bot_text = []
        except Exception:  # noqa: BLE001
            log.debug("transcript save failed", exc_info=True)

    def _publish_state(self) -> None:
        if self.speaker is not None and self.speaker.speaking:
            state = "speaking"
        elif self._listening:
            state = "listening"
        else:
            state = self._agent_state
        self.ui.emit("state", {"state": state})

    def _say(self, sentence: str) -> None:
        if self.speaker is not None:
            self.speaker.say(sentence)

    # ------------------------------------------------------------------ voice flow
    def _on_wake(self) -> None:
        if self.speaker:
            self.speaker.stop()
        self.agent.cancel()
        self._listening = True
        self.ui.emit("wake", {})
        if not self._waved:  # say hi with a wave the first time each run
            self._waved = True
            self.ui.emit("emote", {"name": "wave"})
        self._publish_state()

    def push_to_talk(self) -> None:
        if self.listener is None:
            self._emit("error", {"message": "Microphone isn't ready yet."})
            return
        self._on_wake()
        self.listener.push_to_talk()

    def _on_timeout(self) -> None:
        self._listening = False
        self._publish_state()

    def _on_utterance(self, audio: np.ndarray) -> None:
        self._listening = False
        self._agent_state = "transcribing"
        self._publish_state()
        try:
            text = self.stt().transcribe(audio) if self.stt else ""
        except Exception as exc:  # noqa: BLE001
            self._emit("error", {"message": f"Speech recognition failed: {exc}"})
            text = ""
        self.ui.emit("heard", {"text": text})
        if text and len(text.strip(" .")) > 1:
            self.ask(text)
        else:
            self._agent_state = "idle"
            self._publish_state()

    def ask(self, text: str, importance: str | None = None) -> None:
        if self._ensure_client() is None:
            self._emit("error", {"message": "Add your Anthropic API key in Settings first."})
            return
        self.agent.cancel()
        if self.speaker:
            self.speaker.stop()

        self.agent.on_workspace_error = self._fix_workspace   # re-armed each request; used at most once

        def run():
            try:
                self.agent.handle(text, importance)
            except Exception as exc:  # noqa: BLE001
                log.exception("agent failed")
                self._emit("error", {"message": f"Something broke: {exc}"})
                self._emit("state", {"state": "idle"})

        self._worker.submit(run)

    # ------------------------------------------------------------------ helpers for tools
    def _classify(self, text: str):
        if self._ensure_client() is None:
            raise RuntimeError("no client")
        task, diff, needs_web, why, usage = classify_with_haiku(self.client, text)
        self._record_usage(HAIKU, "low", "router", usage)
        return task, diff, needs_web, why

    def _record_usage(self, model: str, effort: str, purpose: str, usage) -> None:
        self.ledger.record(model, effort, purpose, Usage.from_response(usage))

    def after_install_tasks(self) -> None:
        """First launch of an installed copy: start-with-Windows entry + offer to clean up old installs."""
        from . import cleanup
        from .updater import FIRST_RUN

        def work():
            installed = getattr(sys, "frozen", False)
            if installed and (FIRST_RUN.is_set() or not self.cfg.settings.cleanup_done):
                try:
                    cleanup.set_autostart(self.cfg.settings.start_with_windows)
                except Exception as exc:  # noqa: BLE001
                    log.warning("autostart: %s", exc)
            if self.cfg.settings.cleanup_done and not FIRST_RUN.is_set():
                return
            try:
                plan = cleanup.plan_cleanup()
            except Exception as exc:  # noqa: BLE001
                log.warning("cleanup scan failed: %s", exc)
                return
            if plan.items:
                self.ui.emit("cleanup", plan.to_dict())
            else:
                self.cfg.update(cleanup_done=True)

        threading.Thread(target=work, name="after-install", daemon=True).start()

    def _generate_images(self, prompt: str, count: int, refs=None, rules: bool = False) -> list[dict]:
        """GPT Image generation -> thumbnails (data URIs) for the UI; full PNGs saved in %APPDATA%\\Monkey\\images."""
        from .integrations.image_gen import MONKEY_RULES, generate

        key = keys.get("openai")
        if not key:
            raise RuntimeError("Add your OpenAI API key in Settings to generate images.")
        full_prompt = f"{MONKEY_RULES}\n\n{prompt}" if rules else prompt
        res = generate(full_prompt, self.cfg.data_dir / "images", refs=refs, n=count, api_key=key,
                       model=self.cfg.settings.image_model, size="1024x1536" if rules else "1024x1024")
        self.ledger.record_usd(self.cfg.settings.image_model, "image", res.cost_usd)
        return [{"title": p.stem, "src": _thumb_data_uri(p), "thumb": _thumb_data_uri(p, 384),
                 "page": p.as_uri(), "path": str(p)} for p in res.paths]

    def _images(self, query: str, count: int):
        key = keys.get("brave")
        if key:
            try:
                return brave_images(key, query, count)
            except Exception as exc:  # noqa: BLE001
                log.warning("brave failed: %s", exc)
        return commons_images(query, count)

    def _videos(self, query: str, count: int):
        return youtube_search(keys.get("youtube") or "", query, count)

    @staticmethod
    def _open_url(url: str) -> None:
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)


def _thumb_data_uri(path: Path, size: int = 1024) -> str:
    """Downscaled JPEG data URI so generated images show in the UI without a file server."""
    import io

    from PIL import Image

    im = Image.open(path).convert("RGB")
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------- JS API
class Api:
    """Methods callable from the web UI as window.pywebview.api.<name>()."""

    def __init__(self, app: MonkeyApp):
        self._app = app

    # state
    def get_state(self):
        a = self._app
        ks = keys.status()
        return {
            "settings": a.cfg.as_dict(),
            "keys": ks,
            "key_hints": keys.hints(),
            "secrets_backend": secretstore.BACKEND,
            "wakeword": a.wakeword_label,
            "connections": {
                "gmail": ks.get("google_token", False),
                "google_calendar": ks.get("google_token", False),
                "outlook": a.outlook.available(),
                "canvas": bool(a.cfg.settings.canvas_ics_url),
                "canvas_api": ks.get("canvas_token", False),
                "garmin": a.garmin.connected(),
            },
            "month_usd": a.ledger.month_to_date(),
            "budget_usd": a.cfg.settings.monthly_budget_usd,
            "breakdown": a.ledger.breakdown(),
            "memory_files": a.memory.files(),
            "version": __version__,
        }

    def save_key(self, name: str, value: str):
        """Save, then read it back from disk, so "Saved" really means it'll be there after a restart."""
        if name not in keys.KNOWN_KEYS:
            return {"ok": False, "error": "Unknown key"}
        value = (value or "").strip()
        if not value:
            return {"ok": False, "error": "Paste a key first"}
        try:
            keys.set(name, value)
        except Exception as exc:  # noqa: BLE001
            log.exception("saving key %s failed", name)
            return {"ok": False, "error": str(exc)}
        a = self._app
        if name == "anthropic":
            a.cfg.update(first_run_complete=True, anthropic_workspace_id="")
            check = a.verify_anthropic()
            if not check.get("ok"):
                return {"ok": True, "hint": keys.hints().get(name, ""), "warning": check.get("error", "")}
            return {"ok": True, "hint": keys.hints().get(name, ""), "note": check.get("note", "")}
        if name == "youtube":
            a.services.video_search = a._videos
        return {"ok": True, "hint": keys.hints().get(name, "")}

    def delete_key(self, name: str):
        if name in keys.KNOWN_KEYS:
            keys.delete(name)
        return {"ok": True}

    # model policy (Settings → Brain)
    def get_policy(self):
        a = self._app
        from .brain.calibrate import estimate_cost
        from .brain.policy import EFFORTS, MODEL_NAMES, MODELS

        cal = a.cfg.data_dir / "calibration.json"
        return {"rows": a.policy.table(), "totals": {t: a.policy.monthly_total(t) for t in ("min", "default", "max")},
                "models": [{"id": m, "name": MODEL_NAMES[m]} for m in MODELS], "efforts": EFFORTS,
                "calibration_estimate": estimate_cost(a.policy), "calibrating": a._calibration is not None,
                "has_results": cal.exists()}

    def set_policy_entry(self, task: str, tier: str, model: str, effort: str):
        try:
            self._app.policy.set_entry(task, tier, model, effort)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        self._app.policy.write_memory_note(self._app.memory)
        return {"ok": True, **self.get_policy()}

    def reset_policy(self, task: str = ""):
        self._app.policy.reset(task or None)
        self._app.policy.write_memory_note(self._app.memory)
        return self.get_policy()

    def test_anthropic(self):
        return self._app.verify_anthropic()

    def calibration_estimate(self, tasks=None, samples: int = 1):
        from .brain.calibrate import estimate_cost

        return {"usd": estimate_cost(self._app.policy, list(tasks or []) or None, int(samples or 1))}

    def calibrate_start(self, samples: int = 1, tasks=None):
        a = self._app
        if a._ensure_client() is None:
            return {"ok": False, "error": "Add your Anthropic API key first."}
        check = a.verify_anthropic()   # free; also fixes the workspace header if needed
        if not check.get("ok"):
            return {"ok": False, "error": check.get("error", "Your Claude key isn't working yet.")}
        if a._calibration is not None:
            return {"ok": False, "error": "Calibration is already running."}
        from .brain.calibrate import Calibration

        cal = Calibration(a.client, a.policy, a.ledger, a.cfg.data_dir / "calibration.json",
                          progress=lambda p: a.ui.emit("calibration", p), samples=int(samples or 1),
                          tasks=list(tasks or []) or None)
        a._calibration = cal

        def run():
            try:
                cal.run()
            except Exception as exc:  # noqa: BLE001
                log.exception("calibration failed")
                a.ui.emit("calibration", {"finished": True, "error": str(exc)})
            finally:
                a._calibration = None

        threading.Thread(target=run, name="calibration", daemon=True).start()
        return {"ok": True}

    def calibrate_cancel(self):
        if self._app._calibration is not None:
            self._app._calibration.cancel.set()
        return {"ok": True}

    def calibration_results(self):
        p = self._app.cfg.data_dir / "calibration.json"
        try:
            return {"ok": True, **json.loads(p.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            return {"ok": False, "error": "No calibration results yet."}

    def calibration_apply(self, picks: dict):
        from .brain.calibrate import apply_picks

        res = self.calibration_results()
        if not res.get("ok"):
            return res
        changed = apply_picks(self._app.policy, res, picks or {})
        self._app.policy.write_memory_note(self._app.memory)
        return {"ok": True, "changed": changed, **self.get_policy()}

    def get_transcript(self, limit: int = 40):
        try:
            return self._app.ledger.recent_transcript(max(1, min(int(limit), 200)))
        except Exception:  # noqa: BLE001
            log.exception("transcript load failed")
            return []

    def save_settings(self, changes: dict):
        allowed = {k: v for k, v in (changes or {}).items() if k != "extra"}
        if "fish_voice_id" in allowed:
            from .audio.tts import normalize_voice_id

            allowed["fish_voice_id"] = normalize_voice_id(str(allowed["fish_voice_id"]))
        self._app.cfg.update(**allowed)
        if "start_with_windows" in allowed and getattr(sys, "frozen", False):
            from . import cleanup

            cleanup.set_autostart(bool(allowed["start_with_windows"]))
        return self.get_state()

    # conversation
    def send_text(self, text: str, importance=None):
        self._app.ask(str(text)[:8000], importance if importance in ("low", "normal", "high") else None)

    def push_to_talk(self):
        self._app.push_to_talk()

    def stop_speaking(self):
        if self._app.speaker:
            self._app.speaker.stop()
        self._app.agent.cancel()

    # avatar lab (prototype designs)
    def list_prototypes(self):
        st = self._app.cfg.settings
        return {"favorite": st.favorite_prototype, "notes": st.prototype_notes, "model": st.image_model,
                "has_key": bool(keys.get("openai"))}

    def pick_prototype(self, proto_id: str, notes: str = ""):
        st = self._app.cfg.settings
        notes_map = dict(st.prototype_notes or {})
        if notes:
            notes_map[proto_id] = notes[:2000]
        self._app.cfg.update(favorite_prototype=proto_id, prototype_notes=notes_map)
        return self.list_prototypes()

    def save_prototype_note(self, proto_id: str, notes: str):
        notes_map = dict(self._app.cfg.settings.prototype_notes or {})
        notes_map[proto_id] = (notes or "")[:2000]
        self._app.cfg.update(prototype_notes=notes_map)
        return True

    def generate_prototypes(self, direction: str, count: int = 1, ref_hero: str = ""):
        """New Monkey design ideas: the design rules + your direction, using a prototype hero as reference."""
        ref = None
        if ref_hero and ".." not in ref_hero:
            cand = resource_path("ui", "dist", *ref_hero.split("/"))
            ref = [cand] if cand.exists() else None
        try:
            imgs = self._app._generate_images(
                f"Art direction: {direction.strip()[:1500]}\n\nHero illustration: full body, polished stylized "
                "3D render, soft clumped fur, warm key light and cyan rim light, vivid jungle background with bananas.",
                max(1, min(int(count or 1), 2)), refs=ref, rules=True)
            return {"ok": True, "images": imgs}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    # cleanup of old installs / downloads
    def cleanup_plan(self):
        from . import cleanup

        try:
            return {"ok": True, **cleanup.plan_cleanup().to_dict()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def cleanup_run(self):
        from . import cleanup

        try:
            plan = cleanup.clean(cleanup.plan_cleanup())
            self._app.cfg.update(cleanup_done=True)
            return {"ok": True, **plan.to_dict()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def report_ui_error(self, info: str):
        log.error("UI boot problem: %s", str(info)[:2000])

    def cleanup_dismiss(self):
        self._app.cfg.update(cleanup_done=True)

    # updates
    def check_update(self):
        return self._app.updater.check_async()

    def apply_update(self):
        return self._app.updater.apply()

    def update_state(self):
        return self._app.updater.state()

    def new_conversation(self):
        self._app.agent.new_session()
        self._app.ledger.add_transcript("reset", "")

    # drafts (the ONLY way email gets sent)
    def approve(self, draft_id: str, token: str):
        try:
            self._app.approval.approve(draft_id, token)
            self._app._say("Sent.")
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def cancel_draft(self, draft_id: str):
        self._app.approval.cancel(draft_id)

    def edit_draft(self, draft_id: str, token: str, subject: str, body: str):
        try:
            self._app.approval.update_body(draft_id, token, subject, body)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def open_draft(self, draft_id: str):
        d = self._app.approval.get(draft_id)
        if d is None:
            return
        prov = self._app.outlook if d.account == "outlook" else self._app.gmail
        threading.Thread(target=prov.open_draft, args=(d.provider_draft_id,), daemon=True).start()

    def open_url(self, url: str):
        self._app._open_url(url)

    # accounts
    def google_sign_in(self):
        try:
            self._app.google.sign_in()
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def google_sign_out(self):
        self._app.google.sign_out()

    def test_outlook(self):
        o = self._app.outlook
        if sys.platform != "win32":
            return {"ok": False, "error": "Outlook only works on Windows"}
        try:
            got = o.list_recent(max_results=1)
            return {"ok": True, "count": len(got)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{exc}. Make sure classic Outlook is installed and signed in to wisc.edu."}

    def learn_style(self):
        from .integrations.style import learn_style

        a = self._app
        if a._ensure_client() is None:
            return {"ok": False, "error": "Add your Anthropic key first"}
        try:
            c = a.policy.choice("style_learning")
            guide = learn_style(a.client, [a.gmail, a.outlook], a.memory, record_usage=a._record_usage,
                                model=c.model, effort=c.effort)
            return {"ok": True, "preview": guide[:600]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    # canvas checklist
    def get_assignments(self, refresh: bool = False):
        try:
            return {"ok": True, **self._app.board.load(refresh=bool(refresh))}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def toggle_assignment(self, item_id: str, done: bool):
        try:
            return {"ok": True, **self._app.board.toggle(str(item_id), bool(done))}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    # garmin
    def get_health(self, day: str = "today"):
        try:
            return {"ok": True, "health": self._app.garmin.health(day or "today")}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def garmin_login(self, email: str, password: str):
        try:
            return {"ok": True, "status": self._app.garmin.login(email.strip(), password)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def garmin_mfa(self, code: str):
        try:
            return {"ok": True, "status": self._app.garmin.submit_mfa(code)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def garmin_logout(self):
        self._app.garmin.logout()

    # voice
    def voice_design(self, instruction: str):
        from .audio.tts import fish_voice_design

        key = keys.get("fish")
        if not key:
            return {"ok": False, "error": "Add your Fish Audio key first"}
        try:
            self._app._voice_candidates = fish_voice_design(key, instruction)
            return {"ok": True, "candidates": [base64.b64encode(w).decode() for w in self._app._voice_candidates]}
        except Exception as exc:  # noqa: BLE001
            from .audio.tts import explain_fish_error

            return {"ok": False, "error": explain_fish_error(RuntimeError(f"voice-design {exc}"))}

    def choose_voice(self, index: int):
        from .audio.tts import fish_create_voice

        try:
            wav = self._app._voice_candidates[int(index)]
            voice_id = fish_create_voice(keys.get("fish") or "", wav)
            if not voice_id:
                return {"ok": False, "error": "Fish didn't return a voice ID"}
            self._app.cfg.update(fish_voice_id=voice_id)
            return {"ok": True, "voice_id": voice_id}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    # sound kit (vocal set generated on this PC; effects bundled with the app)
    def make_voice_kit(self, takes: int = 4):
        """Generate Monkey's vocal set + voice reference with Fish's free model, in the background."""
        from .audio.voicekit import VoiceKit

        a = self._app
        key = keys.get("fish")
        if not key:
            return {"ok": False, "error": "Add your Fish Audio key first (Settings → API keys)."}
        if getattr(a, "_voicekit", None) is not None:
            return {"ok": False, "error": "Already making the voice set."}
        kit = VoiceKit(key, a.cfg.settings.fish_voice_id, a.cfg.data_dir, progress=lambda p: a.ui.emit("voicekit", p))
        a._voicekit = kit

        def run():
            from .audio.tts import explain_fish_error

            try:
                res = kit.run(takes=max(1, min(int(takes), 6)))
                a.ui.emit("voicekit", {"finished": True, **res})
            except Exception as exc:  # noqa: BLE001
                log.exception("voice kit failed")
                a.ui.emit("voicekit", {"finished": True, "ok": False, "error": explain_fish_error(exc)})
            finally:
                a._voicekit = None

        threading.Thread(target=run, name="voicekit", daemon=True).start()
        return {"ok": True}

    # offline voice (Pocket TTS via sherpa-onnx)
    def offline_voice_state(self):
        a = self._app
        v = getattr(a, "offline_voice", None) or a._make_offline_voice()
        ref = a.cfg.data_dir / "voice" / "monkey-ref.wav"
        return {"installed": v.installed(), "own_voice": ref.exists(), "mode": a.cfg.settings.offline_voice,
                "downloading": getattr(a, "_voice_dl", False)}

    def download_offline_voice(self):
        from .audio.offline_voice import download

        a = self._app
        if getattr(a, "_voice_dl", False):
            return {"ok": False, "error": "Already downloading."}
        a._voice_dl = True

        def run():
            try:
                res = download(a.cfg.voice_pack_dir, progress=lambda p: a.ui.emit("offlinevoice", p))
                a.ui.emit("offlinevoice", {"finished": True, **res})
                if getattr(a, "offline_voice", None) is not None:
                    a._warm_offline_voice()
            except Exception as exc:  # noqa: BLE001
                log.exception("offline voice download failed")
                a.ui.emit("offlinevoice", {"finished": True, "ok": False, "error": f"Download failed: {exc}"})
            finally:
                a._voice_dl = False

        threading.Thread(target=run, name="voice-pack", daemon=True).start()
        return {"ok": True}

    def test_offline_voice(self):
        """Say a line with the offline voice only (so you can compare it with the Fish voice)."""
        a = self._app
        v = getattr(a, "offline_voice", None)
        if v is None or not v.available():
            return {"ok": False, "error": "Download the offline voice first."}
        if a.speaker is None:
            return {"ok": False, "error": "Audio isn't running."}
        a.speaker.say("Yo! This is my offline voice. No internet, no credits, still me.", engine=v)
        return {"ok": True, "own_voice": (a.cfg.data_dir / "voice" / "monkey-ref.wav").exists()}

    def get_user_sounds(self):
        from .audio.voicekit import user_sounds

        return user_sounds(self._app.cfg.data_dir)

    def get_sound(self, rel: str):
        """A sound generated on this PC (base64 WAV), only from %APPDATA%/Monkey/sfx."""
        root = (self._app.cfg.data_dir / "sfx").resolve()
        p = (root / str(rel)).resolve()
        if root not in p.parents or p.suffix.lower() != ".wav" or not p.exists():
            return ""
        return base64.b64encode(p.read_bytes()).decode()

    def test_voice(self):
        """Check Monkey's Fish voice directly (so the reason shows up if it fails), then say a test line."""
        from .audio.tts import FishTTS, explain_fish_error, normalize_voice_id

        a = self._app
        s = a.cfg.settings
        result = {"ok": True, "engine": "fish", "voice_id": normalize_voice_id(s.fish_voice_id)}
        if not keys.get("fish"):
            result = {"ok": False, "engine": "windows", "error": "No Fish Audio key saved yet (Settings → API keys)."}
        else:
            try:
                if not s.fish_allow_free and (s.fish_model or "") == "s2.1-pro-free":
                    raise RuntimeError("free model turned off in Settings")
                fish = FishTTS(lambda: keys.get("fish"), lambda: s.fish_voice_id, lambda: s.fish_model,
                               on_model_change=lambda m: a.cfg.update(fish_model=m))
                next(iter(fish.stream_pcm("Test.")), None)
                result["model"] = fish.model()
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "engine": "windows", "error": explain_fish_error(exc)}
        a._last_voice_warn = time.time()   # the toast below already explains any problem
        a._say("Yo, it's Monkey. How I'm sounding?")
        return result

    # memory
    def export_memory(self, password: str):
        from .memory.export import export_bundle

        a = self._app
        try:
            target = Path.home() / "Documents" / f"Monkey-backup-{datetime.now():%Y%m%d-%H%M}.monkey"
            target.parent.mkdir(parents=True, exist_ok=True)
            path = export_bundle(a.cfg.data_dir, a.cfg.memory_dir, target, password or "")
            return {"ok": True, "path": str(path)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def import_memory(self, password: str):
        import webview

        from .memory.export import import_bundle

        a = self._app
        try:
            dialog = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
            picked = a.ui.window.create_file_dialog(dialog, file_types=("Monkey backup (*.monkey)",))
            if not picked:
                return {"ok": False, "error": "No file chosen"}
            restored = import_bundle(Path(picked[0]), a.cfg.data_dir, a.cfg.memory_dir, password or "")
            return {"ok": True, "restored": restored}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def open_memory_folder(self):
        folder = Path(self._app.memory.memory_root)
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]  # noqa: S606
        else:
            webbrowser.open(folder.as_uri())


# ---------------------------------------------------------------------------- tray + window
def _tray(app: MonkeyApp, window) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception as exc:  # noqa: BLE001
        log.warning("tray unavailable: %s", exc)
        return
    icon_png = resource_path("assets", "monkey.png")
    img = Image.open(icon_png).resize((64, 64)) if icon_png.exists() else Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if not icon_png.exists():
        d.ellipse((2, 2, 62, 62), fill=(108, 123, 255, 255))
        try:
            d.text((21, 13), "T", fill=(255, 255, 255, 255), font_size=34)
        except TypeError:  # older Pillow
            d.text((28, 24), "T", fill=(255, 255, 255, 255))

    def toggle_mute(icon, item):
        if app.listener:
            app.listener.muted = not app.listener.muted

    def quit_app(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Show Monkey", lambda i, it: (window.show(), window.restore()), default=True),
        pystray.MenuItem("Push to talk", lambda i, it: app.push_to_talk()),
        pystray.MenuItem("Mute microphone", toggle_mute,
                         checked=lambda it: bool(app.listener and app.listener.muted)),
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("Monkey", img, "Monkey", menu)
    icon.run_detached()


def _fix_mime_types() -> None:
    """Python's mimetypes reads the Windows registry, where other software often maps .js/.css to
    text/plain - WebView2 then refuses scripts/styles. Pin the correct types for everything we serve."""
    import mimetypes

    for ext, mime in {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
                      ".html": "text/html", ".json": "application/json", ".svg": "image/svg+xml",
                      ".glb": "model/gltf-binary", ".png": "image/png", ".jpg": "image/jpeg",
                      ".webp": "image/webp", ".woff2": "font/woff2", ".woff": "font/woff"}.items():
        mimetypes.add_type(mime, ext)


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _single_instance() -> bool:
    """True if this is the only Monkey running. Otherwise tell the user and return False (Windows only)."""
    if sys.platform != "win32":
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    run._mutex = kernel32.CreateMutexW(None, False, "Local\\MonkeyAssistant.SingleInstance")  # keep a ref
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            None, "Monkey is already running. Look for the monkey icon in the system tray "
                  "(the ^ arrow near the clock) and click it to open the window.", "Monkey", 0x40)
        return False
    return True


def run() -> None:
    if not _single_instance():
        return
    _fix_mime_types()
    import webview

    app = MonkeyApp()
    api = Api(app)
    index = resource_path("ui", "dist", "index.html")
    debug = "--debug" in sys.argv or bool(os.environ.get("MONKEY_DEBUG"))
    window = webview.create_window(
        "Monkey", url=str(index), js_api=api, width=1200, height=780, min_size=(380, 600),
        background_color="#0d0f17",
    )
    app.ui.window = window

    def on_closing():
        # Closing the window hides Monkey to the tray; he keeps listening.
        window.hide()
        return False

    window.events.closing += on_closing

    def after_start():
        try:
            log.info("UI %s via %s (engine: %s)", index, getattr(window, "real_url", "?"),
                     getattr(getattr(window, "gui", None), "__name__", "?"))
        except Exception:  # noqa: BLE001
            pass
        app.start_audio()
        _tray(app, window)
        app.updater.start_background()
        app.after_install_tasks()

    # pywebview serves ui/dist over a local HTTP server (a plain path, not file://). A fresh free port
    # each launch avoids clashing with any other copy; the UI itself is one self-contained index.html.
    webview.start(after_start, http_server=True, http_port=_free_port(), private_mode=False, debug=debug,
                  storage_path=str(app.cfg.data_dir / "webview"))


def _selftest_secrets(tmp: Path) -> list[str]:
    """Keys must survive a restart. CI runs the exe twice against the same file: the 2nd run checks that the
    secret the 1st run saved is still readable (MONKEY_SELFTEST_EXPECT_SAVED=1)."""
    from .secretstore import SecretStore

    problems: list[str] = []
    path = Path(os.environ.get("MONKEY_SELFTEST_SECRETS") or tmp / "selftest-secrets.dat")
    big = "sk-selftest-" + "x" * 5000 + "-end"  # bigger than Credential Manager allows, like a Google token
    try:
        st = SecretStore(path)
        before = st.get("selftest_big")
        if os.environ.get("MONKEY_SELFTEST_EXPECT_SAVED") and before != big:
            problems.append("a key saved by the previous run was NOT readable after restart")
        st.set("selftest_big", big)
        if SecretStore(path).get("selftest_big") != big:
            problems.append("saved key didn't read back")
        raw = path.read_text(encoding="utf-8")
        if sys.platform == "win32" and ("xxxxxxxx" in raw or '"dpapi:' not in raw):
            problems.append("keys are not DPAPI-encrypted on disk")
        # The real keys module, as Settings uses it.
        keys.use_store(tmp / "keys-selftest.dat")
        try:
            keys.set("fish", "selftest-fish-key-1234")
            if keys.saved("fish") != "selftest-fish-key-1234" or keys.hints().get("fish") != "1234":
                problems.append("keys.set/get round trip failed")
            keys.store().delete("fish")  # (not keys.delete: never touch the real Credential Manager)
        finally:
            keys.use_store(None)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"secret store: {exc}")
    return problems


def selftest() -> int:
    """Used by CI on the built .exe: load everything that doesn't need a mic or a window."""
    import tempfile

    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        app = MonkeyApp(data_dir=Path(tmp), headless=True)
        index = resource_path("ui", "dist", "index.html")
        if not index.exists():
            problems.append("UI not bundled")
        elif "<script src=" in index.read_text(encoding="utf-8", errors="ignore") or \
                'rel="stylesheet" crossorigin href=' in index.read_text(encoding="utf-8", errors="ignore"):
            problems.append("UI must be a single self-contained index.html (external JS/CSS found)")
        if not resource_path("ui", "dist", "models", "monkey.glb").exists():
            problems.append("3D monkey model not bundled")
        sfx_index = resource_path("ui", "dist", "sfx", "index.json")
        if not sfx_index.exists():
            problems.append("sound kit manifest not bundled")
        else:
            import json as _json

            first = next(iter(_json.loads(sfx_index.read_text(encoding="utf-8"))["cues"].values()), [None])[0]
            if not first or not resource_path("ui", "dist", *first.split("/")).exists():
                problems.append("sound kit files not bundled")
        if "Monkey" not in app.agent.system:
            problems.append("persona missing")
        from .brain.calibrate import SAMPLES

        for task, sample in SAMPLES.items():
            got = app.router.pick_task(sample)[0]
            if got != task and task not in ("general", "quick_fact", "hard_problem"):  # these need the classifier
                problems.append(f"policy routing: '{sample}' -> {got}, expected {task}")
        if "model_policy.md" not in app.memory.files():
            problems.append("model policy memory note missing")
        r = app.router.route("draft an email to my professor")
        if r.model != "claude-opus-5-5":
            problems.append(f"router wrong: {r}")
        if "profile.md" not in app.memory.files():
            problems.append("memory not seeded")
        from .audio.kws import find_model
        from .cleanup import plan_cleanup

        try:
            plan_cleanup()  # must not crash on a clean machine
        except Exception as exc:  # noqa: BLE001
            problems.append(f"cleanup scan: {exc}")

        problems += _selftest_secrets(Path(tmp))

        if find_model(resource_path("wakeword")) is None:
            problems.append("Hey Monkey keyword model not bundled")
        for mod in ("webview", "sounddevice", "openwakeword", "faster_whisper", "keyboard", "pystray",
                    "googleapiclient", "google_auth_oauthlib", "garminconnect", "sherpa_onnx", "sentencepiece", "velopack", "psutil", "send2trash"):
            try:
                __import__(mod)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"import {mod}: {exc}")
        logging.shutdown()
    report = "\n".join(["SELFTEST " + ("OK" if not problems else "FAILED"), *problems])
    out = os.environ.get("MONKEY_SELFTEST_OUT")
    if out:
        Path(out).write_text(report, encoding="utf-8")
    if sys.stdout is not None:
        print(report)
    return 0 if not problems else 1

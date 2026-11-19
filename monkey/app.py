"""Monkey desktop app: wires the brain, audio, integrations and UI together."""
from __future__ import annotations

import base64
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import numpy as np

from . import __version__, keys, secretstore
from .audio import conversation
from .brain import workspace
from .brain.agent import Agent
from .brain.approval import ApprovalGate
from .brain.costs import HAIKU, Ledger, Usage
from .brain.policy import ModelPolicy
from .brain.router import Router, classify_with_haiku
from .brain.tools import Services, ToolRunner
from .config import Config, resource_path
from .integrations.canvas_api import AssignmentBoard, CanvasAPI, LocalChecks
from .integrations.canvas_ics import CanvasCalendar, ICSCalendar
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
        self.windows: list = []          # extra windows that get the same events (the companion overlay)
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
                js = f"window.__monkeyEvents && window.__monkeyEvents({json.dumps(batch, default=str)})"
                for w in [self.window, *self.windows]:
                    try:
                        w.evaluate_js(js)
                    except Exception as exc:  # noqa: BLE001 - window may be closing or hidden
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
        from .memory.history import HistoryStore

        self.history = HistoryStore(self.cfg.db_path, self.cfg.settings.history_retention_days) \
            if self.cfg.settings.history_enabled else None
        self._bot_text: list[str] = []
        self._calibration = None

        # Integrations
        self.google = GoogleAuth()
        self.gmail = GmailProvider(self.google)
        self.gcal = GoogleCalendarProvider(self.google)
        self.outlook = OutlookProvider(enabled=lambda: self.cfg.settings.outlook_connected)
        self.canvas = CanvasCalendar(lambda: self.cfg.settings.canvas_ics_url)
        self.ics_calendar = ICSCalendar(lambda: keys.get("calendar_ics"))   # private iCal links (no OAuth)
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
            calendars=[self.gcal, self.outlook, self.ics_calendar, self.canvas],
            image_search=self._images, video_search=self._videos if keys.get("youtube") else None,
            image_gen=self._generate_images,
            weather=NWSWeather(lambda: (self.cfg.settings.latitude, self.cfg.settings.longitude)),
            record_usage=self._record_usage, open_url=self._open_url,
            assignments=self.board, health=self.garmin, history=self.history,
            skills=self._skills(),
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
                           emit=self._emit, speak=self._say, user_name=lambda: self.cfg.settings.user_name,
                           history=self.history, on_session_end=self._episode_async)
        threading.Thread(target=self._history_maintenance, name="history", daemon=True).start()
        from .routines.morning import MorningRoutine, Schedule

        self.morning = MorningRoutine(self.ledger.get_state, self.ledger.put_state,
                                      lambda: Schedule.from_settings(self.cfg.settings.brief_schedule),
                                      self._brief_sources, lambda: self.cfg.settings.brief_lead_min)
        self._ensure_client()

        # Audio (created in start_audio so tests/selftest don't need devices)
        self.speaker = None
        self.listener = None
        self.stt = None
        self.wakeword_label = "starting…"
        self._agent_state = "idle"
        self._listening = False
        self._in_conversation = False    # "Hey Monkey" once, then talk freely until it's over
        self._reply_done = False         # the agent finished its reply (audio may still be playing)
        self._conv_timer: threading.Timer | None = None
        self._waved = False
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent")
        self._voice_candidates: list[bytes] = []
        self.updater = Updater(self.ui.emit, enabled=lambda: self.cfg.settings.auto_update)
        from .automation.service import AutomationService

        self.automation = AutomationService(self)          # idle until computer tasks are turned on and started

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
            if exc.status_code == 401:
                return {"ok": False, "error": workspace.describe(exc), "rejected": True}
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
            on_level=self.ui.level, on_state=self._on_speaker_state, on_visemes=self.ui.visemes,
            on_fallback=self._voice_fallback,
            loudness=lambda: (bool(self.cfg.settings.voice_match_loudness),
                              max(0.25, min(2.0, (self.cfg.settings.voice_volume or 100) / 100))),
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
            from .audio.endpoint import END_SILENCE_PRESETS
            from .audio.vad import load_vad

            vad = load_vad(self.cfg.data_dir / "wakeword", resource_path("wakeword"))
            self.listener = Listener(
                on_wake=self._on_wake, on_utterance=self._on_utterance, on_timeout=self._on_timeout,
                wakeword_model=model, threshold=lambda: self.cfg.settings.wakeword_threshold,
                is_speaking=lambda: bool(self.speaker and self.speaker.speaking), vad=vad,
                end_silence_ms=lambda: END_SILENCE_PRESETS.get(self.cfg.settings.end_silence, 1400),
                on_conversation_idle=lambda: self.end_conversation("quiet"),
                on_reconnect=lambda msg: self._emit("hint", {"text": f"🎙 {msg}"}),
            )
            try:
                self.listener.start()
                self._emit("hint", {"text": f"Say “{label.split(' (')[0]}” or press {s.push_to_talk_hotkey}"})
            except Exception as exc:  # noqa: BLE001
                self._emit("error", {"message": f"Microphone unavailable: {exc}"})

        threading.Thread(target=init_listener, name="listener-init", daemon=True).start()
        self._register_hotkey()

    def _skills(self):
        from .skills.loader import SkillLibrary

        bundled = Path(__file__).resolve().parent / "skills"
        if not bundled.exists():
            bundled = resource_path("monkey", "skills")
        return SkillLibrary(bundled, self.cfg.data_dir / "skills")

    # ------------------------------------------------------------------ morning brief sources
    def _calendars(self) -> list:
        # your calendars (Google sign-in, Outlook, private iCal links); never the Canvas feed: due dates aren't classes
        return [p for p in (self.gcal, self.outlook, self.ics_calendar) if self._ok(p)]

    @staticmethod
    def _ok(p) -> bool:
        try:
            return bool(p.available())
        except Exception:  # noqa: BLE001
            return False

    def canvas_token_status(self) -> dict:
        from .routines.canvas_token import status

        return status(self.canvas_api.available(), self.cfg.settings.canvas_token_expires,
                      getattr(self.canvas_api, "token_rejected", False))

    def _brief_sources(self):
        from datetime import datetime as _dt, time as _time
        from .routines.morning import TZ, Sources

        cals = self._calendars()

        def events_today(day):
            start = _dt.combine(day, _time(0, 0), tzinfo=TZ)
            out = []
            for p in cals:
                out += p.list_events(start, start + timedelta(days=1))
            return out

        mails = [p for p in (self.gmail, self.outlook) if self._ok(p)]

        def emails():
            out = []
            for p in mails:
                out += p.list_recent(max_results=10, unread_only=True, query="")
            return sorted(out, key=lambda e: e.received, reverse=True)

        board_ok = self.canvas_api.available() or self._ok(self.canvas)

        def sleep():
            from .integrations.garmin import summarize

            return {"summary": summarize(self.garmin.health("today"))}

        return Sources(
            events_today=events_today if cals else None,
            assignments=(lambda: self.board.load()) if board_ok else None,
            emails=emails if mails else None,
            weather=self.services.weather,
            sleep=sleep if self.garmin.connected() else None,
            canvas_token=self.canvas_token_status,
            class_notes=lambda: self.memory.read("classes.md") or "",
        )

    # ------------------------------------------------------------------ conversation history (episodes)
    def _history_maintenance(self) -> None:
        """Startup: apply retention, close sessions left open by a quit/crash, summarize unsummarized ones."""
        if self.history is None:
            return
        try:
            removed = self.history.prune()
            if removed:
                log.info("history: removed %d conversations past the retention window", removed)
            self.history.close_stale(active_sid=self.agent.session_id)
            self.history.index_facts(Path(self.memory.memory_root))
            for sid in self.history.needs_episode():
                self._summarize_episode(sid)
        except Exception:  # noqa: BLE001
            log.warning("history maintenance failed", exc_info=True)

    def _episode_async(self, sid: str) -> None:
        threading.Thread(target=self._summarize_episode, args=(sid,), name="episode", daemon=True).start()

    def _summarize_episode(self, sid: str) -> None:
        from .memory.episodes import summarize

        if self.history is None:
            return
        try:
            msgs = self.history.messages(sid)
            if not any(m["role"] == "user" for m in msgs):
                return
            client = self._ensure_client()
            ep, usage = summarize(client, msgs, HAIKU)
            if usage is not None:
                self._record_usage(HAIKU, "low", "memory:episode", usage)
            self.history.add_episode(sid, ep["summary"], ep["topics"], ep["decisions"], ep["open_items"], ep["source"])
        except Exception:  # noqa: BLE001
            log.warning("episode summary failed", exc_info=True)

    def _register_hotkey(self) -> None:
        try:
            import keyboard

            keyboard.add_hotkey(self.cfg.settings.push_to_talk_hotkey, self.push_to_talk)
        except Exception as exc:  # noqa: BLE001
            log.warning("hotkey unavailable: %s", exc)
        try:
            import keyboard

            # Emergency stop for computer tasks: works from any app, even with Monkey's windows hidden.
            keyboard.add_hotkey(self.cfg.settings.automation_stop_hotkey, self.automation.emergency_stop)
        except Exception as exc:  # noqa: BLE001
            log.warning("emergency-stop hotkey unavailable: %s", exc)

    # ------------------------------------------------------------------ state + events
    def _emit(self, name: str, payload: dict | None = None) -> None:
        if name == "state":
            self._agent_state = (payload or {}).get("state", "idle")
            self._publish_state()
            return
        if name in ("user", "delta", "done"):
            self._remember_chat(name, payload or {})
        if name == "done":
            self._reply_done = True
            self._maybe_continue_conversation()
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
        elif self._agent_state == "idle" and self.listener is not None and self.listener.mode == "conversation":
            state = "listening"
        else:
            state = self._agent_state
        self.ui.emit("state", {"state": state, "conversation": self._in_conversation})

    def _say(self, sentence: str) -> None:
        if self.speaker is not None:
            self.speaker.say(sentence)

    # ------------------------------------------------------------------ voice flow
    # ---- conversation mode ------------------------------------------------
    def _start_conversation(self) -> None:
        if self.cfg.settings.conversation_mode:
            self._in_conversation = True

    def _on_speaker_state(self, speaking: bool) -> None:
        if not speaking:
            self._maybe_continue_conversation()
        self._publish_state()

    def _maybe_continue_conversation(self) -> None:
        """After his reply has been said in full, listen for your next turn (no wake word)."""
        if not (self._in_conversation and self._reply_done) or self.listener is None:
            return
        if self.speaker is not None and self.speaker.speaking:
            return                                    # still talking; called again when he stops
        if self._conv_timer is not None:
            self._conv_timer.cancel()

        def open_mic():
            self._conv_timer = None
            busy = self.speaker is not None and self.speaker.speaking
            if not self._in_conversation or busy or self._listening or self.listener is None \
                    or self.listener.mode != "wake" or self.listener.muted:
                return
            self._reply_done = False
            self.listener.enter_conversation(self.cfg.settings.conversation_idle_s)
            self._publish_state()

        self._conv_timer = threading.Timer(0.3, open_mic)    # let his last word die out of the room first
        self._conv_timer.daemon = True
        self._conv_timer.start()

    def end_conversation(self, reason: str = "", cancel: bool = False) -> None:
        was = self._in_conversation
        self._in_conversation = False
        self._reply_done = False
        if cancel:                                    # the ✕ on "Listening…": stop the mic now, not at its timeout
            self._listening = False
            if self._agent_state == "listening":
                self._agent_state = "idle"
            if self.listener is not None and hasattr(self.listener, "cancel"):
                self.listener.cancel()
        if self._conv_timer is not None:
            self._conv_timer.cancel()
            self._conv_timer = None
        if self.listener is not None:
            self.listener.end_conversation()
        if was:
            log.info("conversation over (%s)", reason or "ended")
        self._publish_state()

    def _on_wake(self) -> None:
        if self.speaker:
            self.speaker.stop()
        self.agent.cancel()
        self._start_conversation()
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
        self.end_conversation("nothing said after the wake word")

    def _on_utterance(self, audio: np.ndarray) -> None:
        source = getattr(self.listener, "last_source", "wake")
        self._listening = False
        self._agent_state = "transcribing"
        self._publish_state()
        try:
            text = self.stt().transcribe(audio) if self.stt else ""
        except Exception as exc:  # noqa: BLE001
            log.exception("speech recognition failed")
            self._emit("warning", {"message": explain_stt_error(exc)})
            text = ""
        text = conversation.strip_wake(text or "")
        self.ui.emit("heard", {"text": text})
        if source == "conversation" and not conversation.worth_answering(text):
            # Background noise, someone else talking, an "uh": keep waiting, same quiet deadline.
            log.info("ignored a %d-character utterance in conversation mode", len(text))   # never log speech
            self._agent_state = "idle"
            if self._in_conversation and self.listener is not None:
                self.listener.enter_conversation(self.cfg.settings.conversation_idle_s)
            self._publish_state()
            return
        if self._in_conversation and conversation.is_goodbye(text):
            self._say_goodbye(text)
            return
        if text and len(text.strip(" .")) > 1:
            self.ask(text)
        else:
            self._agent_state = "idle"
            if source == "conversation":
                self._reply_done = True
                self._maybe_continue_conversation()
            else:
                self.end_conversation("nothing understood after the wake word")   # likely a false wake
            self._publish_state()

    def _say_goodbye(self, text: str) -> None:
        """'Thanks' / 'that's all' / 'bye': short sign-off, no model call, back to needing "Hey Monkey"."""
        import random

        self.end_conversation("goodbye")
        line = random.choice(conversation.SIGN_OFFS)
        self.ui.emit("user", {"text": text})
        self.ui.emit("delta", {"text": line})
        self.ui.emit("done", {"text": line})
        self._agent_state = "idle"
        self._publish_state()
        self._say(line)
        if "sleep" in text.lower():
            self.ui.emit("emote", {"name": "sleep"})

    def ask(self, text: str, importance: str | None = None, typed: bool = False) -> None:
        if self._ensure_client() is None:
            self._emit("error", {"message": "Paste your Claude key in Settings → Start here first."})
            return
        self.agent.cancel()
        if self.speaker:
            self.speaker.stop()
        self._reply_done = False
        if typed:
            # Typing means "I'm not talking right now": don't open the mic for a follow-up afterwards (testers read
            # "Listening…" after a typed question as Monkey eavesdropping). Voice turns still continue hands-free.
            self._in_conversation = False
            if self._listening:                       # mic opened (e.g. a mic click), then they typed instead
                self._listening = False
                if self.listener is not None and hasattr(self.listener, "cancel"):
                    self.listener.cancel()
        if self.listener is not None and self.listener.mode == "conversation":
            self.listener.end_conversation()          # only listen again once he has answered

        self.agent.on_workspace_error = self._fix_workspace   # re-armed each request; used at most once

        def run():
            try:
                self.agent.handle(text, importance, source="typed" if typed else "voice")
            except Exception as exc:  # noqa: BLE001 - the agent rolls itself back; just make sure we're usable
                log.exception("agent failed")
                self._listening = False
                if self.speaker is not None and self.speaker.speaking:
                    self.speaker.stop()
                self._emit("warning", {"message": f"Something broke ({type(exc).__name__}: {exc}). "
                                                  "Just ask again; no need to start over."})
                self._emit("state", {"state": "idle"})
                self._reply_done = True
                self._maybe_continue_conversation()

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
        from .links import launch_url

        launch_url(url)

    @staticmethod
    def _open_path(folder: Path) -> None:
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]  # noqa: S606
        else:
            webbrowser.open(Path(folder).as_uri())

    def _unseen_transfer(self) -> dict | None:
        """What a "Move to a new PC" import brought over, until the UI has shown it once."""
        try:
            d = json.loads((self.cfg.data_dir / "last_transfer.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return None if d.get("seen") else d


def explain_stt_error(exc: Exception) -> str:
    """Plain words for a failed transcription (the bare exception name told nobody anything)."""
    msg = str(exc)
    low = msg.lower()
    if "cublas" in low or "cudnn" in low or "cuda" in low:
        return "Speech recognition hit a graphics-card problem. Monkey switched to the processor; say it again."
    if "no such file" in low or "model.bin" in low or "unable to open" in low:
        return ("Speech recognition's model files are missing or damaged. Restart Monkey with internet on so he can "
                "download them again (about 250 MB, once).")
    if "memory" in low:
        return "Speech recognition ran out of memory. Close some apps and try again."
    return f"Speech recognition failed ({type(exc).__name__}: {msg[:120]}). Try again; if it keeps happening, " \
           "run Settings → Check everything and send the report."


def explain_download_error(exc: Exception) -> str:
    """Plain words for a failed download (testers saw raw 'HTTP Error 403: Forbidden')."""
    text = f"{type(exc).__name__} {exc}".lower()
    if any(w in text for w in ("403", "401", "forbidden")):
        why = "the download server refused the connection (a school or work network can block it)"
    elif any(w in text for w in ("timed out", "timeout", "urlopen error", "connection", "getaddrinfo", "name resolution")):
        why = "the internet connection dropped or isn't available"
    elif any(w in text for w in ("no space", "disk", "errno 28")):
        why = "your PC is out of disk space (it needs about 400 MB free)"
    else:
        why = "something went wrong while downloading"
    return f"Couldn't download the backup voice: {why}. Try again on another network, or later."


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
                "calendar_ics": ks.get("calendar_ics", False),
            },
            "transfer": a._unseen_transfer(),
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
        if name == "google_client":
            from .integrations.google import validate_client

            try:
                validate_client(value)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
        if name == "calendar_ics" and not ICSCalendar(lambda: value).urls():
            return {"ok": False, "error": "Paste the calendar's https:// (or webcal://) iCal link."}
        try:
            keys.set(name, value)
        except Exception as exc:  # noqa: BLE001
            log.exception("saving key %s failed", name)
            return {"ok": False, "error": str(exc)}
        a = self._app
        if name == "anthropic":
            a.cfg.update(first_run_complete=True, anthropic_workspace_id="")
            check = a.verify_anthropic()
            if check.get("rejected"):          # a wrong or half-pasted key: don't keep it around looking "saved"
                keys.delete(name)
                a.client = None
                return {"ok": False, "error": check.get("error", "Anthropic didn't accept the key.")}
            if not check.get("ok"):
                return {"ok": True, "hint": keys.hints().get(name, ""), "warning": check.get("error", "")}
            return {"ok": True, "hint": keys.hints().get(name, ""), "note": check.get("note", "")}
        if name == "youtube":
            a.services.video_search = a._videos
        if name == "calendar_ics":
            from .routines.morning import TZ

            now = datetime.now(TZ)
            try:
                a.ics_calendar._cache.clear()
                n = len(a.ics_calendar.list_events(now, now + timedelta(days=7)))
                return {"ok": True, "note": f"Calendar link works: {n} events in the next 7 days."}
            except Exception as exc:  # noqa: BLE001
                return {"ok": True, "warning": f"Saved, but reading it failed ({type(exc).__name__}). "
                                               "Check that it's the *secret* iCal address."}
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
        self._app.ask(str(text)[:8000], importance if importance in ("low", "normal", "high") else None, typed=True)

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

    # routing benchmark (runs here, with the key Monkey already stores; ~14 Haiku calls, < $0.01)
    def routing_benchmark(self):
        from .brain.bench_routing import live, offline, summary_text

        a = self._app
        if getattr(a, "_bench_running", False):
            return {"ok": False, "error": "The benchmark is already running."}
        client = a._ensure_client()
        if client is None:
            return {"ok": False, "error": "Add your Anthropic key first (Settings → API keys)."}
        a._bench_running = True

        def run():
            try:
                res = {"offline": offline()}
                res["live"] = live(client, on_progress=lambda i, n, t: a.ui.emit("bench", {"done": i, "total": n}),
                                   record=lambda u: a._record_usage(HAIKU, "low", "benchmark:routing", u))
                res["summary"] = summary_text(res)
                (a.cfg.data_dir / "bench_routing.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
                a.ui.emit("bench", {"finished": True, "ok": True, "summary": res["summary"],
                                    "path": str(a.cfg.data_dir / "bench_routing.json"),
                                    "misses": res["live"]["misses"][:6]})
            except Exception as exc:  # noqa: BLE001
                log.exception("routing benchmark failed")
                a.ui.emit("bench", {"finished": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]})
            finally:
                a._bench_running = False

        threading.Thread(target=run, name="bench", daemon=True).start()
        return {"ok": True, "started": True}

    # morning brief (in-app preview; no external notifications)
    def brief_status(self):
        from datetime import datetime as _dt

        a = self._app
        st = a.morning.status(_dt.now().astimezone())
        return {**st, "lead_min": a.cfg.settings.brief_lead_min, "speak": a.cfg.settings.brief_speak_on_open,
                "canvas": a.canvas_token_status(), "calendar": bool(a._calendars()),
                "task": self._brief_task_registered()}

    def _brief_task_registered(self) -> bool:
        from .routines.scheduler import is_registered

        a = self._app
        if getattr(a, "_brief_task_enabled", None) is None:
            a._brief_task_enabled = is_registered()     # asked Task Scheduler once; Enable/Disable keep it current
        return bool(a._brief_task_enabled)

    def brief_preview(self, opened: bool = True, refresh: bool = False):
        """The app was opened: today's brief (cached, or built now; a draft if the schedule isn't confirmed).
        refresh=True: you just changed your setup (accounts, schedule), so rebuild it with what's connected now."""
        from datetime import datetime as _dt

        a = self._app
        if not a.cfg.settings.brief_enabled:
            return {"ok": False, "error": "The morning brief is off."}
        try:
            b = a.morning.run(_dt.now().astimezone(), "app_open", rebuild=bool(refresh))
        except Exception as exc:  # noqa: BLE001
            log.exception("brief failed")
            return {"ok": False, "error": f"Couldn't build the brief ({type(exc).__name__})."}
        if b is None:
            return {"ok": True, "brief": None}
        key = f"brief-spoken:{b['day']}"
        if opened and a.cfg.settings.brief_speak_on_open and b["kind"] != "draft" and not a.ledger.get_state(key):
            a.ledger.put_state(key, True, time.time())
            a._say(b["spoken"])                    # two short sentences at most; details stay on screen
        return {"ok": True, "brief": b}

    def brief_candidates(self):
        """Recurring calendar events over the next two weeks, as a schedule for the user to confirm."""
        from datetime import datetime as _dt

        from .routines.morning import TZ, candidate_schedule

        from .routines.morning import schedule_from_notes

        a = self._app
        cals = a._calendars()
        found, source = {}, ""
        if cals:
            now = _dt.now(TZ)
            events = []
            for p in cals:
                try:
                    events += p.list_events(now, now + timedelta(days=14))
                except Exception as exc:  # noqa: BLE001
                    log.warning("calendar read failed: %s", type(exc).__name__)
            found, source = candidate_schedule(events, now), "your calendar"
        if not found:
            notes = schedule_from_notes(a.memory.read("classes.md") or "")
            if notes:
                found, source = notes, "your notes"
        if not found and not cals:
            return {"ok": False, "error": "To detect your classes, add your calendar link (Settings → Accounts) or connect "
                                          "Google. Or just type your first class time for each day here."}
        if not found:
            return {"ok": False, "error": "Monkey looked at the next 2 weeks of your calendar and didn't see classes that repeat "
                                          "each week. If your classes are on a different calendar, add its link in Settings → "
                                          "Accounts. Or just type your first class time for each day here."}
        return {"ok": True, "candidates": found, "source": source}

    def brief_confirm(self, by_day: dict, source: str = "confirmed in app"):
        """The user confirmed (or edited) their earliest weekday class times. Only this enables timed briefs."""
        from datetime import datetime as _dt

        from .routines.morning import SCHOOL_DAYS, Schedule, _hhmm

        clean = {k: v for k, v in (by_day or {}).items() if k in SCHOOL_DAYS and _hhmm(v) is not None}
        sched = Schedule(clean, str(source)[:80], _dt.now().isoformat(timespec="minutes") if clean else None)
        self._app.cfg.update(brief_schedule=sched.to_settings())
        return self.brief_status()

    def brief_task_preview(self):
        from .routines.morning import Schedule
        from .routines.scheduler import task_xml

        a = self._app
        exe = sys.executable if getattr(sys, "frozen", False) else "Monkey.exe"
        try:
            return {"ok": True, "xml": task_xml(exe, Schedule.from_settings(a.cfg.settings.brief_schedule),
                                                a.cfg.settings.brief_lead_min)}
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "needs_schedule": True}

    def brief_task_enable(self):
        """Register the Windows scheduled task (explicit click only). It prepares the brief; it never notifies."""
        from .routines.scheduler import register

        prev = self.brief_task_preview()
        if not prev.get("ok"):
            return prev
        try:
            register(prev["xml"])
            self._app._brief_task_enabled = True
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def brief_task_disable(self):
        from .routines.scheduler import unregister

        unregister()
        self._app._brief_task_enabled = False
        return {"ok": True}

    # memory inspector, history controls, context import
    def memory_search(self, query: str, scope: str = "all", include_history: bool = False):
        a = self._app
        if a.history is None:
            return {"ok": False, "error": "Conversation history is turned off (Settings → Memory)."}
        from .memory.history import hits_json

        a.history.index_facts(Path(a.memory.memory_root))
        return {"ok": True, "hits": hits_json(a.history.search(str(query)[:300], scope=scope, limit=20,
                                                               include_superseded=bool(include_history)))}

    INTERNAL_MEMORY = ("model_policy.md", "sites.md", "superseded.md")

    def memory_list(self):
        """Everything Monkey currently knows about you, by file (the inspector shows this before any search)."""
        from .memory import facts as F

        a = self._app
        tech = bool(a.cfg.settings.show_tech_details)
        out = [{"id": f.id, "file": f.file, "section": f.section, "text": f.text, "date": f.date, "source": f.src,
                "sensitive": f.sensitive}
               for f in F.all_facts(Path(a.memory.memory_root))
               if f.status == "current" and (tech or f.file not in self.INTERNAL_MEMORY)]
        return {"ok": True, "facts": out}

    def memory_edit(self, fact_id: str, new_text: str):
        """Correct a fact from the inspector; the old version is kept as superseded history."""
        from .memory import facts as F

        a = self._app
        new_text = str(new_text or "").strip()
        if not new_text:
            return {"ok": False, "error": "Type the corrected text first."}
        try:
            old, new = F.update_fact(Path(a.memory.memory_root), str(fact_id), new_text, src="user_edit")
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}
        if a.history is not None:
            a.history.index_facts(Path(a.memory.memory_root), force=True)
        return {"ok": True, "id": new.id, "text": new.text}

    def memory_forget(self, fact_id: str):
        from .memory import facts as F

        a = self._app
        try:
            f = F.forget_fact(Path(a.memory.memory_root), str(fact_id))
            if a.history is not None:
                a.history.tombstone(f.text)
                a.history.index_facts(Path(a.memory.memory_root), force=True)
            return {"ok": True, "file": f.file}
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}

    def history_stats(self):
        a = self._app
        s = a.cfg.settings
        st = a.history.stats() if a.history is not None else {}
        return {"enabled": s.history_enabled, "retention_days": s.history_retention_days, **st}

    def history_delete(self, scope: str = "all", days: int = 0):
        a = self._app
        if a.history is None:
            return {"ok": False, "error": "History is off."}
        n = a.history.delete_all() if scope == "all" else a.history.prune(int(days))
        return {"ok": True, "deleted": n}

    def history_export(self):
        a = self._app
        if a.history is None:
            return {"ok": False, "error": "History is off."}
        target = Path.home() / "Documents" / f"Monkey-conversations-{datetime.now():%Y%m%d-%H%M}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(a.history.export(), indent=1), encoding="utf-8")
        return {"ok": True, "path": str(target)}

    def import_preview(self):
        """Pick .md context files (e.g. from a ChatGPT profile pack) and preview the merge. Nothing is written yet."""
        import webview

        from .memory.importer import plan_import

        a = self._app
        dialog = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        picked = a.ui.window.create_file_dialog(dialog, allow_multiple=True, file_types=("Markdown (*.md)",))
        if not picked:
            return {"ok": False, "error": "Nothing picked."}
        try:
            incoming = {Path(p).name: Path(p).read_text(encoding="utf-8") for p in picked
                        if Path(p).name.lower() not in ("readme_import.md", "implementation_brief.md")}
            plan = plan_import(Path(a.memory.memory_root), incoming)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        a._import_plan = plan
        return {"ok": True, **plan.summary()}

    def import_apply(self):
        from .memory.importer import apply_import

        a = self._app
        plan = getattr(a, "_import_plan", None)
        if plan is None:
            return {"ok": False, "error": "Preview an import first."}
        backup = apply_import(Path(a.memory.memory_root), plan)
        a._import_plan = None
        a._last_import_backup = backup
        if a.history is not None:
            a.history.index_facts(Path(a.memory.memory_root), force=True)
        return {"ok": True, "backup": str(backup)}

    def import_undo(self):
        from .memory.importer import restore_backup

        a = self._app
        backup = getattr(a, "_last_import_backup", None)
        if backup is None:
            return {"ok": False, "error": "No import to undo this session."}
        restored = restore_backup(Path(a.memory.memory_root), backup)
        if a.history is not None:
            a.history.index_facts(Path(a.memory.memory_root), force=True)
        return {"ok": True, "restored": restored}

    def end_conversation(self):
        """The ✕ on the "Listening…" chip: stop listening now (even mid-recording), back to the wake word."""
        self._app.end_conversation("closed", cancel=True)

    def open_log(self):
        p = self._app.cfg.data_dir / "monkey.log"
        try:
            if sys.platform == "win32":
                os.startfile(str(p))  # type: ignore[attr-defined]
            return {"ok": True, "path": str(p)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "path": str(p)}

    def new_conversation(self):
        self._app.end_conversation("new conversation")
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
        """Starts the browser sign-in in the background and returns at once. Progress comes as "google" events:
        opening (with the sign-in link, in case the browser didn't come up) -> done | error."""
        from .integrations.google import SignInCancelled, validate_client

        a = self._app
        if getattr(a, "_google_signing_in", False):
            return {"ok": False, "error": "Already waiting for you to finish signing in in the browser."}
        try:
            validate_client(keys.get("google_client") or "")
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "needs_client": True}
        a._google_signing_in = True

        def run():
            try:
                a.google.sign_in(on_url=lambda url: a.ui.emit("google", {"stage": "opening", "url": url}))
                try:                                  # "Connected as you@gmail.com" (testers asked which account)
                    prof = a.google.service("gmail", "v1").users().getProfile(userId="me").execute()
                    a.cfg.update(google_account=str(prof.get("emailAddress", ""))[:120])
                except Exception:  # noqa: BLE001
                    pass
                found = {}
                try:                                  # proof both halves work (testers weren't sure the calendar did)
                    found["emails"] = len(a.gmail.list_recent(max_results=10))
                    now = datetime.now().astimezone()
                    found["events"] = len(a.gcal.list_events(now, now + timedelta(days=7)))
                except Exception:  # noqa: BLE001
                    pass
                a.ui.emit("google", {"stage": "done", **found})
            except SignInCancelled:
                a.ui.emit("google", {"stage": "cancelled"})
            except Exception as exc:  # noqa: BLE001
                log.warning("google sign-in failed: %s", type(exc).__name__)
                a.ui.emit("google", {"stage": "error", "message": str(exc)})
            finally:
                a._google_signing_in = False

        threading.Thread(target=run, name="google-signin", daemon=True).start()
        return {"ok": True, "started": True}

    def health_check(self):
        """Settings → Check everything. Runs in the background; the result comes as a "health" event."""
        a = self._app
        if getattr(a, "_health_running", False):
            return {"ok": False, "error": "The check is already running."}
        a._health_running = True

        def run():
            from .health import as_dicts, report_text, run_checks

            try:
                checks = run_checks(a, self)
                a.ui.emit("health", {"ok": True, "checks": as_dicts(checks), "report": report_text(checks)})
            except Exception as exc:  # noqa: BLE001
                log.exception("health check failed")
                a.ui.emit("health", {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            finally:
                a._health_running = False

        threading.Thread(target=run, name="health-check", daemon=True).start()
        return {"ok": True, "started": True}

    def google_sign_in_cancel(self):
        """Stop waiting for the browser sign-in (Google showed an error page and won't come back)."""
        a = self._app
        if not getattr(a, "_google_signing_in", False):
            return {"ok": True, "was_waiting": False}
        return {"ok": True, "was_waiting": bool(a.google.cancel())}

    def google_client_file(self):
        """Pick the client_secret_*.json downloaded from Google Cloud (Desktop app) and save it."""
        import webview

        from .integrations.google import validate_client

        a = self._app
        dialog = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        picked = a.ui.window.create_file_dialog(dialog, file_types=("Google client JSON (*.json)",))
        if not picked:
            return {"ok": False, "error": "Nothing picked."}
        try:
            text = Path(picked[0]).read_text(encoding="utf-8")
            validate_client(text)
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        return self.save_key("google_client", text)

    def google_sign_out(self):
        self._app.google.sign_out()
        self._app.cfg.update(google_account="")

    def test_outlook(self):
        """The Connect button: the only place Monkey starts Outlook on its own. Success turns Outlook on."""
        from .integrations.outlook_com import installed

        o, st = self._app.outlook, self._app.cfg.settings
        if sys.platform != "win32":
            return {"ok": False, "error": "Outlook only works on Windows"}
        if not installed():
            return {"ok": False, "error": "Classic Outlook isn't installed (the \"new Outlook\" can't be read by apps). "
                                         "Install Microsoft 365 Apps from UW's Office 365 page, or use a calendar link."}
        try:
            got = o.list_recent(max_results=1)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{exc}. Make sure classic Outlook is installed and signed in to wisc.edu."}
        st.outlook_connected = True
        self._app.cfg.save()
        return {"ok": True, "count": len(got)}

    def disconnect_outlook(self):
        self._app.cfg.settings.outlook_connected = False
        self._app.cfg.save()
        return {"ok": True}

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
                a.ui.emit("offlinevoice", {"finished": True, "ok": False, "error": explain_download_error(exc)})
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
    def export_memory(self, password: str, include_keys: bool = True):
        """Settings -> Memory -> Move to a new PC -> Export: one encrypted file with everything personal."""
        from .memory.export import NO_KEY, export_bundle

        a = self._app
        try:
            ks = {}
            if include_keys:
                ks = {k: v for k in keys.KNOWN_KEYS if k not in NO_KEY and (v := keys.get(k))}
            target = Path.home() / "Documents" / f"Monkey-transfer-{datetime.now():%Y%m%d-%H%M}.monkey"
            path = export_bundle(a.cfg.data_dir, a.cfg.memory_dir, target, password or "", keys=ks,
                                 version=__version__)
            return {"ok": True, "path": str(path), "folder": str(path.parent), "keys": sorted(ks),
                    "mb": round(path.stat().st_size / 1e6, 1)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def import_memory(self, password: str):
        """Pick a .monkey file; keys are saved right away, files are swapped in when Monkey restarts."""
        import webview

        from .memory.export import stage_import

        a = self._app
        try:
            dialog = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
            picked = a.ui.window.create_file_dialog(dialog, file_types=("Monkey transfer file (*.monkey)",))
            if not picked:
                return {"ok": False, "error": "No file chosen"}
            staged = stage_import(Path(picked[0]), a.cfg.data_dir, password or "")
            saved, failed = [], []
            for name, value in staged["keys"].items():
                if name not in keys.KNOWN_KEYS:
                    continue
                try:
                    keys.set(name, value)
                    saved.append(name)
                except Exception:  # noqa: BLE001
                    failed.append(name)
            return {"ok": True, "files": len(staged["files"]), "keys": saved, "keys_failed": failed,
                    "restart": True, "from_version": staged["manifest"].get("version", "")}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def restart_app(self):
        """Relaunch Monkey (after an import). Waits for this copy to exit so the single-instance lock is free."""
        exe = sys.executable
        args = [exe, *sys.argv[1:]] if getattr(sys, "frozen", False) else [exe, "-m", "monkey"]
        try:
            if sys.platform == "win32":
                cmdline = subprocess.list2cmdline(args)
                subprocess.Popen(f'cmd /c timeout /t 2 /nobreak >nul & start "" {cmdline}', shell=False,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                subprocess.Popen(["sh", "-c", 'sleep 2; exec "$@"', "sh", *args])
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{exc}. Quit Monkey from the tray and open it again."}
        threading.Timer(0.3, lambda: os._exit(0)).start()
        return {"ok": True}

    def transfer_seen(self):
        p = self._app.cfg.data_dir / "last_transfer.json"
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d["seen"] = True
            p.write_text(json.dumps(d, indent=1), encoding="utf-8")
        except (OSError, ValueError):
            pass
        return {"ok": True}

    def open_documents_folder(self):
        self._app._open_path(Path.home() / "Documents")
        return {"ok": True}

    # ------------------------------------------------------------ computer tasks (docs/adr/0001-computer-agent.md)
    def window_role(self):
        return "main"

    def automation_state(self):
        return self._app.automation.state()

    def automation_enable(self, on: bool):
        self._app.cfg.update(computer_access=bool(on))
        if not on:
            self._app.automation.emergency_stop()
        self._app.ui.emit("automation_enabled", {"on": bool(on)})
        _overlay_visibility(self._app)
        return self._app.automation.state()

    def automation_start(self, objective: str, start_url: str, domains: list, mode: str = "managed_browser",
                         send_screenshots: bool = False, confirm_medium: bool = False):
        return self._app.automation.start(objective, start_url, list(domains or []), mode, send_screenshots,
                                          confirm_medium)

    def automation_demo(self):
        return self._app.automation.demo_start()

    def automation_control(self, action: str, task_id: str):
        return self._app.automation.control(action, task_id)

    def automation_approve(self, task_id: str, approval_id: str, token: str, allow: bool = True):
        return self._app.automation.approve(task_id, approval_id, token, allow)

    def automation_history(self, task_id: str):
        return self._app.automation.history(task_id)

    def automation_stop_all(self):
        self._app.automation.emergency_stop()
        return {"ok": True}

    def automation_windows(self):
        return self._app.automation.windows()

    def overlay(self, action: str, value=None):
        """show | hide | mode (compact/expanded/minimized) | geometry ({x,y,w,h}) | expand (bring the main window)."""
        a = self._app
        win = getattr(a, "_overlay_window", None)
        if action == "geometry" and isinstance(value, dict):
            a.cfg.update(overlay_geom={k: int(v) for k, v in value.items() if k in ("x", "y", "w", "h")})
        elif action == "mode" and value in ("compact", "expanded", "minimized"):
            a.cfg.update(overlay_mode=value)
            size = {"compact": (260, 352), "expanded": (380, 560), "minimized": (96, 96)}[value]
            if win is not None:
                win.resize(*size)
        elif action in ("show", "hide"):
            a.cfg.update(overlay_enabled=action == "show")
            _overlay_visibility(a)
        elif action == "expand":
            main = getattr(a, "_main_window", None)
            if main is not None:
                main.show()
                main.restore()
        elif action == "hit" and isinstance(value, dict):
            from . import desktop_overlay

            desktop_overlay.set_hit_rects(value.get("rects", []), float(value.get("dpr", 1)))
        return {"ok": True, "mode": a.cfg.settings.overlay_mode}

    def open_memory_folder(self):
        folder = Path(self._app.memory.memory_root)
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]  # noqa: S606
        else:
            webbrowser.open(folder.as_uri())


# ---------------------------------------------------------------------------- tray + window
class OverlayApi(Api):
    """The companion window's API: identical, but it knows it's the overlay (so the UI renders the compact view)."""

    def window_role(self):
        return "overlay"


def _overlay_visibility(app: MonkeyApp) -> None:
    win = getattr(app, "_overlay_window", None)
    if win is None:
        return
    want = app.cfg.settings.computer_access and app.cfg.settings.overlay_enabled
    try:
        win.show() if want else win.hide()
    except Exception:  # noqa: BLE001
        log.debug("overlay show/hide failed", exc_info=True)


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
            if app.listener.muted:
                app.end_conversation("muted")

    def quit_app(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Show Monkey", lambda i, it: (window.show(), window.restore()), default=True),
        pystray.MenuItem("Push to talk", lambda i, it: app.push_to_talk()),
        pystray.MenuItem("Show companion", lambda i, it: (app.cfg.update(overlay_enabled=True),
                                                          _overlay_visibility(app)),
                         visible=lambda it: bool(app.cfg.settings.computer_access)),
        pystray.MenuItem("Stop all computer tasks", lambda i, it: app.automation.emergency_stop(),
                         visible=lambda it: bool(app.cfg.settings.computer_access)),
        pystray.MenuItem("Mute microphone", toggle_mute,
                         checked=lambda it: bool(app.listener and app.listener.muted)),
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("Monkey", img, "Monkey", menu)
    icon.run_detached()
    app._tray_icon = icon


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


SHOW_EVENT = "Local\\MonkeyAssistant.Show"


def _single_instance() -> bool:
    """True if this is the only Monkey running. If he's already running (e.g. hidden in the tray after closing
    the window), ask that copy to show its window and return False (Windows only)."""
    if sys.platform != "win32":
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    run._mutex = kernel32.CreateMutexW(None, False, "Local\\MonkeyAssistant.SingleInstance")  # keep a ref
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ev = kernel32.OpenEventW(0x0002, False, SHOW_EVENT)          # EVENT_MODIFY_STATE
        if ev and kernel32.SetEvent(ev):
            kernel32.CloseHandle(ev)
            return False                                              # the running copy brings its window up
        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            None, "Monkey is already running. Look for the monkey icon in the system tray "
                  "(the ^ arrow near the clock) and click it to open the window.", "Monkey", 0x40)
        return False
    return True


def _listen_for_show(window) -> None:
    """Opening Monkey again (Start menu / desktop shortcut) while he's in the tray brings the window back."""
    if sys.platform != "win32":
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    ev = kernel32.CreateEventW(None, False, False, SHOW_EVENT)        # auto-reset
    if not ev:
        return
    run._show_event = ev                                              # keep a ref

    def wait():
        while kernel32.WaitForSingleObject(ev, 0xFFFFFFFF) == 0:
            try:
                window.show()
                window.restore()
                window.on_top = True                                  # pop above other windows, then behave normally
                window.on_top = False
            except Exception:  # noqa: BLE001
                log.exception("couldn't show the window")

    threading.Thread(target=wait, name="show-window", daemon=True).start()


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
    app._main_window = window
    # The companion: a small frameless always-on-top window with the same avatar, shown while computer tasks are on.
    g = dict(app.cfg.settings.overlay_geom or {})
    from .desktop_overlay import position_on_screen

    if not position_on_screen(g.get("x"), g.get("y")):           # first run, or that monitor was unplugged
        g = {}
    size = {"compact": (260, 352), "expanded": (380, 560), "minimized": (96, 96)}.get(app.cfg.settings.overlay_mode,
                                                                                      (260, 352))
    overlay = webview.create_window(
        "Monkey companion", url=str(index), js_api=OverlayApi(app), width=size[0], height=size[1],
        x=g.get("x"), y=g.get("y"), frameless=True, on_top=True, transparent=True, easy_drag=False, focus=False,
        hidden=not (app.cfg.settings.computer_access and app.cfg.settings.overlay_enabled), resizable=False,
        min_size=(80, 80), shadow=False,
        background_color="#000000",
    )
    app._overlay_window = overlay
    app.ui.windows.append(overlay)

    def on_closing():
        # Closing the window hides Monkey to the tray; he keeps listening. Say so the first few times.
        window.hide()
        icon = getattr(app, "_tray_icon", None)
        shown = getattr(app, "_hide_tips", 0)
        if icon is not None and shown < 3:
            app._hide_tips = shown + 1
            try:
                icon.notify("Monkey is still listening. To open him again, click the monkey icon near the clock "
                            "or open Monkey from the Start menu. To quit, right-click the icon → Quit.", "Monkey")
            except Exception:  # noqa: BLE001
                pass
        return False

    window.events.closing += on_closing
    _listen_for_show(window)

    def after_start():
        try:
            log.info("UI %s via %s (engine: %s)", index, getattr(window, "real_url", "?"),
                     getattr(getattr(window, "gui", None), "__name__", "?"))
        except Exception:  # noqa: BLE001
            pass
        app.start_audio()
        _tray(app, window)
        try:
            from . import desktop_overlay

            desktop_overlay.install(overlay, "Monkey companion")       # click-through, no focus, hidden from capture
        except Exception:  # noqa: BLE001
            log.warning("companion window extras unavailable", exc_info=True)
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


def run_routine(name: str) -> int:
    """`Monkey.exe --routine morning` (Task Scheduler): build + cache today's brief, then exit.

    No UI, no audio, no speech, no notifications. Safe to run twice (the routine is idempotent) and safe while the
    app is open (both share monkey.db; the per-day key prevents duplicates)."""
    if name != "morning":
        print(f"unknown routine {name!r}")
        return 2
    app = MonkeyApp(headless=True)
    if not app.cfg.settings.brief_enabled:
        return 0
    try:
        b = app.morning.run(datetime.now().astimezone(), "scheduled")
        log.info("routine morning: %s", b["kind"] if b else "nothing due")
        return 0
    except Exception:  # noqa: BLE001
        log.exception("routine morning failed")
        return 1


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
        from .audio.vad import load_vad

        vad = load_vad(None, resource_path("wakeword"))
        if vad is None:
            problems.append("voice activity model (Silero VAD) not bundled or not loadable")
        elif vad.is_speech(np.zeros(1280, dtype=np.int16)):
            problems.append("voice activity model reports speech in silence")
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

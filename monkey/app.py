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

from . import __version__, keys
from .brain.agent import Agent
from .brain.approval import ApprovalGate
from .brain.costs import HAIKU, Ledger, Usage
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

log = logging.getLogger("monkey")


# ---------------------------------------------------------------------------- UI bus
class UIBus:
    """Batches events to the web UI (~30 per second), coalescing mouth levels."""

    def __init__(self):
        self.window = None
        self._q: queue.Queue[tuple[str, dict]] = queue.Queue()
        self._level: float | None = None
        threading.Thread(target=self._loop, name="ui-bus", daemon=True).start()

    def emit(self, name: str, payload: dict | None = None) -> None:
        self._q.put((name, payload or {}))

    def level(self, v: float) -> None:
        self._level = v

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
            weather=NWSWeather(lambda: (self.cfg.settings.latitude, self.cfg.settings.longitude)),
            record_usage=self._record_usage, open_url=self._open_url,
            assignments=self.board, health=self.garmin,
        )
        self.router = Router(
            classify=self._classify,
            budget_usd=lambda: self.cfg.settings.monthly_budget_usd,
            spent_usd=self.ledger.month_to_date,
            forced_model=lambda: self.cfg.settings.force_model,
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
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent")
        self._voice_candidates: list[bytes] = []

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

        if self.client is None or getattr(self.client, "api_key", None) != key:
            self.client = anthropic.Anthropic(api_key=key, max_retries=2)
            self.agent.client = self.client
            self.services.anthropic_client = self.client
        return self.client

    def start_audio(self) -> None:
        from .audio.listener import Listener, load_wakeword
        from .audio.speaker import Speaker
        from .audio.stt import DeepgramSTT, WhisperSTT
        from .audio.tts import FishTTS, SystemTTS

        s = self.cfg.settings
        self.speaker = Speaker(
            [FishTTS(lambda: keys.get("fish"), lambda: self.cfg.settings.fish_voice_id,
                     lambda: self.cfg.settings.fish_model), SystemTTS()],
            on_level=self.ui.level, on_state=lambda _: self._publish_state(),
        )
        try:
            self.speaker.start()
        except Exception as exc:  # noqa: BLE001
            self._emit("error", {"message": f"No speaker/headphones found: {exc}"})
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
        self.ui.emit(name, payload)

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
        diff, needs_web, why, usage = classify_with_haiku(self.client, text)
        self._record_usage(HAIKU, "low", "router", usage)
        return diff, needs_web, why

    def _record_usage(self, model: str, effort: str, purpose: str, usage) -> None:
        self.ledger.record(model, effort, purpose, Usage.from_response(usage))

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
        if name not in keys.KNOWN_KEYS:
            return False
        keys.set(name, value.strip())
        a = self._app
        if name == "anthropic":
            a._ensure_client()
            a.cfg.update(first_run_complete=True)
        if name == "youtube":
            a.services.video_search = a._videos
        return True

    def save_settings(self, changes: dict):
        allowed = {k: v for k, v in (changes or {}).items() if k != "extra"}
        self._app.cfg.update(**allowed)
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

    def new_conversation(self):
        self._app.agent.new_session()

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
            guide = learn_style(a.client, [a.gmail, a.outlook], a.memory, record_usage=a._record_usage)
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
            return {"ok": False, "error": str(exc)}

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

    def test_voice(self):
        self._app._say("Yo, it's Monkey. How I'm sounding?")

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


def run() -> None:
    import webview

    app = MonkeyApp()
    api = Api(app)
    index = resource_path("ui", "dist", "index.html")
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
        app.start_audio()
        _tray(app, window)

    webview.start(after_start, private_mode=False, storage_path=str(app.cfg.data_dir / "webview"))


def selftest() -> int:
    """Used by CI on the built .exe: load everything that doesn't need a mic or a window."""
    import tempfile

    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        app = MonkeyApp(data_dir=Path(tmp), headless=True)
        if not resource_path("ui", "dist", "index.html").exists():
            problems.append("UI not bundled")
        if "Monkey" not in app.agent.system:
            problems.append("persona missing")
        r = app.router.route("draft an email to my professor")
        if r.model != "claude-opus-5-5":
            problems.append(f"router wrong: {r}")
        if "profile.md" not in app.memory.files():
            problems.append("memory not seeded")
        from .audio.kws import find_model

        if find_model(resource_path("wakeword")) is None:
            problems.append("Hey Monkey keyword model not bundled")
        for mod in ("webview", "sounddevice", "openwakeword", "faster_whisper", "keyboard", "pystray",
                    "googleapiclient", "google_auth_oauthlib", "garminconnect", "sherpa_onnx", "sentencepiece"):
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

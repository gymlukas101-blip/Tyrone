"""Playtest backend: the real Monkey app (headless) behind a small HTTP bridge, so testers can drive the real UI in a
browser on Linux with no Windows, microphone, Claude key or Google account.

What is real: every Python code path behind the UI (settings, keys, Google sign-in flow logic, calendars and Canvas
feed parsing, memory import, PC transfer, morning brief, health check, approval gate, agent loop and tools).
What is stood in:
  - Claude: a scripted brain that calls the same tools Claude would (calendar, email, assignments, drafts, memory...)
    and answers in plain words. It is not as smart as Claude; testers judge the app, not the AI's wit.
  - Google: sign-in "completes" a few seconds after the browser link opens; Gmail/Calendar return sample data.
  - Calendar links and the Canvas feed under *.playtest.edu return sample ICS files (anything else is fetched for real).
  - Native file pickers: the tester picks from a list of files on the "PC" (driver /pick).
  - Microphone/speakers: a silent speaker and an idle listener (testers type instead of talking).

Run:  python -m tools.playtest.backend --port 8801 --data /tmp/pt/1 --profile fresh|setup
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace as NS
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "ui" / "dist"
FIX = Path(__file__).resolve().parent / "fixtures"
CLAUDE_KEY_SHAPE = re.compile(r"^sk-ant-[A-Za-z0-9_-]{20,}$")


# ----------------------------------------------------------------------------------------------- sample data
def _now():
    return datetime.now().astimezone()


def classes_ics() -> bytes:
    """A realistic student calendar: weekly classes (RRULE), one exam, one club meeting."""
    tz = "America/Chicago"
    monday = (_now() - timedelta(days=_now().weekday())).date()
    rows = [("MATH 222 Lecture", "MO,WE,FR", "095500", "104500", "Van Vleck B102"),
            ("COMP SCI 300 Lecture", "TU,TH", "110000", "121500", "Morgridge 1524"),
            ("PSYCH 202 Lecture", "TU,TH", "143000", "154500", "Social Sciences 6210"),
            ("COMP SCI 300 Lab", "WE", "133000", "152500", "CS 1350")]
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//playtest//EN"]
    for i, (title, days, s, e, loc) in enumerate(rows):
        out += ["BEGIN:VEVENT", f"UID:cls{i}@playtest", f"SUMMARY:{title}", f"LOCATION:{loc}",
                f"DTSTART;TZID={tz}:{monday:%Y%m%d}T{s}", f"DTEND;TZID={tz}:{monday:%Y%m%d}T{e}",
                f"RRULE:FREQ=WEEKLY;BYDAY={days};COUNT=40", "END:VEVENT"]
    exam = monday + timedelta(days=9)
    out += ["BEGIN:VEVENT", "UID:exam@playtest", "SUMMARY:MATH 222 Midterm 2", f"DTSTART;TZID={tz}:{exam:%Y%m%d}T190000",
            f"DTEND;TZID={tz}:{exam:%Y%m%d}T203000", "LOCATION:Ingraham 19", "END:VEVENT"]
    club = monday + timedelta(days=3)
    out += ["BEGIN:VEVENT", "UID:club@playtest", "SUMMARY:Climbing club", f"DTSTART;TZID={tz}:{club:%Y%m%d}T180000",
            f"DTEND;TZID={tz}:{club:%Y%m%d}T200000", "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(out).encode()


def canvas_ics() -> bytes:
    """Canvas-style calendar feed: assignment due dates with [COURSE] suffixes."""
    items = [(1, "Problem Set 7", "MATH_222_001_F26"), (2, "Project 3: Hash Tables", "COMP_SCI_300_002_F26"),
             (4, "Reading Response 9", "PSYCH_202_001_F26"), (6, "Quiz 8", "MATH_222_001_F26"),
             (0, "Lab 10 Checkoff", "COMP_SCI_300_002_F26"), (-1, "Reading Response 8", "PSYCH_202_001_F26")]
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Instructure//Canvas//EN"]
    for n, (days, title, course) in enumerate(items):
        due = (datetime.now(timezone.utc) + timedelta(days=days)).replace(hour=5, minute=59, second=0, microsecond=0)
        out += ["BEGIN:VEVENT", f"UID:event-assignment-{4000 + n}", f"SUMMARY:{title} [{course}]",
                f"DTSTART:{due:%Y%m%dT%H%M%SZ}", f"DTEND:{due:%Y%m%dT%H%M%SZ}",
                f"URL:https://canvas.playtest.edu/courses/1/assignments/{4000 + n}", "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(out).encode()


def sample_emails():
    from monkey.integrations.base import Email

    n = _now()
    rows = [("Prof. Dana Whitfield", "whitfield@math.playtest.edu", "MATH 222: Midterm 2 room change",
             "Midterm 2 is now in Ingraham 19. Bring a calculator and one page of notes.", 2, True),
            ("Canvas Notifications", "notifications@instructure.com", "Project 3: Hash Tables due in 2 days",
             "Reminder: Project 3 is due Thursday at 11:59pm.", 5, True),
            ("Sam (roommate)", "sam.k@playtest.edu", "grocery run tonight?",
             "going to trader joes at 7 if you want anything lmk", 8, True),
            ("UW Bursar", "bursar@playtest.edu", "Your tuition statement is ready",
             "Your spring statement is available in Student Center.", 26, False),
            ("TA Priya Raman", "praman@cs.playtest.edu", "Lab 10 checkoff slots",
             "Sign up for a checkoff slot by Wednesday. Slots fill up fast.", 30, False)]
    return [Email(id=f"m{i}", account="gmail", sender=s, sender_email=e, to=["jordan@playtest.edu"], subject=sub,
                  snippet=snip, received=n - timedelta(hours=h), unread=u, body=snip + "\n\nThanks,\n" + s.split()[-1])
            for i, (s, e, sub, snip, h, u) in enumerate(rows)]


def sample_google_events(start, end):
    from monkey.integrations.base import Event

    n = _now().replace(minute=0, second=0, microsecond=0)
    rows = [("Office hours: MATH 222", 1, 26, "Van Vleck 501"), ("Dentist", 2, 39, ""), ("Study group (CS 300)", 1, 50, "College Library")]
    evs = [Event(id=f"g{i}", source="google", title=t, start=n + timedelta(hours=h), end=n + timedelta(hours=h + d),
                 location=loc) for i, (t, d, h, loc) in enumerate(rows)]
    return [e for e in evs if start <= e.start <= end]


# ----------------------------------------------------------------------------------------------- scripted brain
def _tool_names(params):
    return {t.get("name") for t in params.get("tools") or [] if isinstance(t, dict)}


def _last_user(params):
    for m in reversed(params.get("messages") or []):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c, None
        texts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        results = [b for b in c if isinstance(b, dict) and b.get("type") == "tool_result"]
        if results:
            return None, results
        if texts:
            return " ".join(texts), None
    return "", None


def _strip_context(text: str) -> str:
    """The app prepends memory context to the user's message; the brain only reacts to what was typed."""
    if "</context>" in text:
        text = text.rsplit("</context>", 1)[1]
    text = re.sub(r"^\s*\(You already said .*?\)\n", "", text, flags=re.S)
    return text.strip()


class ScriptedBrain:
    """Answers like Claude would at the level of 'which tool, then summarize' (no real language understanding)."""

    def __init__(self):
        self.last_tool = None

    def plan(self, text: str, tools: set[str]):
        t = text.lower()
        want = lambda name: name in tools  # noqa: E731
        if re.search(r"\b(write|draft|email|message)\b.*\b(prof|professor|ta|whitfield|instructor)", t) and want("draft_email"):
            return "draft_email", {"account": "gmail", "to": ["whitfield@math.playtest.edu"], "cc": [],
                                   "subject": "Question about Problem Set 7",
                                   "body": "Hi Professor Whitfield,\n\nI had a question about problem 4 on Problem Set 7. "
                                           "Could I come to office hours tomorrow to go over it?\n\nThanks,\nJordan",
                                   "reply_to_id": ""}
        if re.search(r"\b(due|assignment|homework|hw|canvas|deadline)", t) and want("get_assignments"):
            return "get_assignments", {"include_done": False}
        if re.search(r"\b(email|inbox|mail|unread)", t) and want("get_emails"):
            return "get_emails", {"account": "all", "unread_only": "unread" in t, "max_results": 10, "query": ""}
        if re.search(r"\b(calendar|schedule|class|classes|today|tomorrow|week|free)\b", t) and want("get_calendar"):
            return "get_calendar", {"days_ahead": 7 if "week" in t else 1}
        if re.search(r"\b(weather|rain|cold|jacket|umbrella)", t) and want("get_weather"):
            return "get_weather", {}
        if re.search(r"\b(sleep|slept|heart|health|garmin)", t) and want("get_health"):
            return "get_health", {"day": "today"}
        if re.search(r"\b(picture|image|draw|generate)", t) and want("generate_image"):
            return "generate_image", {"prompt": text[:120], "count": 1}
        if re.search(r"\bopen\b", t) and want("open_website"):
            target = re.sub(r".*\bopen\s+", "", t).strip(" ?.!") or "canvas"
            return "open_website", {"target": target}
        if re.search(r"\b(know about me|remember about me|what do you know)", t) and want("search_memory"):
            return "search_memory", {"query": "about the user", "scope": "all"}
        m = re.search(r"\bremember (that )?(.+)", text, re.I)
        if m and want("remember"):
            return "remember", {"fact": m.group(2).strip(" ."), "file": "profile.md", "evidence": text.strip()}
        return None, None

    def answer_text(self, text: str) -> str:
        t = text.lower()
        if re.search(r"\b(hi|hey|yo|hello|sup)\b", t):
            return "Yo! What's up? I can check your classes, what's due, your email, or help you write to a professor."
        if "thank" in t:
            return "Anytime."
        if "who are you" in t or "what can you do" in t:
            return ("I'm Monkey. I can check your schedule and Canvas due dates, read and draft emails, remember stuff "
                    "about you, and do your morning brief. Just ask like you'd ask a friend.")
        return "Got it. (Playtest brain: I only understand schedule, due dates, email, weather, drafts and memory questions.)"

    def summarize(self, tool: str, content: str) -> str:
        try:
            data = json.loads(content)
        except (TypeError, ValueError):
            data = content
        if isinstance(data, str):
            return data if len(data) < 400 else data[:400] + "…"
        if tool == "get_assignments":
            todo = data.get("todo", [])
            if not todo:
                return "Nothing due right now. Nice."
            top = todo[0]
            return (f"You've got {len(todo)} things coming up. Most urgent: {top['title']} for {top['course']} "
                    f"({str(top.get('reason') or '').strip() or 'due soon'}). I put the full list on screen.")
        if tool == "get_calendar":
            if not data:
                return "Your calendar's clear."
            first = data[0]
            return f"You've got {len(data)} things. First up: {first.get('title')} at {str(first.get('start'))[11:16]}."
        if tool == "get_emails":
            n = len(data)
            return f"You've got {n} recent emails. The top one is from {data[0].get('sender')}: \"{data[0].get('subject')}\"." if n else "Inbox is empty."
        if tool == "get_weather":
            return f"Weather: {data.get('summary') or data}"
        if tool == "search_memory":
            hits = data.get("facts") or data.get("hits") or []
            return f"Here's what I know: {'; '.join(h.get('text', '') for h in hits[:5])}" if hits else "I don't know much about you yet."
        return "Done."

    def respond(self, params):
        text, results = _last_user(params)
        if results:
            r = results[-1]
            content = r.get("content")
            if isinstance(content, list):
                content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            return [NS(type="text", text=self.summarize(self.last_tool, content or ""))], "end_turn"
        text = _strip_context(text or "")
        tool, args = self.plan(text, _tool_names(params))
        if tool:
            self.last_tool = tool
            lead = {"draft_email": "On it, drafting that now.", "get_assignments": "Let me check Canvas."}.get(tool, "")
            blocks = ([NS(type="text", text=lead)] if lead else []) + \
                     [NS(type="tool_use", name=tool, input=args, id="toolu_" + uuid.uuid4().hex[:10])]
            return blocks, "tool_use"
        return [NS(type="text", text=self.answer_text(text))], "end_turn"


class _Stream:
    def __init__(self, content, stop):
        self.content, self.stop = content, stop

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for b in self.content:
            if b.type == "text":
                for word in re.findall(r"\S+\s*", b.text):
                    time.sleep(0.03)
                    yield NS(type="text", text=word)

    def get_final_message(self):
        return NS(content=self.content, stop_reason=self.stop, model="claude-sonnet-5-5",
                  usage=NS(input_tokens=1200, output_tokens=80, cache_read_input_tokens=900,
                           cache_creation_input_tokens=0, server_tool_use=None))


class FakeClaude:
    def __init__(self, key: str):
        import anthropic
        import httpx

        self.key, self.brain = key, ScriptedBrain()
        self.valid = bool(CLAUDE_KEY_SHAPE.match(key or ""))
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        self._auth_error = lambda: anthropic.AuthenticationError(
            "invalid x-api-key", response=httpx.Response(401, request=req),
            body={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
        self.beta = NS(messages=NS(stream=self._stream))
        self.messages = NS(count_tokens=self._count, parse=self._parse, create=self._parse)
        self.models = NS(list=self._models)

    def _check(self):
        if not self.valid:
            raise self._auth_error()

    def _count(self, **kw):
        self._check()
        return NS(input_tokens=5)

    def _models(self, **kw):
        self._check()
        return NS(data=[NS(id="claude-sonnet-5-5")])

    def _parse(self, **kw):
        self._check()
        raise RuntimeError("playtest: no classifier/ranker (rules are used instead)")

    def _stream(self, **params):
        self._check()
        content, stop = self.brain.respond(params)
        return _Stream(content, stop)


# ----------------------------------------------------------------------------------------------- the app
class Bridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.events: list = []
        self.dialog: dict | None = None
        self.dialog_answer: list | None = None
        self.dialog_cv = threading.Condition()
        self.opened: list[str] = []

    def push(self, batch):
        with self.lock:
            self.events.extend(batch)

    def take(self):
        with self.lock:
            out, self.events = self.events, []
        return out


class FakeWindow:
    def __init__(self, bridge: Bridge, files: list[str]):
        self.b, self.files = bridge, files

    def evaluate_js(self, js: str):
        m = re.search(r"__monkeyEvents\((.*)\)\s*$", js, re.S)
        if m:
            self.b.push(json.loads(m.group(1)))

    def create_file_dialog(self, dialog_type=None, allow_multiple=False, file_types=(), **kw):
        """Blocks like a real picker until the tester picks (driver /pick) or cancels, max 3 minutes."""
        with self.b.dialog_cv:
            self.b.dialog = {"types": list(file_types or ()), "multiple": bool(allow_multiple), "files": self.files}
            self.b.dialog_answer = None
            self.b.dialog_cv.wait_for(lambda: self.b.dialog_answer is not None, timeout=180)
            ans, self.b.dialog, self.b.dialog_answer = self.b.dialog_answer, None, None
        return ans or None

    def __getattr__(self, name):              # show/restore/minimize/... are no-ops here
        return lambda *a, **k: None


def build_app(data: Path, profile: str, bridge: Bridge):
    from monkey import keys
    from monkey import app as app_mod
    from monkey.integrations.base import DraftResult

    data.mkdir(parents=True, exist_ok=True)
    keys.use_store(data / "secrets.dat")
    files_dir = data.parent / "pc-files"
    _make_pc_files(files_dir)
    a = app_mod.MonkeyApp(data_dir=data / "Monkey", headless=True)
    a._pt_bridge = bridge
    a.ui.window = FakeWindow(bridge, sorted(str(p) for p in files_dir.rglob("*") if p.is_file()))

    # Claude
    def ensure_client():
        k = keys.get("anthropic")
        if not k:
            return None
        if getattr(a, "_pt_client", None) is None or a._pt_client.key != k:
            a._pt_client = FakeClaude(k)
        a.client = a._pt_client
        return a.client
    a._ensure_client = ensure_client
    if a.agent is not None:
        a.agent.client = ensure_client()
    orig_ask = a.ask

    def ask(*args, **kw):
        a.agent.client = ensure_client()
        return orig_ask(*args, **kw)
    a.ask = ask

    # Speaker/listener stand-ins (no audio here)
    spoken = []
    a.speaker = NS(engines=[NS(available=lambda: True, enabled=lambda: True)], speaking=False,
                   say=lambda s, engine=None: spoken.append(s), stop=lambda: None)
    class _Listener:                          # idle microphone: testers type instead of talking
        muted, vad, mode = False, object(), "wake"

        def enter_conversation(self, *x, **k):
            self.mode = "conversation"

        def end_conversation(self, *x, **k):
            self.mode = "wake"

        def __getattr__(self, name):
            return lambda *x, **k: None
    a.listener = _Listener()
    a.wakeword_label = "Hey Monkey (keyword spotter)"
    a.offline_voice = NS(available=lambda: False, enabled=lambda: True)

    # Google
    def fake_sign_in(on_url=None, timeout_s=300):
        url = ("https://accounts.google.com/o/oauth2/auth?client_id=playtest&redirect_uri=http%3A%2F%2Flocalhost%3A1%2F"
               "&state=playtest")
        a.google._auth_url = url
        if on_url:
            on_url(url)
        bridge.opened.append(url)
        for _ in range(40):                   # the tester "finishes in the browser" after ~4 s
            time.sleep(0.1)
            if a.google._cancelled:
                from monkey.integrations.google import SignInCancelled
                raise SignInCancelled("Sign-in cancelled.")
        keys.set("google_token", json.dumps({"token": "playtest", "refresh_token": "playtest"}))
    a.google._cancelled = False

    def cancel():
        a.google._cancelled = True
        return True
    a.google.sign_in, a.google.cancel = fake_sign_in, cancel
    signed = lambda: bool(keys.get("google_token"))  # noqa: E731
    a.gmail.available = signed
    a.gmail.list_recent = lambda max_results=25, unread_only=False, query="": \
        [e for e in sample_emails() if (e.unread or not unread_only)][:max_results]
    a.gmail.get = lambda i: next(e for e in sample_emails() if e.id == i)
    a.gmail.list_sent = lambda max_results=100: []
    a.gmail.create_draft = lambda to, cc, subject, body, reply_to_id="": DraftResult("pt-" + uuid.uuid4().hex[:6], "")
    a.gmail.send_draft = lambda *x, **k: bridge.opened.append("SENT EMAIL (playtest: not really sent)")
    a.gmail.open_draft = lambda *x, **k: None
    a.gcal.available = signed
    a.gcal.list_events = sample_google_events
    a.google.service = lambda *x: NS(users=lambda: NS(getProfile=lambda **k: NS(execute=lambda: {"messagesTotal": 1834})))

    # Calendar link + Canvas feed: *.playtest.edu serve the sample ICS files; anything else is fetched for real
    fixtures = {"canvas": canvas_ics(), "calendar": classes_ics()}
    orig_ics_fetch, orig_canvas_fetch = a.ics_calendar._fetch, a.canvas._fetch
    a.ics_calendar._fetch = lambda url: fixtures["calendar"] if "playtest.edu" in url else orig_ics_fetch(url)
    a.canvas._fetch = lambda: fixtures["canvas"] if "playtest.edu" in (a.cfg.settings.canvas_ics_url or "") else orig_canvas_fetch()

    # Weather, links, Windows-only bits
    a.services.weather = lambda: {"summary": "38°F and cloudy, rain after 3pm", "temp_f": 38, "high_f": 44, "low_f": 31}
    a._open_url = lambda url: bridge.opened.append(url)
    a.services.open_url = a._open_url
    from monkey.routines import scheduler
    scheduler.register = lambda xml: setattr(a, "_pt_task", True)
    scheduler.unregister = lambda: setattr(a, "_pt_task", False)
    scheduler.is_registered = lambda: bool(getattr(a, "_pt_task", False))
    a.outlook.available = lambda: False

    if profile == "setup":
        keys.set("anthropic", "sk-ant-api03-PLAYTEST-" + "x" * 30)
        keys.set("fish", "playtest-fish-key")
        keys.set("google_client", (FIX / "client_secret_playtest.json").read_text())
        keys.set("google_token", json.dumps({"token": "playtest", "refresh_token": "playtest"}))
        keys.set("calendar_ics", "https://calendar.playtest.edu/jordan/classes.ics")
        a.cfg.update(first_run_complete=True, user_name="Jordan",
                     canvas_ics_url="https://canvas.playtest.edu/feeds/calendars/user_playtest.ics")
        ensure_client()
    return a, spoken


def _make_pc_files(d: Path) -> None:
    """Files on the tester's 'PC' they can pick in file dialogs."""
    (d / "Downloads").mkdir(parents=True, exist_ok=True)
    (d / "Documents" / "Monkey pack").mkdir(parents=True, exist_ok=True)
    (d / "Downloads" / "client_secret_887-playtest.apps.googleusercontent.com.json").write_text(
        (FIX / "client_secret_playtest.json").read_text())
    (d / "Downloads" / "client_secret_web_WRONG_TYPE.json").write_text(json.dumps({"web": {"client_id": "w", "client_secret": "s"}}))
    for p in (FIX / "pack").glob("*.md"):
        (d / "Documents" / "Monkey pack" / p.name).write_text(p.read_text())
    (d / "Downloads" / "syllabus_MATH222.pdf").write_bytes(b"%PDF-1.4 playtest")


def verify(a) -> dict:
    """Ground truth for task success, read from the app itself (testers never see this)."""
    from monkey import keys
    root = Path(a.memory.memory_root)
    imported = sum((root / n).read_text(encoding="utf-8").count("src=import")
                   for n in ("profile.md", "classes.md", "preferences.md", "projects.md") if (root / n).exists())
    text = " ".join((root / n).read_text(encoding="utf-8") for n in ("profile.md", "classes.md")
                    if (root / n).exists())
    s = a.cfg.settings
    return {
        "claude_key_saved": bool(keys.get("anthropic")),
        "claude_key_valid": bool(keys.get("anthropic")) and bool(CLAUDE_KEY_SHAPE.match(keys.get("anthropic") or "")),
        "google_client_saved": bool(keys.get("google_client")),
        "google_signed_in": bool(keys.get("google_token")),
        "calendar_link_saved": bool(keys.get("calendar_ics")),
        "canvas_feed_saved": bool(s.canvas_ics_url),
        "brief_schedule_confirmed": bool((s.brief_schedule or {}).get("by_day")),
        "brief_schedule": (s.brief_schedule or {}).get("by_day"),
        "brief_task_enabled": bool(getattr(a, "_pt_task", False)),
        "memory_pack_imported": "Sellery" in text or "Van Vleck" in text,
        "imported_facts": imported,
        "voice_volume": s.voice_volume, "voice_match_loudness": s.voice_match_loudness,
        "offline_voice_mode": s.offline_voice, "user_name": s.user_name,
        "drafts_pending": len(getattr(a.approval, "_drafts", {}) or {}),
        "emails_sent": [u for u in a._pt_bridge.opened if u.startswith("SENT EMAIL")],
        "links_opened": [u for u in a._pt_bridge.opened if u.startswith("http")][-5:],
        "messages_in_history": (a.history.stats()["messages"] if getattr(a, "history", None) else None),
    }


# ----------------------------------------------------------------------------------------------- HTTP
SHIM = """<script>
(() => {
  const call = async (name, args) => {
    const r = await fetch('/api/' + name, {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(args)});
    const j = await r.json();
    if (j.__error) throw new Error(j.__error);
    return j.result;
  };
  const api = new Proxy({}, {get: (_, name) => (name === 'then' || typeof name !== 'string') ? undefined : (...args) => call(name, args)});
  window.pywebview = {api};
  const poll = async () => {
    try { const r = await fetch('/events'); const ev = await r.json(); if (ev.length && window.__monkeyEvents) window.__monkeyEvents(ev); } catch (e) {}
    setTimeout(poll, 120);
  };
  window.addEventListener('DOMContentLoaded', () => { window.dispatchEvent(new Event('pywebviewready')); poll(); });
})();
</script>"""


def serve(port: int, data: Path, profile: str) -> None:
    bridge = Bridge()
    a, spoken = build_app(data, profile, bridge)
    from monkey.app import Api

    api = Api(a)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            if u.path == "/events":
                return self._send(200, json.dumps(bridge.take(), default=str).encode())
            if u.path == "/control/state":
                return self._send(200, json.dumps({"dialog": bridge.dialog, "opened": bridge.opened[-10:],
                                                   "spoken": spoken[-10:]}).encode())
            if u.path == "/control/verify":
                return self._send(200, json.dumps(verify(a), default=str).encode())
            path = DIST / (u.path.lstrip("/") or "index.html")
            if u.path in ("/", "/index.html"):
                html = (DIST / "index.html").read_text(encoding="utf-8").replace("<head>", "<head>" + SHIM, 1)
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if path.is_file() and DIST in path.resolve().parents:
                return self._send(200, path.read_bytes(), mimetypes.guess_type(str(path))[0] or "application/octet-stream")
            return self._send(404, b"{}")

        def do_POST(self):  # noqa: N802
            u = urlparse(self.path)
            body = self.rfile.read(int(self.headers.get("content-length") or 0)) or b"[]"
            if u.path == "/control/pick":
                q = json.loads(body or b"{}")
                with bridge.dialog_cv:
                    bridge.dialog_answer = q.get("files") or []
                    bridge.dialog_cv.notify_all()
                return self._send(200, b'{"ok": true}')
            name = u.path.rsplit("/", 1)[-1]
            fn = getattr(api, name, None)
            if fn is None or name.startswith("_"):
                return self._send(200, json.dumps({"__error": f"no api {name}"}).encode())
            try:
                res = fn(*json.loads(body))
                return self._send(200, json.dumps({"result": res}, default=str).encode())
            except Exception as exc:  # noqa: BLE001 - the UI sees what pywebview would raise
                return self._send(200, json.dumps({"__error": f"{type(exc).__name__}: {exc}"}).encode())

    print(f"playtest backend on http://127.0.0.1:{port}/ ({profile})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8801)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--profile", choices=("fresh", "setup"), default="fresh")
    args = ap.parse_args()
    serve(args.port, args.data, args.profile)

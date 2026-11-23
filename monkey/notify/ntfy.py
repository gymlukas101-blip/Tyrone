"""Reminders on the owner's phone through ntfy (https://ntfy.sh): free, no account.

The owner installs the ntfy app and subscribes to a topic. The topic name is the only thing that protects the
messages (anyone who knows it can read them and post to it), so Monkey makes a long random one and keeps it in the
encrypted secret store (`keys`, DPAPI on Windows), never in settings.json. A self-hosted server can also need an
access token, saved the same way.

Rules this module keeps:
- Every request has a 5-second timeout, and a failed one is retried once (network errors, 5xx, 429; never 4xx).
- Reminders go through one background worker, so the reminder tick and the UI never wait on the network.
- The topic, the token and the message text are never logged or put in a status message. Messages are published
  as JSON to the server's root URL, so the topic isn't even in the URL an exception might print.
- Failures only update a quiet status line in Settings.
"""
from __future__ import annotations

import ipaddress
import logging
import queue
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit

log = logging.getLogger("monkey.notify")

DEFAULT_SERVER = "https://ntfy.sh"
TOPIC_KEY = "ntfy_topic"
TOKEN_KEY = "ntfy_token"
TIMEOUT_S = 5.0
RETRY_AFTER_S = 1.0
TITLE = "Monkey reminder"
PRIVATE_BODY = "You have a reminder"
_TOPIC_RE = re.compile(r"[-_A-Za-z0-9]{1,64}")
MIN_TOPIC_LEN = 20                   # shorter topics are guessable


def new_topic() -> str:
    """'monkey-' + 32 random URL-safe characters (192 bits): unguessable, and valid for ntfy (max 64 chars)."""
    return "monkey-" + secrets.token_urlsafe(24)


def valid_topic(topic: str | None) -> bool:
    return bool(topic) and len(topic) >= MIN_TOPIC_LEN and bool(_TOPIC_RE.fullmatch(topic))


def _local_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    if host == "localhost" or host.endswith((".local", ".lan", ".home.arpa", ".internal")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def normalize_server(url: str | None) -> str:
    """'' -> https://ntfy.sh; 'ntfy.example.com' -> https://ntfy.example.com. Plain http only on this PC or the home
    network (an access token must not cross the internet unencrypted). Raises ValueError with a readable reason."""
    u = (url or "").strip()
    if not u:
        return DEFAULT_SERVER
    if "://" not in u:
        u = "https://" + u
    try:
        p = urlsplit(u)
        host = p.hostname
        _ = p.port                       # raises on a bad port
    except ValueError as exc:
        raise ValueError("That isn't a web address. Use something like https://ntfy.sh") from exc
    if p.scheme not in ("http", "https") or not host:
        raise ValueError("Use an https:// address, like https://ntfy.sh")
    if p.query or p.fragment or p.username or p.password:
        raise ValueError("Use just the server's address, like https://ntfy.example.com (no ?, # or user name)")
    if p.scheme == "http" and not _local_host(host):
        raise ValueError("Use https:// for a server on the internet (plain http is only allowed on your home network)")
    return u.rstrip("/")


@dataclass
class PhoneMessage:
    title: str
    body: str
    high: bool = False
    tags: list[str] = field(default_factory=lambda: ["alarm_clock"])


def reminder_message(text: str, due: str, *, high: bool, show_text: bool) -> PhoneMessage:
    """The phone notification for a to-do. show_text=False keeps the item off ntfy's server entirely."""
    body = f"{text}\n{due[:1].upper() + due[1:]}" if show_text else PRIVATE_BODY
    return PhoneMessage(TITLE, body, high=high)


def payload(topic: str, msg: PhoneMessage) -> dict:
    """ntfy's JSON publish format (https://docs.ntfy.sh/publish/#publish-as-json). Priority 4 = high, 3 = default."""
    return {"topic": topic, "title": msg.title, "message": msg.body, "priority": 4 if msg.high else 3,
            "tags": list(msg.tags)}


@dataclass
class SendResult:
    ok: bool
    detail: str = ""                    # safe to show and log: never the topic, token or text
    attempts: int = 0


class NtfySender:
    """One publish with a timeout and one retry. `post` is httpx.post (tests pass a fake)."""

    def __init__(self, post: Callable | None = None, sleep: Callable[[float], None] = time.sleep):
        if post is None:
            import httpx

            post = httpx.post
        self._post = post
        self._sleep = sleep

    def send(self, server: str, topic: str, msg: PhoneMessage, token: str | None = None) -> SendResult:
        if not valid_topic(topic):
            return SendResult(False, "no phone topic yet: set up your phone in Settings → Reminders")
        url = normalize_server(server) + "/"
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = payload(topic, msg)
        detail = ""
        for attempt in (1, 2):
            try:
                r = self._post(url, json=body, headers=headers, timeout=TIMEOUT_S)
                code = int(getattr(r, "status_code", 0))
                if 200 <= code < 300:
                    return SendResult(True, "sent", attempt)
                detail = _http_detail(code)
                if 400 <= code < 500 and code != 429:
                    return SendResult(False, detail, attempt)     # retrying won't fix a refusal
            except Exception as exc:  # noqa: BLE001 - network trouble of any kind: retry once, then report quietly
                detail = _error_detail(exc)
            if attempt == 1:
                self._sleep(RETRY_AFTER_S)
        return SendResult(False, detail, 2)


def _http_detail(code: int) -> str:
    if code in (401, 403):
        return f"the server refused it (HTTP {code}): check the access token, or whether this topic is reserved"
    if code == 429:
        return "the server says too many messages (HTTP 429)"
    if code == 413:
        return "the message was too long for the server (HTTP 413)"
    return f"the server answered HTTP {code}"


def _error_detail(exc: Exception) -> str:
    name = type(exc).__name__
    if "Timeout" in name:
        return "the server didn't answer within 5 seconds"
    if "Connect" in name:
        return "couldn't reach the server (no internet, or the address is wrong)"
    return f"couldn't send ({name})"


class PhoneNotifier:
    """Settings + secrets + a background worker around NtfySender.

    settings(): the live Settings object (todo_phone_notify, ntfy_server, todo_phone_show_text).
    secret(name) / save_secret(name, value): the encrypted key store (monkey.keys.get / keys.set)."""

    def __init__(self, settings: Callable, secret: Callable[[str], str | None],
                 save_secret: Callable[[str, str], None], sender: NtfySender | None = None,
                 clock: Callable[[], float] = time.time):
        self._settings = settings
        self._secret = secret
        self._save_secret = save_secret
        self._sender = sender
        self._clock = clock
        self._q: queue.Queue[PhoneMessage] = queue.Queue(maxsize=50)
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self.status: dict = {"state": "idle", "at": None, "detail": ""}

    @property
    def sender(self) -> NtfySender:
        if self._sender is None:
            self._sender = NtfySender()
        return self._sender

    # ---- setup
    def topic(self) -> str | None:
        t = self._secret(TOPIC_KEY)
        return t if valid_topic(t) else None

    def ensure_topic(self, renew: bool = False) -> str:
        """The phone topic, made (and saved encrypted) the first time. renew=True replaces it: old subscriptions stop
        getting reminders."""
        with self._lock:
            t = None if renew else self.topic()
            if t is None:
                t = new_topic()
                self._save_secret(TOPIC_KEY, t)
            return t

    def server(self) -> str:
        try:
            return normalize_server(getattr(self._settings(), "ntfy_server", "") or DEFAULT_SERVER)
        except ValueError:
            return DEFAULT_SERVER

    def enabled(self) -> bool:
        return bool(getattr(self._settings(), "todo_phone_notify", False)) and self.topic() is not None

    def describe(self) -> dict:
        """For Settings. Includes the topic so the owner can subscribe to it (never logged)."""
        t = self.topic()
        st = self._settings()
        return {"enabled": bool(getattr(st, "todo_phone_notify", False)), "configured": t is not None,
                "server": self.server(), "topic": t or "", "subscribe_url": f"{self.server()}/{t}" if t else "",
                "has_token": bool(self._secret(TOKEN_KEY)), "show_text": bool(getattr(st, "todo_phone_show_text", True)),
                "status": dict(self.status)}

    # ---- sending
    def send_now(self, msg: PhoneMessage) -> SendResult:
        """Blocking (up to ~11 s): for the Settings test button, which runs on pywebview's API thread."""
        t = self.topic()
        if t is None:
            res = SendResult(False, "no phone topic yet: click Set up my phone first")
        else:
            res = self.sender.send(self.server(), t, msg, self._secret(TOKEN_KEY) or None)
        self.status = {"state": "ok" if res.ok else "failed", "at": self._clock(), "detail": res.detail}
        if not res.ok:
            log.warning("phone notification not sent: %s", res.detail)
        return res

    def submit(self, msg: PhoneMessage) -> bool:
        """Queue a reminder for the background worker. False when the phone is off, not set up, or the queue is full."""
        if not self.enabled():
            return False
        try:
            self._q.put_nowait(msg)
        except queue.Full:
            log.warning("phone notification queue full; dropped one")
            return False
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="phone-notify", daemon=True)
                self._worker.start()
        return True

    def _run(self) -> None:
        while True:                         # one long-lived worker (a daemon thread: it ends with the app)
            msg = self._q.get()
            try:
                self.send_now(msg)
            except Exception:  # noqa: BLE001 - never let one bad message stop later ones
                log.warning("phone notification worker error", exc_info=False)
            finally:
                self._q.task_done()

    def wait_idle(self, timeout: float = 15.0) -> bool:
        """Tests: wait until every queued message was handled."""
        end = time.monotonic() + timeout
        while self._q.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.01)
        return not self._q.unfinished_tasks

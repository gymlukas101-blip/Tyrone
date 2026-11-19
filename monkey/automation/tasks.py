"""Durable computer tasks: the model, the state machine, and the local store.

A task is not a conversation turn. It lives in %APPDATA%\\Monkey\\automation.db, survives restarts, and only moves
between states along TRANSITIONS. On restart nothing is replayed: active tasks come back PAUSED and are reconciled
with what is actually on screen when the user resumes them.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit


class S(str, Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"            # waiting for the page/app (media playing, a load, a download): no model calls
    NEEDS_INPUT = "NEEDS_INPUT"    # waiting for the user: an approval, their own answer/attestation, a sign-in
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"            # an external dependency is down (site errors, browser gone) after bounded retries
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL = {S.COMPLETED, S.FAILED, S.CANCELLED}
_ACTIVE = {S.RUNNING, S.WAITING, S.NEEDS_INPUT, S.BLOCKED, S.VERIFYING}
TRANSITIONS: dict[S, set[S]] = {
    S.READY: {S.RUNNING, S.CANCELLED},
    S.RUNNING: {S.WAITING, S.NEEDS_INPUT, S.PAUSED, S.BLOCKED, S.VERIFYING, S.FAILED, S.CANCELLED},
    S.WAITING: {S.RUNNING, S.NEEDS_INPUT, S.PAUSED, S.BLOCKED, S.FAILED, S.CANCELLED},
    S.NEEDS_INPUT: {S.RUNNING, S.PAUSED, S.FAILED, S.CANCELLED},
    S.PAUSED: {S.RUNNING, S.CANCELLED},
    S.BLOCKED: {S.RUNNING, S.PAUSED, S.FAILED, S.CANCELLED},
    S.VERIFYING: {S.COMPLETED, S.RUNNING, S.NEEDS_INPUT, S.PAUSED, S.FAILED, S.CANCELLED},
    S.COMPLETED: set(), S.FAILED: set(), S.CANCELLED: set(),
}


class InvalidTransition(Exception):
    pass


@dataclass
class Budget:
    max_minutes: float = 90.0
    max_actions: int = 600
    max_model_calls: int = 40
    max_usd: float = 1.00
    max_retries_per_step: int = 3


@dataclass
class Usage:
    actions: int = 0
    model_calls: int = 0
    usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_s: float = 0.0          # accumulated RUNNING/WAITING time (not paused time)


@dataclass
class Task:
    objective: str
    mode: str = "managed_browser"   # managed_browser | control_window | observe_window
    skill: str = "course"           # course (deterministic, model fallback) | general (model-driven)
    start_url: str = ""
    allowed_domains: list = field(default_factory=list)
    window: dict = field(default_factory=dict)       # {"hwnd", "title", "process"} for window modes
    send_screenshots: bool = False                   # may screenshots go to Claude (only if the user ticked it)
    confirm_medium: bool = False                     # ask before medium-risk actions too
    id: str = field(default_factory=lambda: "t_" + uuid.uuid4().hex[:10])
    state: S = S.READY
    subgoal: str = ""
    checkpoints: list = field(default_factory=list)  # [{ts, step, url, note, evidence}]
    pending: dict | None = None                      # {"kind": approval|user_turn|sign_in|blocked, "message", ...}
    errors: list = field(default_factory=list)       # recoverable error history [{ts, kind, detail}]
    budget: Budget = field(default_factory=Budget)
    usage: Usage = field(default_factory=Usage)
    outcome: dict | None = None
    last_url: str = ""
    note: str = ""                                   # one human line: what Monkey is doing now
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)

    # ---- state machine -------------------------------------------------
    def transition(self, to: S, note: str = "") -> None:
        to = S(to)
        if to == self.state:
            if note:
                self.note = note
            return
        if to not in TRANSITIONS[self.state]:
            raise InvalidTransition(f"{self.state.value} → {to.value}")
        self.state = to
        if note:
            self.note = note
        self.updated = time.time()

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL

    def checkpoint(self, step: str, url: str = "", note: str = "", evidence: dict | None = None) -> None:
        self.checkpoints.append({"ts": round(time.time(), 1), "step": step, "url": safe_url(url),
                                 "note": note[:200], "evidence": evidence or {}})
        self.checkpoints = self.checkpoints[-200:]
        if url:
            self.last_url = url

    def error(self, kind: str, detail: str) -> None:
        self.errors.append({"ts": round(time.time(), 1), "kind": kind, "detail": detail[:200]})
        self.errors = self.errors[-50:]

    def public(self) -> dict:
        d = self.to_dict()
        d["state"] = self.state.value
        if d.get("pending"):
            d["pending"] = {k: v for k, v in d["pending"].items() if k != "token"}   # tokens go to the UI separately
        d["progress"] = self.progress()
        return d

    def progress(self) -> dict:
        done = [c for c in self.checkpoints if c["step"] == "module_complete"]
        return {"steps": len(self.checkpoints), "modules_done": len({c["evidence"].get("module") for c in done})}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        d = dict(d)
        d["state"] = S(d.get("state", "READY"))
        d["budget"] = Budget(**(d.get("budget") or {}))
        d["usage"] = Usage(**(d.get("usage") or {}))
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def safe_url(url: str) -> str:
    """Scheme + host + path only: query strings and fragments can carry tokens and personal ids."""
    if not url:
        return ""
    try:
        p = urlsplit(url)
    except ValueError:
        return ""
    return f"{p.scheme}://{p.netloc}{p.path}"[:200] if p.scheme else url[:60]


_SECRETISH = re.compile(r"(password|passcode|token|secret|ssn|social security|card number|cvv|cvc)", re.I)


def redact(text: str, limit: int = 80) -> str:
    text = " ".join(str(text or "").split())
    return "[redacted]" if _SECRETISH.search(text) else text[:limit]


class TaskStore:
    """SQLite: tasks (JSON) + an audit log of actions. The audit log keeps what was done, to which control (role and
    name), on which host, and the outcome: never typed text, page text, cookies or screenshots."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, created REAL, updated REAL, state TEXT, data TEXT);
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, ts REAL,
                    kind TEXT, risk TEXT, target TEXT, host TEXT, outcome TEXT);
                CREATE INDEX IF NOT EXISTS audit_task ON audit(task_id);
            """)

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def save(self, t: Task) -> None:
        t.updated = time.time()
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO tasks(id, created, updated, state, data) VALUES (?,?,?,?,?)",
                      (t.id, t.created, t.updated, t.state.value, json.dumps(t.to_dict(), default=str)))

    def load(self, task_id: str) -> Task | None:
        with self._conn() as c:
            r = c.execute("SELECT data FROM tasks WHERE id=?", (task_id,)).fetchone()
        return Task.from_dict(json.loads(r["data"])) if r else None

    def list(self, limit: int = 30) -> list[Task]:
        with self._conn() as c:
            rows = c.execute("SELECT data FROM tasks ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [Task.from_dict(json.loads(r["data"])) for r in rows]

    def audit(self, task_id: str, kind: str, risk: str = "", target: str = "", url: str = "", outcome: str = "") -> None:
        host = urlsplit(url).hostname or "" if url else ""
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO audit(task_id, ts, kind, risk, target, host, outcome) VALUES (?,?,?,?,?,?,?)",
                      (task_id, time.time(), kind, risk, redact(target), host, outcome[:80]))

    def audit_log(self, task_id: str) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT ts, kind, risk, target, host, outcome FROM audit "
                                               "WHERE task_id=? ORDER BY id", (task_id,))]

    def recover_after_restart(self) -> list[Task]:
        """Tasks that were active when Monkey stopped come back PAUSED: never resumed blindly."""
        out = []
        for t in self.list(200):
            if t.state in _ACTIVE:
                t.state = S.PAUSED
                t.pending = None
                t.note = "Monkey restarted. Press Resume and he'll look at the screen again before doing anything."
                t.error("interrupted", "Monkey stopped while this task was active")
                self.save(t)
                out.append(t)
        return out

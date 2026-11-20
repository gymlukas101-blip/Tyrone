"""Structured task trace: one event per meaningful thing, for the UI (live) and for evaluation (metrics).

Events never carry typed text, field values, screenshots or full URLs (only host + path). The JSONL file lives next
to automation.db in the user's data folder, which is never committed or uploaded.
"""
from __future__ import annotations

import json
import statistics
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Callable

from ..tasks import safe_url


class Ev(str, Enum):
    TASK_STARTED = "TASK_STARTED"
    PLAN_UPDATED = "PLAN_UPDATED"
    WINDOW_SELECTED = "WINDOW_SELECTED"
    BROWSER_NAVIGATED = "BROWSER_NAVIGATED"
    DRIVER_SWITCHED = "DRIVER_SWITCHED"
    CURSOR_MOVED = "CURSOR_MOVED"
    ELEMENT_HOVERED = "ELEMENT_HOVERED"
    INPUT_PRESSED = "INPUT_PRESSED"
    INPUT_RELEASED = "INPUT_RELEASED"
    ACTION_ACCEPTED = "ACTION_ACCEPTED"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    ACTION_VERIFIED = "ACTION_VERIFIED"
    ACTION_FAILED = "ACTION_FAILED"
    RECOVERY = "RECOVERY"
    WAIT_STARTED = "WAIT_STARTED"
    WAIT_FINISHED = "WAIT_FINISHED"
    CHECKPOINT = "CHECKPOINT"
    MODEL_CALL = "MODEL_CALL"
    USER_INPUT_NEEDED = "USER_INPUT_NEEDED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"


_SAFE_KEYS = {"op", "backend", "target", "role", "name", "stage", "error", "detail", "ms", "risk", "from", "to", "why",
              "kind", "timeout_s", "ok", "subgoal", "steps", "model", "input_tokens", "output_tokens", "usd", "x", "y",
              "space", "window", "process", "url", "message", "evidence", "recovered_by", "state", "count"}


def _clean(data: dict) -> dict:
    out = {}
    for k, v in data.items():
        if k not in _SAFE_KEYS:
            continue
        if k == "url" and isinstance(v, str):
            v = safe_url(v)
        elif isinstance(v, str):
            v = v[:160]
        out[k] = v
    return out


class Trace:
    def __init__(self, task_id: str, path: Path | None = None, emit: Callable[[str, dict], None] | None = None):
        self.task_id = task_id
        self.path = Path(path) if path else None
        self.emit = emit
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self.t0 = time.time()

    def __call__(self, ev: Ev, **data) -> dict:
        e = {"ts": round(time.time(), 3), "t": round(time.time() - self.t0, 3), "ev": ev.value, **_clean(data)}
        with self._lock:
            self.events.append(e)
            if len(self.events) > 5000:
                self.events = self.events[-4000:]
            if self.path is not None:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps({"task": self.task_id, **e}) + "\n")
                except OSError:
                    pass
        if self.emit is not None:
            try:
                self.emit("computer_event", {"task_id": self.task_id, **e})
            except Exception:  # noqa: BLE001 - the UI must never break the task
                pass
        return e

    # ---- metrics (what the benchmark and the quality report read) --------------------------------------------------
    def metrics(self) -> dict:
        ev = self.events
        acts = [e for e in ev if e["ev"] in ("ACTION_VERIFIED", "ACTION_EXECUTED", "ACTION_FAILED")
                and e.get("op") not in ("observe", "wait_for", "find_element", "list_windows", "get_element_state",
                                        "capture_screenshot", "verify")]
        lat = sorted(e["ms"] for e in acts if isinstance(e.get("ms"), (int, float)))
        p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))] if lat else 0  # noqa: E731
        calls = [e for e in ev if e["ev"] == "MODEL_CALL"]
        return {
            "actions": len(acts),
            "verified": sum(1 for e in acts if e["ev"] == "ACTION_VERIFIED"),
            "failed": sum(1 for e in acts if e["ev"] == "ACTION_FAILED"
                          and e.get("error") not in ("refused", "needs_approval", "needs_user", "duplicate")),
            "gate_refusals": sum(1 for e in acts if e.get("error") in ("refused", "needs_approval", "needs_user")),
            "recoveries": sum(1 for e in ev if e["ev"] == "RECOVERY" and e.get("ok")),
            "driver_switches": sum(1 for e in ev if e["ev"] == "DRIVER_SWITCHED"),
            "model_calls": len(calls),
            "input_tokens": sum(e.get("input_tokens", 0) for e in calls),
            "output_tokens": sum(e.get("output_tokens", 0) for e in calls),
            "usd": round(sum(e.get("usd", 0.0) for e in calls), 5),
            "median_ms": statistics.median(lat) if lat else 0,
            "p95_ms": p(0.95),
            "backends": sorted({e.get("backend") for e in acts if e.get("backend")}),
        }

"""Per-turn traces: where the time goes from your voice to his, and how each turn was routed.

One record per turn, with monotonic timestamps for each stage and a few labels (source, task, model, effort, rounds,
cost, outcome). No speech text, no audio: the owner can opt in to keeping the request text for routing evaluation
(`trace_text`), and even then it stays in %APPDATA%\\Monkey\\traces on this PC.

Stage marks (any subset; missing stages are simply absent):
  wake, speech_start, last_voiced, endpoint, stt_start, stt_end, route_start, route_end, context_start, context_end,
  llm_request, first_token, first_speakable, tts_submit, first_audio_packet, first_audio_played, last_audio_played,
  interrupt_request, playback_stopped, ack_spoken
A mark is recorded once per turn (the first time); later calls are ignored, so "first_*" really means first.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Spans reported in "Check everything" and the voice report: (label, from, to)
SPANS: list[tuple[str, str, str]] = [
    ("you stop → turn ends", "last_voiced", "endpoint"),
    ("speech → text", "stt_start", "stt_end"),
    ("routing", "route_start", "route_end"),
    ("memory + context", "context_start", "context_end"),
    ("request → first word", "llm_request", "first_token"),
    ("first word → first sentence", "first_token", "first_speakable"),
    ("sentence → first sound", "tts_submit", "first_audio_played"),
    ("you stop → he speaks", "last_voiced", "first_audio_played"),
    ("turn ends → he speaks", "endpoint", "first_audio_played"),
    ("typed → he speaks", "route_start", "first_audio_played"),
    ("interrupt → silence", "interrupt_request", "playback_stopped"),
]

_CORRECTION = re.compile(r"^\s*(no[,.! ]|nope|not that|that'?s (not|wrong)|i (meant|said)|wrong\b|actually[, ])",
                         re.I)


def percentile(values: list[float], p: float) -> float | None:
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


@dataclass
class Turn:
    id: str
    source: str
    started: float
    wall: float
    marks: dict[str, float] = field(default_factory=dict)
    meta: dict[str, object] = field(default_factory=dict)
    text: str = ""                    # only kept when the owner opted in
    done: bool = False

    def span_ms(self, a: str, b: str) -> float | None:
        if a in self.marks and b in self.marks and self.marks[b] >= self.marks[a]:
            return round((self.marks[b] - self.marks[a]) * 1000.0, 1)
        return None

    def record(self, keep_text: bool = False) -> dict:
        t0 = min(self.marks.values()) if self.marks else self.started
        out = {"id": self.id, "at": round(self.wall, 3), "source": self.source,
               "marks_ms": {k: round((v - t0) * 1000.0, 1) for k, v in sorted(self.marks.items(), key=lambda x: x[1])},
               "spans_ms": {label: ms for label, a, b in SPANS if (ms := self.span_ms(a, b)) is not None},
               **{k: v for k, v in self.meta.items()}}
        if keep_text and self.text:
            out["text"] = self.text
        return out


class TurnTracer:
    def __init__(self, folder: Path | None = None, keep_text: callable = lambda: False, ring: int = 300):
        self.folder = folder
        self.keep_text = keep_text
        self._lock = threading.Lock()
        self._current: Turn | None = None
        self._recent: deque[dict] = deque(maxlen=ring)
        self._last_text = ""
        self._last_text_at = 0.0
        self._load_recent()

    # ---- lifecycle ------------------------------------------------------------------------------------------
    def begin(self, source: str, at: float | None = None) -> Turn:
        """A new turn starts (wake word, conversation turn, push-to-talk, typed). Closes any unfinished one."""
        with self._lock:
            old = self._current
            self._current = Turn(id=uuid.uuid4().hex[:12], source=source, started=at or time.monotonic(),
                                 wall=time.time())
        if old is not None and not old.done:
            old.meta.setdefault("outcome", "superseded")
            self._finish(old)
        return self._current

    def current(self) -> Turn | None:
        return self._current

    def ensure(self, source: str) -> Turn:
        t = self._current
        if t is None or t.done:
            t = self.begin(source)
        return t

    def mark(self, name: str, at: float | None = None, turn: Turn | None = None) -> None:
        t = turn or self._current
        if t is None or t.done:
            return
        with self._lock:
            t.marks.setdefault(name, at if at is not None else time.monotonic())

    def note(self, **meta) -> None:
        t = self._current
        if t is None or t.done:
            return
        with self._lock:
            for k, v in meta.items():
                if k == "cost_usd":
                    t.meta[k] = round(float(t.meta.get(k, 0.0)) + float(v or 0.0), 6)
                elif k == "rounds":
                    t.meta[k] = int(t.meta.get(k, 0)) + int(v)
                else:
                    t.meta[k] = v

    def user_text(self, text: str) -> None:
        """Called with what the user asked. Used only for the correction signal (and kept only with opt-in)."""
        t = self._current
        now = time.monotonic()
        if t is None or t.done:
            return
        corrected = bool(self._last_text) and now - self._last_text_at < 60 and bool(_CORRECTION.match(text or ""))
        if corrected:
            self._flag_previous_correction()
        t.meta["words"] = len((text or "").split())
        if self.keep_text():
            t.text = text
        self._last_text, self._last_text_at = text, now

    def finish(self, outcome: str = "ok", turn: Turn | None = None) -> None:
        t = turn or self._current
        if t is None or t.done:
            return
        t.meta.setdefault("outcome", outcome)
        self._finish(t)

    def _finish(self, t: Turn) -> None:
        with self._lock:
            if t.done:
                return
            t.done = True
            rec = t.record(keep_text=self.keep_text())
            self._recent.append(rec)
        self._write(rec)

    def _flag_previous_correction(self) -> None:
        with self._lock:
            if self._recent:
                self._recent[-1]["corrected_next_turn"] = True
                self._append(self._recent[-1]["id"], {"corrected_next_turn": True})

    # ---- storage --------------------------------------------------------------------------------------------
    def _file(self) -> Path | None:
        if self.folder is None:
            return None
        return self.folder / f"turns-{time.strftime('%Y-%m')}.jsonl"

    def _write(self, rec: dict) -> None:
        f = self._file()
        if f is None:
            return
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            log.debug("couldn't write a turn trace", exc_info=True)

    def _append(self, turn_id: str, patch: dict) -> None:
        f = self._file()
        if f is None:
            return
        try:
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"patch": turn_id, **patch}) + "\n")
        except OSError:
            pass

    def _load_recent(self) -> None:
        for rec in load_traces(self.folder, limit=self._recent.maxlen or 300):
            self._recent.append(rec)

    # ---- reading --------------------------------------------------------------------------------------------
    def recent(self) -> list[dict]:
        with self._lock:
            return list(self._recent)

    def stats(self, source: str | None = None) -> list[dict]:
        return span_stats(self.recent(), source)


def load_traces(folder: Path | None, limit: int = 5000) -> list[dict]:
    """Every saved turn (newest last), with later patches (e.g. corrected_next_turn) applied."""
    if folder is None or not Path(folder).exists():
        return []
    recs: dict[str, dict] = {}
    for f in sorted(Path(folder).glob("turns-*.jsonl")):
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if "patch" in d:
                if d["patch"] in recs:
                    recs[d["patch"]].update({k: v for k, v in d.items() if k != "patch"})
            elif "id" in d:
                recs[d["id"]] = d
    return list(recs.values())[-limit:]


def span_stats(records: list[dict], source: str | None = None) -> list[dict]:
    rows = []
    for label, _a, _b in SPANS:
        vals = [r["spans_ms"][label] for r in records
                if label in r.get("spans_ms", {}) and (source is None or r.get("source") == source)]
        if vals:
            rows.append({"span": label, "n": len(vals), "p50": round(percentile(vals, 50), 0),
                         "p95": round(percentile(vals, 95), 0), "p99": round(percentile(vals, 99), 0)})
    return rows


def report(records: list[dict]) -> str:
    """Plain-text report (no speech text) for "Check everything" and `python -m tools.voice_report`."""
    if not records:
        return "No turns traced yet. Talk to Monkey a few times, then look again."
    lines = [f"{len(records)} turns traced"]
    by_src: dict[str, int] = {}
    for r in records:
        by_src[str(r.get("source"))] = by_src.get(str(r.get("source")), 0) + 1
    lines.append("by source: " + ", ".join(f"{k} {v}" for k, v in sorted(by_src.items())))
    lines.append("")
    lines.append(f"{'stage':32} {'n':>4} {'p50':>7} {'p95':>7} {'p99':>7}")
    for row in span_stats(records):
        lines.append(f"{row['span']:32} {row['n']:>4} {row['p50']:>6.0f}ms {row['p95']:>6.0f}ms {row['p99']:>6.0f}ms")
    outcomes: dict[str, int] = {}
    for r in records:
        outcomes[str(r.get("outcome", "?"))] = outcomes.get(str(r.get("outcome", "?")), 0) + 1
    lines.append("")
    lines.append("outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(outcomes.items())))
    tasks: dict[str, list[dict]] = {}
    for r in records:
        if r.get("task"):
            tasks.setdefault(str(r["task"]), []).append(r)
    if tasks:
        lines.append("")
        lines.append(f"{'task':16} {'n':>4} {'corrected':>9} {'escalated':>9} {'cost':>9}")
        for task, rs in sorted(tasks.items(), key=lambda kv: -len(kv[1])):
            corr = sum(1 for r in rs if r.get("corrected_next_turn"))
            esc = sum(1 for r in rs if r.get("escalated"))
            cost = sum(float(r.get("cost_usd", 0) or 0) for r in rs)
            lines.append(f"{task:16} {len(rs):>4} {corr:>9} {esc:>9} ${cost:>8.4f}")
    return "\n".join(lines)

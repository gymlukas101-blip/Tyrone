"""Monkey's stored model policy: which Claude model + effort to use for each task.

The shipped defaults live in model_policy.json (researched, with cost estimates). Your own changes and
calibration results live in %APPDATA%\\Monkey\\model_policy.json and override the defaults task by task,
so app updates never wipe them. A readable copy is written to memory (model_policy.md) so Monkey can
explain his choices.
"""
from __future__ import annotations

import copy
import json
import threading
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterable

from .costs import HAIKU, OPUS, PRICES, SONNET, WEB_SEARCH_USD

FABLE = "claude-fable-5-2"
MODELS = [HAIKU, SONNET, OPUS, FABLE]
MODEL_NAMES = {HAIKU: "Haiku 5.5", SONNET: "Sonnet 5.5", OPUS: "Opus 5.5", FABLE: "Fable 5.2"}
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
TIERS = ("min", "default", "max")

# Price table extension for Fable (only used if you force it): input, output, cache read, 5m cache write.
ALL_PRICES = {**PRICES, FABLE: (8.00, 40.00, 0.20, 10.00)}
# Rough output speed (tokens/s) and start-up time (s): Artificial Analysis / DeepLearning.AI, Nov 2026.
SPEED = {HAIKU: (230, 0.5), SONNET: (100, 0.8), OPUS: (75, 1.2), FABLE: (60, 1.5)}
# How much thinking each effort level produces relative to "medium" (Anthropic: effort scales thinking).
EFFORT_THINK = {"low": 0.3, "medium": 1.0, "high": 2.5, "xhigh": 5.0, "max": 8.0}
PREFIX_TOKENS = 4000    # persona + tool definitions + tool system prompt (cached)
HISTORY_TOKENS = 3000   # typical earlier conversation (cached)


@dataclass(frozen=True)
class Choice:
    model: str
    effort: str

    @property
    def label(self) -> str:
        return f"{MODEL_NAMES.get(self.model, self.model)} · {self.effort}"


def rank(c: Choice) -> int:
    """Cheapest -> strongest ordering used for budget step-downs and 'sticky model' checks."""
    return MODELS.index(c.model) * 10 + EFFORTS.index(c.effort) if c.model in MODELS else 0


def _valid(entry) -> Choice | None:
    if isinstance(entry, (list, tuple)) and len(entry) == 2 and entry[0] in MODELS and entry[1] in EFFORTS:
        return Choice(entry[0], entry[1])
    if isinstance(entry, dict) and entry.get("model") in MODELS and entry.get("effort") in EFFORTS:
        return Choice(entry["model"], entry["effort"])
    return None


def load_defaults() -> dict:
    return json.loads(resources.files("monkey.brain").joinpath("model_policy.json").read_text(encoding="utf-8"))


def estimate(est: dict, choice: Choice) -> dict:
    """Cost per use (USD) and seconds until Monkey starts speaking, from the task's token profile."""
    inp, out, cread, cwrite = ALL_PRICES.get(choice.model, ALL_PRICES[OPUS])
    ots, startup = SPEED.get(choice.model, SPEED[OPUS])
    rounds = max(1, int(est.get("rounds", 1)))
    new_in = float(est.get("new_in", 0))
    think = float(est.get("think", 0)) * EFFORT_THINK.get(choice.effort, 1.0)
    searches = float(est.get("searches", 0))
    prefix = 0 if est.get("no_prefix") else PREFIX_TOKENS + HISTORY_TOKENS
    usd = 0.0
    per = new_in / rounds
    for k in range(rounds):
        if est.get("no_prefix"):
            usd += per * inp / 1e6
        else:
            usd += (prefix + per * k) * cread / 1e6 + per * cwrite / 1e6
    usd += (float(est.get("out", 0)) + think + 60 * (rounds - 1)) * out / 1e6 + searches * WEB_SEARCH_USD
    first_words = rounds * startup + (think + 60 * (rounds - 1) + 20) / ots + 0.3 * (rounds - 1) + 1.5 * searches
    return {"usd": round(usd, 5), "first_words_s": round(first_words, 1),
            "per_month_usd": round(usd * float(est.get("per_month", 0)), 2)}


class ModelPolicy:
    def __init__(self, user_file: Path | str | None = None):
        self.user_file = Path(user_file) if user_file else None
        self._lock = threading.Lock()
        self.defaults = load_defaults()
        self.reload()

    # ------------------------------------------------------------ load / save
    def _user(self) -> dict:
        if not self.user_file or not self.user_file.exists():
            return {}
        try:
            data = json.loads(self.user_file.read_text(encoding="utf-8"))
            return data.get("tasks", {}) if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def reload(self) -> None:
        tasks = copy.deepcopy(self.defaults["tasks"])
        for tid, over in self._user().items():
            if tid not in tasks or not isinstance(over, dict):
                continue
            for tier in TIERS:
                c = _valid(over.get(tier))
                if c:
                    tasks[tid][tier] = [c.model, c.effort]
            if isinstance(over.get("measured"), dict):
                tasks[tid]["measured"] = over["measured"]
        self.tasks = tasks

    def _save_override(self, tid: str, changes: dict) -> None:
        if not self.user_file:
            return
        with self._lock:
            data = {"version": 1, "tasks": self._user()}
            data["tasks"].setdefault(tid, {}).update(changes)
            self.user_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.user_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            tmp.replace(self.user_file)
        self.reload()

    # ------------------------------------------------------------ queries
    def ids(self, include_internal: bool = True) -> list[str]:
        return [t for t, v in self.tasks.items() if include_internal or not v.get("internal")]

    def has(self, tid: str) -> bool:
        return tid in self.tasks

    def choice(self, tid: str, tier: str = "default") -> Choice:
        task = self.tasks.get(tid) or self.tasks["general"]
        return _valid(task[tier]) or Choice(SONNET, "low")

    def task(self, tid: str) -> dict:
        return self.tasks.get(tid) or self.tasks["general"]

    def in_range(self, tid: str, c: Choice) -> bool:
        return rank(self.choice(tid, "min")) <= rank(c) <= rank(self.choice(tid, "max"))

    def step_down(self, tid: str, c: Choice) -> Choice:
        """One notch cheaper, but never below the task's minimum."""
        lo = self.choice(tid, "min")
        if rank(c) <= rank(lo):
            return lo
        if c.effort != "low":
            cand = Choice(c.model, EFFORTS[EFFORTS.index(c.effort) - 1])
        else:
            prev = MODELS[max(0, MODELS.index(c.model) - 1)]
            cand = Choice(prev, "medium")
        return cand if rank(cand) >= rank(lo) else lo

    # ------------------------------------------------------------ edits
    def set_entry(self, tid: str, tier: str, model: str, effort: str) -> None:
        if tid not in self.tasks or tier not in TIERS:
            raise ValueError("unknown task or tier")
        c = _valid([model, effort])
        if c is None:
            raise ValueError("unknown model or effort")
        self._save_override(tid, {tier: [c.model, c.effort]})

    def set_measured(self, tid: str, measured: dict) -> None:
        self._save_override(tid, {"measured": measured})

    def reset(self, tid: str | None = None) -> None:
        if not self.user_file or not self.user_file.exists():
            return
        if tid is None:
            self.user_file.unlink()
        else:
            data = {"version": 1, "tasks": self._user()}
            data["tasks"].pop(tid, None)
            self.user_file.write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.reload()

    # ------------------------------------------------------------ views
    def table(self) -> list[dict]:
        rows = []
        for tid, t in self.tasks.items():
            est = t.get("est", {})
            row = {"id": tid, "label": t["label"], "why": t.get("why", ""), "internal": bool(t.get("internal")),
                   "measured": t.get("measured")}
            for tier in TIERS:
                c = self.choice(tid, tier)
                row[tier] = {"model": c.model, "effort": c.effort, "label": c.label, **estimate(est, c)}
            row["default_is_shipped"] = t["default"] == self.defaults["tasks"][tid]["default"]
            rows.append(row)
        return rows

    def monthly_total(self, tier: str = "default") -> float:
        return round(sum(r[tier]["per_month_usd"] for r in self.table()), 2)

    def memory_note(self) -> str:
        lines = ["# Which model I use for what",
                 "Auto = what I use normally. Quick = cheapest that works. Important = the most worth paying for.",
                 "The user can change these in Settings → Brain. Don't edit this file; it's rewritten from the policy.",
                 ""]
        for r in self.table():
            m = r.get("measured")
            extra = f" (measured ${m['usd']:.4f}, {m['first_words_s']}s)" if m and "usd" in m else ""
            lines.append(f"- {r['label']}: Auto {r['default']['label']}; Quick {r['min']['label']}; "
                         f"Important {r['max']['label']}{extra}")
        lines.append("")
        lines.append(f"Estimated monthly cost at Auto: about ${self.monthly_total():.0f}.")
        return "\n".join(lines) + "\n"

    def write_memory_note(self, memory) -> None:
        try:
            memory.write("model_policy.md", self.memory_note())
        except Exception:  # noqa: BLE001 - never block startup over the note
            pass


def unique(choices: Iterable[Choice]) -> list[Choice]:
    out: list[Choice] = []
    for c in choices:
        if c not in out:
            out.append(c)
    return out

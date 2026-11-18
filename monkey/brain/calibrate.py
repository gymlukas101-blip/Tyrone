"""Calibrate the model policy with real, measured runs (Settings → Brain → Calibrate models).

Runs one sample request per task on each candidate model+effort (the task's min, default and max), with
fake Canvas / Garmin / calendar / email data and stubbed tools, so nothing real is read, sent or changed.
Web search is real (it's part of what's being measured). Records the real token cost, time until the first
words and total time, and the answer text, so you can compare them side by side and pick.
"""
from __future__ import annotations

import json
import statistics
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from ..integrations.base import Email, Event
from .agent import Agent
from .costs import Usage
from .policy import TIERS, Choice, ModelPolicy, estimate, unique
from .router import Route
from .workspace import is_setup_error

SAMPLES: dict[str, str] = {
    "chat": "yo monkey, what's good?",
    "quick_fact": "how many tablespoons are in a quarter cup?",
    "command": "open canvas",
    "weather": "do I need a jacket today?",
    "web_lookup": "who won the most recent Wisconsin Badgers football game?",
    "assignments": "what should I work on tonight?",
    "check_off": "check off the CS 400 project proposal",
    "health": "how did I sleep last night?",
    "calendar": "what's on my calendar tomorrow?",
    "memory_note": "remember that my TA for Math 222 is Priya",
    "general": "why do cats purr?",
    "read_email": "read me the email from Professor Lee",
    "triage": "any important emails I need to deal with?",
    "briefing": "how's my day look?",
    "study_help": "explain the difference between mitosis and meiosis for my bio exam",
    "hard_problem": "I have three exams and a project due in five days. Make me a realistic study plan.",
    "draft_email": "draft a reply to Professor Lee asking for a two-day extension on the lab report",
    "research": "research the best laptops under $1200 for engineering students right now",
    "image_request": "make me a picture of a banana spaceship",
}

# Fake data returned by the stubbed tools (made up; nothing from your accounts).
FAKE: dict[str, object] = {
    "get_assignments": {"todo": [
        {"id": "a1", "course": "MATH 222", "name": "Problem Set 8", "due": "tomorrow 11:59 PM", "points": 30,
         "share_of_grade": "3.0%", "current_grade": "B+", "missing": False, "tier": "high"},
        {"id": "a2", "course": "CS 400", "name": "Project proposal", "due": "in 3 days", "points": 100,
         "share_of_grade": "10%", "current_grade": "A-", "missing": False, "tier": "critical"},
        {"id": "a3", "course": "BIO 151", "name": "Lab report 5", "due": "yesterday", "points": 20,
         "share_of_grade": "2%", "current_grade": "B", "missing": True, "tier": "critical"}]},
    "check_off_assignment": {"ok": True, "synced_to_canvas": True},
    "get_health": {"sleep_score": 78, "sleep": "7h 05m (deep 1h 20m, REM 1h 35m, light 3h 50m, awake 20m)",
                   "resting_hr": 52, "hrv_ms": 61, "body_battery": "charged to 84", "stress_avg": 28, "steps": 6400},
    "get_calendar": [{"title": "MATH 222 lecture", "start": "tomorrow 9:55 AM", "end": "10:45 AM", "where": "Van Vleck B102"},
                     {"title": "CS 400 office hours", "start": "tomorrow 2:30 PM", "end": "3:30 PM", "where": "CS 1240"},
                     {"title": "Intramural soccer", "start": "tomorrow 7:00 PM", "end": "8:00 PM", "where": "Near East Fields"}],
    "get_emails": [{"id": "e1", "from": "Prof. Lee <lee@wisc.edu>", "subject": "BIO 151 lab report",
                    "snippet": "Your lab report 5 hasn't been submitted…", "date": "today 8:12 AM"},
                   {"id": "e2", "from": "UW Housing", "subject": "Winter break move-out", "snippet": "Reminder…",
                    "date": "yesterday"},
                   {"id": "e3", "from": "Spotify", "subject": "Your Wrapped is here", "snippet": "", "date": "yesterday"}],
    "read_email": {"id": "e1", "from": "Prof. Lee <lee@wisc.edu>", "subject": "BIO 151 lab report",
                   "body": "Hi, I noticed your lab report 5 hasn't been submitted yet. It was due yesterday. "
                           "Late work loses 10% per day unless you reach out. Let me know if something came up. "
                           "Best, Dr. Lee"},
    "rank_items": {"summary": "Reply to Professor Lee about the missing lab report first; the CS 400 proposal is next.",
                   "top": [{"tier": "critical", "title": "Prof. Lee: BIO 151 lab report", "reason": "missing, losing 10%/day"},
                           {"tier": "high", "title": "CS 400 project proposal", "reason": "10% of grade, due in 3 days"}]},
    "get_weather": {"now": "34°F, cloudy, wind 12 mph", "today": "High 38°F, low 27°F, 40% chance of snow after 4 PM"},
    # (In calibration nothing is actually saved or sent; the model just sees a normal confirmation.)
    "draft_email": "Draft created and shown to the user for approval.",
    "open_website": "Opened.",
    "show_images": "Shown 4 images.",
    "show_videos": "Shown 3 videos.",
    "show_on_screen": "Shown on screen.",
    "emote": "Done.",
    "generate_image": "Generated 1 image and showed it on screen.",
    "escalate": "Handing off isn't available right now. Answer as well as you can yourself.",
}
FAKE_MEMORY = {
    "profile.md": "# Profile\n- Name: Sam\n- Sophomore at UW–Madison, computer science major\n- Lives in Sellery Hall\n",
    "writing_style.md": "# How the user writes emails\n- Greeting: 'Hi Professor X,' ; sign-off: 'Thanks, Sam'\n"
                        "- Short, polite, direct; 3-5 sentences; no exclamation marks.\n",
}


def _fake_items() -> list:
    """The same made-up inbox and calendar the other stubs describe, for the real ranking call."""
    now = datetime.now(timezone.utc)
    return [
        Email("e1", "gmail", "Prof. Lee", "lee@wisc.edu", ["you@wisc.edu"], "BIO 151 lab report",
              "Your lab report 5 hasn't been submitted yet. Late work loses 10% per day unless you reach out.",
              now - timedelta(hours=2), unread=True),
        Email("e2", "gmail", "UW Housing", "housing@wisc.edu", ["you@wisc.edu"], "Winter break move-out",
              "Reminder: residence halls close Dec 19 at noon.", now - timedelta(days=1)),
        Email("e3", "gmail", "Spotify", "no-reply@spotify.com", ["you@wisc.edu"], "Your Wrapped is here", "",
              now - timedelta(days=1)),
        Event("c1", "google", "MATH 222 lecture", now + timedelta(days=1, hours=3), location="Van Vleck B102"),
        Event("c2", "canvas", "CS 400 Project proposal due", now + timedelta(days=3)),
    ]


class _StubTools:
    """Fake data for every tool, except ranking, which really runs (it's part of what triage costs)."""

    def __init__(self, client=None, choice: Choice | None = None, ledger=None):
        self.s = SimpleNamespace(approval=SimpleNamespace(handle_voice=lambda text: None))
        self.client, self.choice, self.ledger = client, choice, ledger
        self.outputs: list[dict] = []     # what the model produced: drafts, on-screen content
        self.extra_usd = 0.0

    def run(self, name: str, args: dict):
        if name == "draft_email":
            self.outputs.append({"kind": "Email draft", "to": ", ".join(args.get("to") or []),
                                 "subject": str(args.get("subject", "")), "text": str(args.get("body", ""))[:4000]})
        elif name == "show_on_screen":
            self.outputs.append({"kind": "On screen", "subject": str(args.get("title", "")),
                                 "text": str(args.get("markdown", ""))[:4000]})
        elif name == "rank_items" and self.client is not None and self.choice is not None:
            return self._rank(), False
        out = FAKE.get(name, "Done.")
        return (out if isinstance(out, str) else json.dumps(out)), False

    def _rank(self) -> str:
        from .ranking import TIER_ORDER, rank_items

        items = _fake_items()
        ranking, usage = rank_items(self.client, items, FAKE_MEMORY["profile.md"],
                                    effort=self.choice.effort, model=self.choice.model)
        if usage is not None and self.ledger is not None:
            self.extra_usd += self.ledger.record(self.choice.model, self.choice.effort, "calibration",
                                                 Usage.from_response(usage))
        by_id = {i.id: i for i in items}
        rows = [{"tier": r.tier, "reason": r.reason, "title": getattr(by_id.get(r.id), "subject", None)
                 or getattr(by_id.get(r.id), "title", r.id)} for r in sorted(ranking.items, key=lambda r: TIER_ORDER[r.tier])]
        return json.dumps({"summary": ranking.summary, "top": [r for r in rows if r["tier"] in ("critical", "high")][:8]})


class _StubMemory:
    def files(self):
        return sorted(FAKE_MEMORY)

    def read(self, name):
        return FAKE_MEMORY.get(name, "")

    def call(self, inp):
        path = str((inp or {}).get("path", ""))
        if (inp or {}).get("command") == "view":
            name = path.rsplit("/", 1)[-1]
            return FAKE_MEMORY.get(name) or "Directory /memories: " + ", ".join(FAKE_MEMORY)
        return "Saved."


class _FixedRouter:
    """Always the configuration under test; no escalation, no holding line."""

    def __init__(self, route: Route):
        self._route = route

    def route(self, *a, **k):
        return self._route

    def escalate(self, route):
        return route


def candidates(policy: ModelPolicy, task: str) -> list[Choice]:
    return unique(policy.choice(task, t) for t in TIERS)


def plan(policy: ModelPolicy) -> list[tuple[str, Choice]]:
    return [(task, c) for task in SAMPLES if policy.has(task) for c in candidates(policy, task)]


def estimate_cost(policy: ModelPolicy, tasks: list[str] | None = None, samples: int = 1) -> float:
    """Expected spend for a calibration run (+30% margin, shown before you confirm)."""
    jobs = [(t, c) for t, c in plan(policy) if not tasks or t in tasks]
    total = sum(estimate(policy.task(t).get("est", {}), c)["usd"] for t, c in jobs) * max(1, samples)
    return round(total * 1.3 + 0.05, 2)   # + warm-up


class Calibration:
    def __init__(self, client, policy: ModelPolicy, ledger, out_file: Path | str,
                 progress: Callable[[dict], None] = lambda p: None, samples: int = 1,
                 tasks: list[str] | None = None, warm_up: bool = True):
        self.client = client
        self.policy = policy
        self.ledger = ledger
        self.out_file = Path(out_file)
        self.progress = progress
        self.cancel = threading.Event()
        self.setup_error = ""
        self.samples = max(1, min(int(samples), 3))
        self.only = [t for t in (tasks or []) if t in SAMPLES] or None
        self.warm_up = warm_up

    def _agent(self, task: str, choice: Choice, tools, emit) -> Agent:
        agent = Agent(self.client, _FixedRouter(Route(choice.model, choice.effort, "normal", task, "calibration")),
                      tools, _StubMemory(), self.ledger, emit=emit, speak=lambda s: None, persist=False)
        agent.purpose = "calibration"
        return agent

    def _warm(self, models: list[str]) -> None:
        """One untimed request per model first, so writing the prompt cache and opening the connection
        don't get blamed on whichever task happens to run first."""
        for m in models:
            if self.cancel.is_set():
                return
            try:
                reply = self._agent("chat", Choice(m, "low"), _StubTools(), lambda e, p: None).handle("hi")
            except Exception as exc:  # noqa: BLE001
                reply = f"{type(exc).__name__}: {exc}"
            if is_setup_error(reply):
                # Key/workspace/credits problem: nothing else would work either.
                self.setup_error = reply.strip()
                self.cancel.set()
                return

    def run_one(self, task: str, choice: Choice) -> dict:
        events: list[tuple[float, str, dict]] = []
        t0 = time.monotonic()
        tools = _StubTools(self.client, choice, self.ledger)
        agent = self._agent(task, choice, tools, lambda e, p: events.append((time.monotonic() - t0, e, p)))
        answer = ""
        error = ""
        try:
            answer = agent.handle(SAMPLES[task])
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        total = time.monotonic() - t0
        first = next((t for t, e, p in events if e == "delta" and str(p.get("text", "")).strip()), total)
        usd = sum(float(p.get("usd", 0)) for _, e, p in events if e == "cost") + tools.extra_usd
        shown = "".join(str(p.get("text", "")) for _, e, p in events if e == "delta") or answer
        errors = [p.get("message") for _, e, p in events if e == "error"]
        if not error and not errors and usd == 0 and is_setup_error(shown):
            errors = [shown.strip()]   # the agent explained a key/workspace/credits problem instead of answering
        return {"model": choice.model, "effort": choice.effort, "label": choice.label, "usd": round(usd, 5),
                "first_words_s": round(first, 1), "total_s": round(total, 1), "answer": shown.strip(),
                "outputs": tools.outputs, "error": error or "; ".join(m for m in errors if m)}

    def run_config(self, task: str, choice: Choice) -> dict:
        """Run a configuration `samples` times; keep the median-speed answer and the average cost."""
        runs = []
        for _ in range(self.samples):
            runs.append(self.run_one(task, choice))
            if runs[-1]["error"] or self.cancel.is_set():
                return runs[-1]
        if len(runs) == 1:
            return runs[0]
        best = sorted(runs, key=lambda r: r["total_s"])[len(runs) // 2]
        return {**best, "usd": round(statistics.mean(r["usd"] for r in runs), 5),
                "first_words_s": round(statistics.median(r["first_words_s"] for r in runs), 1),
                "total_s": round(statistics.median(r["total_s"] for r in runs), 1), "samples": len(runs)}

    def run(self) -> dict:
        jobs = [(t, c) for t, c in plan(self.policy) if self.only is None or t in self.only]
        results: dict[str, dict] = {}
        if self.warm_up:
            self.progress({"done": 0, "total": len(jobs), "task": "Warming up", "config": "each model once"})
            self._warm(list(dict.fromkeys(c.model for _, c in jobs)))
        for i, (task, choice) in enumerate(jobs):
            if self.cancel.is_set():
                break
            self.progress({"done": i, "total": len(jobs), "task": self.policy.task(task)["label"], "config": choice.label})
            entry = results.setdefault(task, {"label": self.policy.task(task)["label"], "sample": SAMPLES[task], "runs": []})
            run = self.run_config(task, choice)
            entry["runs"].append(run)
            if run["error"] and is_setup_error(run["error"]):
                # Key/workspace/credits problem: every other run would fail the same way, so stop now.
                self.setup_error = run["error"]
                self.cancel.set()
        spent = round(sum(r["usd"] for t in results.values() for r in t["runs"]), 4)
        if self.only is not None:
            # Re-running a few tasks: keep the earlier results for everything else.
            try:
                prev = json.loads(self.out_file.read_text(encoding="utf-8"))
                results = {**prev.get("tasks", {}), **results}
            except (OSError, ValueError):
                pass
        out = {"date": date.today().isoformat(), "complete": not self.cancel.is_set(), "tasks": results,
               "setup_error": self.setup_error, "spent_usd": spent, "samples": self.samples,
               "rerun": self.only or []}
        self.out_file.parent.mkdir(parents=True, exist_ok=True)
        self.out_file.write_text(json.dumps(out, indent=1), encoding="utf-8")
        self.progress({"done": len(jobs), "total": len(jobs), "finished": True,
                       **({"error": self.setup_error} if self.setup_error else {})})
        return out


def apply_picks(policy: ModelPolicy, results: dict, picks: dict[str, object]) -> list[str]:
    """picks: {task: index of the answer you liked best, or "all" if they were all fine}.
    "all" keeps the cheapest measured configuration; a pick sets that configuration as the default."""
    changed: list[str] = []
    for task, pick in picks.items():
        shown = results.get("tasks", {}).get(task, {}).get("runs") or []
        ok = [r for r in shown if not r.get("error")]
        if not ok or not policy.has(task):
            continue
        if pick == "all":
            best = min(ok, key=lambda r: r["usd"])
        else:
            try:
                best = shown[int(pick)]  # type: ignore[arg-type]  # index as shown on screen
            except (ValueError, IndexError, TypeError):
                continue
            if best.get("error"):
                continue
        before = policy.choice(task)
        policy.set_entry(task, "default", best["model"], best["effort"])
        policy.set_measured(task, {"model": best["model"], "effort": best["effort"], "usd": best["usd"],
                                   "first_words_s": best["first_words_s"], "total_s": best["total_s"],
                                   "date": results.get("date", "")})
        if Choice(best["model"], best["effort"]) != before:
            changed.append(task)
    return changed

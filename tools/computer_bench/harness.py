"""Benchmark harness: run a goal through Monkey's real GoalRunner + Computer + drivers, with a *scripted* planner
(deterministic steps that name controls the way a model would) and a host that plays the user (approves only the
approvals a fixture's goal needs; denies everything else).

What this measures: the execution layer — routing, the permission gate, idempotency, recovery, waiting, verification,
checkpoints and the trace — on real Chromium. What it does not measure: model planning quality (no API key in CI);
the Claude planner is the same loop with ClaudeGoalPlanner in place of ScriptedPlanner.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

from monkey.automation.computer.goal import Plan
from monkey.automation.permissions import PermissionGate
from monkey.automation.tasks import S, Task


def C(name: str, target: str | None = None, role: str = "", **inp) -> dict:
    """A planner call that names its target the way a model would (visible name + role), resolved at run time."""
    if target is not None:
        inp["target"] = {"name": target, "role": role} if role else target
    return {"name": name, "input": inp}


@dataclass
class ScriptedPlanner:
    """steps: list of (condition(view, recent) -> bool | None, Plan). The first step whose condition holds (or None
    = next unused step) is returned. Mimics a planner reacting to the screen, without a model."""
    steps: list
    used: set = field(default_factory=set)
    calls: int = 0

    def plan(self, ctx: dict, attempt: int = 0) -> Plan:
        self.calls += 1
        view, recent = ctx["view"], ctx.get("recent", [])
        for i, (cond, p) in enumerate(self.steps):
            if cond is not None and cond(view, recent):
                if callable(p):
                    p = p(view)
                return Plan(calls=[dict(c) for c in p.calls], status=p.status, message=p.message,
                            evidence=p.evidence, subgoal=p.subgoal, model="scripted")
        for i, (cond, p) in enumerate(self.steps):
            if cond is None and i not in self.used:
                self.used.add(i)
                return Plan(calls=[dict(c) for c in p.calls], status=p.status, message=p.message,
                            evidence=p.evidence, subgoal=p.subgoal, model="scripted")
        return Plan(status="need_user", message="script exhausted", model="scripted")


def has(view, rx: str) -> bool:
    r = re.compile(rx, re.I)
    return any(r.search(e.name or "") for e in view.elements) or bool(r.search(view.title or ""))


class BenchHost:
    """Plays TaskManager for the runner, and the user for approvals (policy: approve iff the action matches)."""

    def __init__(self, gate: PermissionGate, approve: tuple[str, ...] = (), open_driver=None,
                 stop_after_ops: int = 0):
        self.gate = gate
        self.approve_rx = [re.compile(a, re.I) for a in approve]
        self.states: list[str] = []
        self.approvals = {"asked": 0, "approved": 0, "denied": 0}
        self.user_turns = 0
        self._open = open_driver
        self._stop = threading.Event()
        self.stop_after_ops = stop_after_ops
        self.t0 = time.time()
        self.timeout_s = 120.0

    def set_state(self, task, state: S, note: str = "") -> None:
        task.transition(state, note)
        self.states.append(state.value)

    def save(self, task) -> None:
        if self.stop_after_ops and sum(1 for c in task.checkpoints if c["step"] == "op") >= self.stop_after_ops:
            self._stop.set()                           # simulate Monkey closing mid-task

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def over_budget(self, task) -> str:
        if time.time() - self.t0 > self.timeout_s:
            return "the benchmark time limit"
        if task.usage.actions > task.budget.max_actions:
            return "too many actions"
        return ""

    def request_approval(self, task, action, page_url: str, risk) -> str:
        from monkey.automation.permissions import Risk

        a = self.gate.request(task.id, action, page_url, Risk[risk] if isinstance(risk, str) else risk)
        self.approvals["asked"] += 1
        if any(r.search(action.describe()) for r in self.approve_rx):
            self.gate.approve(a.id, a.token)
            self.approvals["approved"] += 1
        else:
            self.gate.deny(a.id)
            self.approvals["denied"] += 1
        return a.id

    def wait_user(self, task, timeout_s: float) -> dict | None:
        self.user_turns += 1
        if self.user_turns > 6:
            self._stop.set()                           # the "user" gives up: the run counts as failed
        return None

    def open_driver(self, kind: str, **kw):
        return self._open(kind, **kw) if self._open else None


def new_task(objective: str, url: str, **kw) -> Task:
    return Task(objective=objective, start_url=url, allowed_domains=["127.0.0.1", "localhost"], skill="general", **kw)

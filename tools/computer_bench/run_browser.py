"""Run the browser fixtures through Monkey's real executor on real Chromium and score against the server's record.

    python -m tools.computer_bench.run_browser [--only name,...] [--headed] [--out results.json]

Per fixture: success (server truth), failure reason, wall time, actions, planner calls, model calls/tokens/cost
(0 here: scripted planner), approvals asked/approved/denied, recoveries, driver switches, duplicate refusals,
verification refusals, browser startup time, median/p95 action latency.
"""
from __future__ import annotations

import argparse
import json
import platform
import tempfile
import time
from pathlib import Path

from monkey.automation.browser import BrowserSession
from monkey.automation.computer import Computer, Trace
from monkey.automation.computer.drivers.browser import BrowserDriver
from monkey.automation.computer.drivers.visual import JsonGrounder, VisualDriver
from monkey.automation.computer.goal import GoalRunner
from monkey.automation.permissions import PermissionGate

from . import fixtures as fx
from .harness import BenchHost, ScriptedPlanner, new_task
from .scripts import SCRIPTS


def green_button(image, description: str):
    """Test grounder: the centroid of saturated green pixels (the canvas Start button)."""
    import numpy as np

    a = np.asarray(image.convert("RGB")).astype(int)
    mask = (a[..., 1] > 130) & (a[..., 0] < 80) & (a[..., 2] < 110)
    if mask.sum() < 30:
        return None
    ys, xs = np.nonzero(mask)
    return float(xs.mean()), float(ys.mean())


def _subst(steps, mapping: dict):
    out = []
    for cond, p in steps:
        calls = []
        for c in p.calls:
            inp = {k: (v.format(**mapping) if isinstance(v, str) and "{" in v else v)
                   for k, v in (c.get("input") or {}).items()}
            calls.append({"name": c["name"], "input": inp})
        from monkey.automation.computer.goal import Plan

        out.append((cond, Plan(calls=calls, status=p.status, message=p.message, evidence=p.evidence,
                               subgoal=p.subgoal)))
    return out


def run_fixture(name: str, port: int, workdir: Path, headless: bool = True, restart: bool = False) -> dict:
    fx.S.reset()
    spec = SCRIPTS[name]
    report = workdir / "report.txt"
    report.write_text("Weekly report\n")
    gate = PermissionGate()
    kw = {}
    if spec.get("files"):
        kw["files"] = [str(report)]
    if spec.get("visual"):
        kw["send_screenshots"] = True
    url = f"http://127.0.0.1:{port}/f/{name}"
    task = new_task(fx.FIXTURES[name]["goal"], url, **kw)
    t0 = time.time()
    from tools.automation_eval import browser_path

    sess = BrowserSession(workdir / f"profile-{name}", gate, headless=headless, channel=None,
                          executable_path=browser_path(), allowed_domains=task.allowed_domains)
    result: dict = {"fixture": name, "goal": fx.FIXTURES[name]["goal"]}
    try:
        sess.start()
        result["browser_startup_ms"] = int((time.time() - t0) * 1000)
        drv = BrowserDriver(sess)
        trace = Trace(task.id)
        visual = VisualDriver(drv, JsonGrounder(green_button)) if spec.get("visual") else None
        host = BenchHost(gate, approve=spec.get("approve", ()), stop_after_ops=1 if restart else 0)
        comp = Computer(task, gate, {"browser": drv}, trace, should_stop=host.should_stop, visual=visual,
                        save=lambda: host.save(task))
        comp.do("navigate", None, url=url)
        planner = ScriptedPlanner(_subst(spec["steps"], {"report": str(report)}))
        runner = GoalRunner(task, comp, planner, host)
        state = runner.run()
        resumed = False
        if restart and state == "stopped":
            # Monkey "restarts": a new Computer rebuilt from the task's checkpoints, same browser profile, no replay.
            resumed = True
            host._stop.clear()
            host.stop_after_ops = 0
            comp2 = Computer(task, gate, {"browser": drv}, Trace(task.id), should_stop=host.should_stop,
                             save=lambda: host.save(task))
            comp2.trace.events = trace.events                 # one trace for the whole task
            result["uncertain_after_restart"] = comp2.uncertain()
            state = GoalRunner(task, comp2, planner, host).run()
            trace = comp2.trace
        ok = bool(fx.FIXTURES[name]["check"]())
        m = trace.metrics()
        ev = trace.events
        result.update({
            "success": ok, "runner_state": state, "task_state": task.state.value, "resumed": resumed,
            "seconds": round(time.time() - t0, 2), "planner_calls": planner.calls,
            "duplicates_refused": sum(1 for e in ev if e.get("error") == "duplicate"),
            "gate_refusals": sum(1 for e in ev if e.get("error") in ("refused", "needs_approval", "needs_user")),
            "verify_rejections": sum(1 for e in ev if e["ev"] == "ACTION_FAILED" and e.get("op") == "verify"),
            "approvals": host.approvals, "user_turns": host.user_turns, "states": host.states[-12:],
            "server": {"saved": fx.S.saved.get(name), "counts": {k: v for k, v in fx.S.counts.items()},
                       "files": [f[0] for f in fx.S.files.get(name, [])]},
            **m,
        })
        if not ok:
            fails = [e for e in ev if e["ev"] == "ACTION_FAILED"]
            result["failure_reason"] = (fails[-1].get("detail") or fails[-1].get("error")) if fails else state
    finally:
        sess.close()
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    names = [n for n in SCRIPTS if not a.only or n in a.only.split(",")]
    srv, port = fx.serve()
    rows = []
    with tempfile.TemporaryDirectory() as d:
        for n in names:
            try:
                r = run_fixture(n, port, Path(d), headless=not a.headed, restart=(n == "restart"))
            except Exception as exc:  # noqa: BLE001 - a crash is a failed fixture, not a crashed benchmark
                r = {"fixture": n, "success": False, "failure_reason": f"crash: {type(exc).__name__}: {exc}"[:300]}
            rows.append(r)
            print(f"{'PASS' if r['success'] else 'FAIL'} {n:20s} {r.get('seconds', 0):6.2f}s actions={r.get('actions')}"
                  f" recov={r.get('recoveries')} dup={r.get('duplicates_refused')} "
                  f"refused={r.get('gate_refusals')} {r.get('failure_reason', '')}")
    srv.shutdown()
    summary = {"platform": f"{platform.system()} {platform.release()}", "python": platform.python_version(),
               "fixtures": len(rows), "passed": sum(1 for r in rows if r["success"]),
               "planner": "scripted (no model calls)", "rows": rows}
    if a.out:
        Path(a.out).write_text(json.dumps(summary, indent=1, default=str))
    print(f"{summary['passed']}/{summary['fixtures']} passed")
    return 0 if summary["passed"] == summary["fixtures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

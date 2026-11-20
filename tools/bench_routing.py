"""CLI for the routing benchmark (the implementation lives in monkey/brain/bench_routing.py so the app can run it).

    python -m tools.bench_routing            # offline: rule coverage + precision ($0)
    python -m tools.bench_routing --live     # + Haiku classifier accuracy, latency, cost (needs your Anthropic key)
    python -m tools.bench_routing --from-traces [DIR]
        # real turns from %APPDATA%\\Monkey\\traces: per-task counts, corrections, escalations, cost; with
        # "keep what you asked" on, also re-routes each request with today's rules and lists likely misroutes
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from monkey.brain.bench_routing import CASES, live, offline, summary_text
from monkey.brain.router import Router


def from_traces(folder: Path) -> str:
    from monkey.brain.router import rule_task
    from monkey.trace import load_traces, report

    recs = load_traces(folder)
    lines = [report(recs)]
    texts = [r for r in recs if r.get("text") and r.get("task")]
    if texts:
        lines += ["", "Likely misroutes (corrected by you next turn, escalated, or today's rules disagree):"]
        for r in texts:
            now, _why = rule_task(r["text"])
            flags = [f for f, on in (("corrected", r.get("corrected_next_turn")), ("escalated", r.get("escalated")),
                                     (f"rules now say {now}", now is not None and now != r["task"])) if on]
            if flags:
                lines.append(f"  [{r['task']}] {r['text'][:80]}  — {', '.join(flags)}")
    else:
        lines += ["", "(Request text isn't kept, so misroutes can't be listed. Turn on Settings → Brain → "
                      "\"Keep what I ask in local traces\" to evaluate routing on your own requests.)"]
    return "\n".join(lines)


def main() -> None:
    if "--from-traces" in sys.argv:
        i = sys.argv.index("--from-traces")
        import os

        default = Path(os.environ.get("APPDATA", str(Path.home()))) / "Monkey" / "traces"
        folder = Path(sys.argv[i + 1]) if len(sys.argv) > i + 1 else default
        print(from_traces(folder))
        return
    out = {"offline": offline()}
    if "--live" in sys.argv:
        import anthropic

        from monkey import keys

        out["live"] = live(anthropic.Anthropic(api_key=keys.get("anthropic") or None))
    print(summary_text(out))
    (Path(__file__).with_name("bench_routing_last.json")).write_text(json.dumps(out, indent=1))
    r = Router()
    assert all(r.route(t).model for t, _ in CASES)      # sanity: routing works with no classifier at all


if __name__ == "__main__":
    main()

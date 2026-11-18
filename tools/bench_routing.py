"""CLI for the routing benchmark (the implementation lives in monkey/brain/bench_routing.py so the app can run it).

    python -m tools.bench_routing            # offline: rule coverage + precision ($0)
    python -m tools.bench_routing --live     # + Haiku classifier accuracy, latency, cost (needs your Anthropic key)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from monkey.brain.bench_routing import CASES, live, offline, summary_text
from monkey.brain.router import Router


def main() -> None:
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

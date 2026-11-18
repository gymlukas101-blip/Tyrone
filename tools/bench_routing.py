"""Routing benchmark: rules-first vs the Haiku classifier, on representative (fake) voice requests.

    python -m tools.bench_routing            # offline: rule coverage + rule accuracy (no API calls, $0)
    python -m tools.bench_routing --live     # + Haiku classifier accuracy, latency and cost (needs ANTHROPIC key)

Decision rule (from the sprint brief): only drop or replace the classifier if quality and cost both improve;
escalation for hard tasks stays either way. Writes tools/bench_routing_last.json.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

from monkey.brain.router import Router, rule_task

# (request, acceptable task ids). Several tasks are legitimately interchangeable (e.g. general/quick_fact).
CASES: list[tuple[str, set[str]]] = [
    ("yo what's up", {"chat"}),
    ("thanks monkey", {"chat"}),
    ("how's my day look", {"briefing", "triage"}),
    ("what's on my plate this week", {"briefing", "triage"}),
    ("what do I have due tomorrow", {"assignments"}),
    ("what's due for my design class", {"assignments"}),
    ("I finished the reading quiz, check it off", {"check_off"}),
    ("when is my next class", {"calendar"}),
    ("what time is my speech class on thursday", {"calendar"}),
    ("do I have anything after 3 today", {"calendar"}),
    ("any new emails", {"read_email", "triage"}),
    ("read me the email from my professor", {"read_email"}),
    ("draft an email to my professor asking for an extension on the proposal", {"draft_email"}),
    ("write a reply saying I'll be at the meeting", {"draft_email"}),
    ("how did I sleep", {"health"}),
    ("what's my recovery like today", {"health"}),
    ("what's the weather", {"weather"}),
    ("is it gonna snow this weekend", {"weather"}),
    ("open canvas", {"command"}),
    ("open my email", {"command", "read_email"}),          # ambiguous: open Gmail vs. show the inbox
    ("remember that my speech is on friday", {"memory_note"}),
    ("forget what I said about the club meeting", {"memory_note"}),
    ("what's the capital of australia", {"quick_fact", "general", "web_lookup"}),
    ("how many ounces in a cup", {"quick_fact", "general"}),
    ("who won the packers game last night", {"web_lookup"}),
    ("what's the latest roblox studio update", {"web_lookup", "research"}),
    ("explain supply and demand like I'm cramming for a quiz", {"study_help"}),
    ("quiz me on the key terms for my entrepreneurship exam", {"study_help"}),
    ("compare three ways to do matchmaking for a 3v3 roblox game and recommend one", {"research", "hard_problem"}),
    ("research the best snowboard bindings for park under 300 dollars", {"research"}),
    ("help me design a ranked draft system that won't let people dodge", {"hard_problem", "research"}),
    ("debug why my lua remote event fires twice", {"hard_problem", "study_help"}),
    ("make me an image of a buff monkey snowboarding", {"image_request"}),
    ("draw a logo for my game", {"image_request"}),
    ("what should I work on first today", {"triage", "briefing", "assignments"}),
    ("rank my emails by importance", {"triage"}),
    ("learn how I write emails", {"style_learning"}),
    ("what did we decide about the boss fight last time", {"general", "memory_note"}),
    ("give me speech note cards for a 3 minute persuasive speech", {"study_help", "general"}),
    ("write a 16 bar verse with triplet flow about snowboarding", {"general", "hard_problem"}),
    ("is it worth adding a survival mode before ranked", {"general", "hard_problem", "research"}),
    ("tell me a joke", {"chat", "general"}),
]


def offline() -> dict:
    covered = correct = 0
    misses, falls = [], []
    for text, ok in CASES:
        task, _why = rule_task(text)
        if task is None:
            falls.append(text)
            continue
        covered += 1
        if task in ok:
            correct += 1
        else:
            misses.append({"text": text, "got": task, "want": sorted(ok)})
    return {"cases": len(CASES), "rule_covered": covered, "rule_correct": correct,
            "rule_precision": round(correct / covered, 3) if covered else None,
            "fall_through_to_classifier": len(falls), "rule_misses": misses, "fallthrough": falls}


def live() -> dict:
    import anthropic

    from monkey import keys
    from monkey.brain.costs import HAIKU, Usage, cost_usd
    from monkey.brain.router import classify_with_haiku

    client = anthropic.Anthropic(api_key=keys.get("anthropic") or None)
    rows = []
    for text, ok in CASES:
        if rule_task(text)[0] is not None:
            continue                                     # rules already handle it; no classifier call
        t = time.perf_counter()
        task, diff, web, why, usage = classify_with_haiku(client, text)
        dt = time.perf_counter() - t
        usd = cost_usd(HAIKU, Usage.from_response(usage))
        rows.append({"text": text, "task": task, "ok": task in ok, "latency_s": round(dt, 3), "usd": usd})
    lat = [r["latency_s"] for r in rows]
    return {"classified": len(rows), "accuracy": round(sum(r["ok"] for r in rows) / len(rows), 3) if rows else None,
            "latency_p50_s": statistics.median(lat) if lat else None,
            "latency_max_s": max(lat) if lat else None, "usd_total": round(sum(r["usd"] for r in rows), 5),
            "rows": rows}


def main() -> None:
    out = {"offline": offline()}
    if "--live" in sys.argv:
        out["live"] = live()
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in ("rows", "fallthrough")} for k, v in out.items()},
                     indent=1))
    (Path(__file__).with_name("bench_routing_last.json")).write_text(json.dumps(out, indent=1))
    # sanity: the router still produces a route for every case without a classifier
    r = Router()
    assert all(r.route(t).model for t, _ in CASES)


if __name__ == "__main__":
    main()

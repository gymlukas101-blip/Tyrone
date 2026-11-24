"""Routing benchmark: rules-first vs the Haiku classifier, on 55 representative (fake) voice requests.

Runs inside Monkey (Settings -> Brain -> Run routing benchmark) with the key Monkey already stores, or from a dev
checkout with `python -m tools.bench_routing [--live]`. Offline = rule coverage/precision ($0). Live = the Haiku
classifier on the requests the rules don't catch: accuracy, latency and cost (~14 calls, well under $0.01).
Decision rule: only replace or drop the classifier if quality AND cost improve; escalation stays either way.
"""
from __future__ import annotations

import statistics
import time
from typing import Callable

from .router import rule_task

# (request, acceptable task ids). Several tasks are legitimately interchangeable (e.g. general/quick_fact).
CASES: list[tuple[str, set[str]]] = [
    ("yo what's up", {"chat"}),
    ("thanks monkey", {"chat"}),
    ("how's my day look", {"briefing", "triage"}),
    ("what's on my plate this week", {"briefing", "triage"}),
    ("what do I have due tomorrow", {"assignments"}),
    ("what's due for my design class", {"assignments"}),
    ("I finished the reading quiz, check it off", {"check_off"}),
    ("add buy groceries to my to-do list", {"todo"}),
    ("remind me to call the dentist tomorrow at 5", {"todo"}),
    ("what's on my to-do list", {"todo"}),
    ("what do I need to do today", {"todo", "briefing", "assignments"}),
    ("I dropped marketing", {"course_drop"}),
    ("remove all my marketing assignments", {"course_drop"}),
    ("hide the marketing class", {"course_drop"}),
    ("unsubscribe me from the medium newsletter", {"task_helper"}),
    ("cancel my spotify free trial reminder", {"task_helper"}),
    ("go to the gym's website and cancel my membership", {"task_helper"}),
    ("find the cheapest flight to denver on the 18th, just show me", {"task_helper", "web_lookup", "research"}),
    ("when is my next class", {"calendar"}),
    ("what time is my speech class on thursday", {"calendar"}),
    ("do I have anything after 3 today", {"calendar"}),
    ("any new emails", {"read_email", "triage"}),
    ("read me the email from my professor", {"read_email"}),
    ("draft an email to my professor asking for an extension on the proposal", {"draft_email"}),
    ("write a reply saying I'll be at the meeting", {"draft_email"}),
    ("how did I sleep", {"health"}),
    ("what's my recovery like today", {"health"}),
    ("how much was I on my phone today", {"health"}),
    ("what's my screen time this week", {"health"}),
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


def live(client, on_progress: Callable[[int, int, str], None] = lambda i, n, t: None,
         record: Callable[[object], None] | None = None) -> dict:
    """Classify every request the rules don't handle with the real Haiku classifier."""
    from .costs import HAIKU, Usage, cost_usd
    from .router import classify_with_haiku

    todo = [(t, ok) for t, ok in CASES if rule_task(t)[0] is None]
    rows = []
    for i, (text, ok) in enumerate(todo):
        on_progress(i, len(todo), text)
        t = time.perf_counter()
        try:
            task, diff, web, why, usage = classify_with_haiku(client, text)
        except Exception as exc:  # noqa: BLE001
            rows.append({"text": text, "task": None, "ok": False, "latency_s": round(time.perf_counter() - t, 3),
                         "usd": 0.0, "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
            continue
        dt = time.perf_counter() - t
        if record is not None and usage is not None:
            record(usage)
        usd = cost_usd(HAIKU, Usage.from_response(usage)) if usage is not None else 0.0
        rows.append({"text": text, "task": task, "want": sorted(ok), "ok": task in ok, "difficulty": diff,
                     "needs_web": web, "latency_s": round(dt, 3), "usd": usd})
    lat = [r["latency_s"] for r in rows if r.get("task")]
    good = [r for r in rows if r.get("task")]
    return {"classified": len(rows), "errors": sum(1 for r in rows if r.get("error")),
            "accuracy": round(sum(r["ok"] for r in good) / len(good), 3) if good else None,
            "latency_p50_s": round(statistics.median(lat), 3) if lat else None,
            "latency_max_s": round(max(lat), 3) if lat else None,
            "usd_total": round(sum(r["usd"] for r in rows), 5),
            "misses": [{k: r[k] for k in ("text", "task", "want") if k in r} for r in good if not r["ok"]],
            "rows": rows}


def summary_text(res: dict) -> str:
    off, lv = res.get("offline", {}), res.get("live")
    s = (f"Rules: {off.get('rule_correct')}/{off.get('rule_covered')} correct on the {off.get('rule_covered')} of "
         f"{off.get('cases')} requests they handle; {off.get('fall_through_to_classifier')} go to the classifier.")
    if lv:
        s += (f" Classifier: {lv['accuracy'] * 100:.0f}% right, median {lv['latency_p50_s']} s "
              f"(max {lv['latency_max_s']} s), ${lv['usd_total']:.4f} total") if lv.get("accuracy") is not None \
            else " Classifier: no successful calls."
        if lv.get("errors"):
            s += f", {lv['errors']} errors"
        s += "."
    return s

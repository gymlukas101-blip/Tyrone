"""Voice benchmark: "you stop → he speaks" for a fixed set of spoken turns, before and after Voice 2.0.

    python -m tools.voice_bench                       # table + p50/p95, baseline vs current
    python -m tools.voice_bench --params my.json      # your own vendor timings (e.g. from the Dell's turn traces)
    python -m tools.voice_bench --from-traces DIR     # take STT / first-token / first-audio medians from real traces

What's real and what's assumed:
- REAL (the app's own code decides): when the turn ends (endpointer rules, early commit with turn.py, cut-offs during
  mid-thought pauses), whether the classifier runs (router rules + fast voice path), when the first speakable piece
  appears in the reply text (SentenceChunker, early clause).
- ASSUMED (vendor/hardware timings, editable with --params): Whisper time per second of audio, classifier call,
  Claude's first token and token rate, Fish's first audio packet with a cold or kept-alive connection, device output
  latency. Defaults are conservative laptop/cloud figures, not measurements; replace them with the Dell's traces.
"""
from __future__ import annotations

import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

from monkey.audio.endpoint import END_SILENCE_PRESETS, FRAME_MS
from monkey.audio.listener import EARLY_MS, TRAIL_OFF_EXTRA_MS
from monkey.audio.turn import commit_after_ms, completeness
from monkey.brain.policy import ModelPolicy
from monkey.brain.router import Router
from monkey.brain.speech_text import SentenceChunker

DEFAULTS = {
    "stt_base_s": 0.25, "stt_per_audio_s": 0.18,      # Whisper small.en int8 on a laptop CPU (assumed)
    "classifier_s": 0.8,                              # Haiku structured-output call (assumed; capped at 4 s in code)
    "context_s": 0.05,                                # memory recall + context build (measured locally: tens of ms)
    "first_token_s": {"haiku": 0.55, "sonnet": 0.9, "opus": 1.4},
    "tokens_per_s": 60, "chars_per_token": 4.0,
    "fish_first_cold_s": 0.70, "fish_first_warm_s": 0.45,   # TLS handshake is the difference (assumed)
    "output_latency_s": 0.10,
    "short_ms": 1500, "short_extra_ms": 400,
}


@dataclass
class Turn:
    name: str
    segments: list[tuple[int, int]]      # (speech ms, pause ms after it); the last pause is the end of the turn
    words_at_pause: list[str]            # transcript of everything said up to each pause
    reply: str
    kind: str = "simple"                 # simple | command | thinking | goodbye


TURNS = [
    Turn("question", [(1200, 0)], ["What's due this week?"],
         "Two things: your stats lab on Tuesday, and the English essay on Friday."),
    Turn("command", [(800, 0)], ["Open canvas."], "Opening Canvas for you now.", "command"),
    Turn("quick fact", [(1400, 0)], ["What's the capital of Australia?"],
         "It's Canberra, not Sydney, which surprises a lot of people."),
    Turn("mid-thought pause", [(1000, 1600), (1300, 0)], ["Remind me to call", "Remind me to call my mom at five."],
         "Got it, I'll remind you at five to call your mom."),
    Turn("breath between clauses", [(900, 400), (1500, 0)], ["Check my email", "Check my email and tell me if the professor replied."],
         "Your professor replied this morning: the deadline moved to Monday."),
    Turn("long question", [(4200, 0)], ["Can you explain how photosynthesis works and why plants need light for it?"],
         "Sure, plants turn light, water and carbon dioxide into sugar and oxygen. Light powers the first step."),
    Turn("thinking task", [(2200, 0)], ["Help me design a study plan for my finals."],
         "Okay, let's build it around your exam dates, starting with the hardest class first.", "thinking"),
    Turn("thanks", [(500, 0)], ["Thanks!"], "Anytime!", "goodbye"),
    Turn("opinion", [(1600, 0)], ["Is it worth adding a survival mode before ranked?"],
         "Honestly, I'd ship ranked first, since your players keep asking for it."),
    Turn("chat", [(1100, 0)], ["Tell me a joke."], "Why did the banana go to the doctor? It wasn't peeling well."),
]


@dataclass
class Result:
    name: str
    endpoint_s: float
    stt_after_s: float
    route_s: float
    first_token_s: float
    first_piece_s: float
    tts_s: float
    total_s: float
    cut_off: bool = False
    classifier: bool = False
    stages: dict = field(default_factory=dict)


def _family(model: str) -> str:
    return "opus" if "opus" in model else "sonnet" if "sonnet" in model else "haiku"


def _first_piece_s(reply: str, early_clause: bool, p: dict) -> float:
    """Seconds from the first token until the chunker hands over the first speakable piece (real chunker)."""
    c = SentenceChunker(early_clause=early_clause)
    tokens, pos = [], 0
    while pos < len(reply):
        step = max(1, int(p["chars_per_token"]))
        tokens.append(reply[pos:pos + step])
        pos += step
    for i, tok in enumerate(tokens):
        if c.feed(tok):
            return i / p["tokens_per_s"]
    return len(tokens) / p["tokens_per_s"]


def simulate(turn: Turn, current: bool, p: dict, warm: bool = True) -> Result:
    silence_ms = END_SILENCE_PRESETS["normal"]
    total_speech = sum(s for s, _ in turn.segments)
    short_extra = p["short_extra_ms"] if total_speech < p["short_ms"] else 0
    audio_s = total_speech / 1000 + 0.5
    stt_s = p["stt_base_s"] + p["stt_per_audio_s"] * audio_s
    cut = False
    # -- end of turn (and mid-thought pauses) ------------------------------------------------------------------
    for i, (_speech, pause) in enumerate(turn.segments[:-1]):
        words = turn.words_at_pause[i]
        need = silence_ms + short_extra
        if current:
            wait = commit_after_ms(words)
            early_ready = EARLY_MS + stt_s * 1000
            if wait is not None and pause >= max(wait, early_ready):
                cut = True                               # ended early during a mid-thought pause
            if completeness(words) == "incomplete":
                need += TRAIL_OFF_EXTRA_MS
        if pause >= need:
            cut = True
    final_words = turn.words_at_pause[-1]
    stt_after = stt_s
    normal_ms = silence_ms + short_extra
    if current:
        wait = commit_after_ms(final_words)
        ready_ms = EARLY_MS + stt_s * 1000           # the pause's background transcription is done by then
        if completeness(final_words) == "incomplete":
            normal_ms += TRAIL_OFF_EXTRA_MS
        early_ms = max(wait, ready_ms) if wait is not None else None
        if early_ms is not None and early_ms < normal_ms:
            endpoint_ms, stt_after = early_ms, 0.0   # ended early; already transcribed
        else:
            endpoint_ms = normal_ms                  # the normal rule ends it; reuse the in-flight transcription
            stt_after = max(0.0, (ready_ms - normal_ms) / 1000)
    else:
        endpoint_ms = normal_ms
    endpoint_ms = (endpoint_ms // FRAME_MS + (1 if endpoint_ms % FRAME_MS else 0)) * FRAME_MS
    # -- routing --------------------------------------------------------------------------------------------------
    used = {"n": 0}

    def classify(text):
        used["n"] += 1
        return ("general", 2, False, "bench", None)
    router = Router(classify=classify, policy=ModelPolicy())
    route = router.route(final_words, fast=current)
    route_s = (p["classifier_s"] if used["n"] else 0.0) + p["context_s"]
    if turn.kind == "goodbye":
        route_s, ft, piece = 0.0, 0.0, 0.0              # sign-offs are spoken without a model call
    else:
        ft = p["first_token_s"][_family(route.model)]
        piece = _first_piece_s(turn.reply, early_clause=current, p=p)
    tts = (p["fish_first_warm_s"] if (current and warm) else p["fish_first_cold_s"]) + p["output_latency_s"]
    total = endpoint_ms / 1000 + stt_after + route_s + ft + piece + tts
    return Result(turn.name, endpoint_ms / 1000, stt_after, route_s, ft, piece, tts, total, cut, bool(used["n"]))


def pct(v: list[float], q: float) -> float:
    v = sorted(v)
    k = (len(v) - 1) * q
    lo = int(k)
    return v[lo] + (v[min(lo + 1, len(v) - 1)] - v[lo]) * (k - lo)


def run(p: dict) -> dict:
    rows = []
    for t in TURNS:
        b, c = simulate(t, False, p), simulate(t, True, p)
        rows.append((t, b, c))
    base = [b.total_s for _, b, _ in rows]
    cur = [c.total_s for _, _, c in rows]
    return {"rows": rows, "p50": (statistics.median(base), statistics.median(cur)),
            "p95": (pct(base, .95), pct(cur, .95)),
            "cutoffs": (sum(b.cut_off for _, b, _ in rows), sum(c.cut_off for _, _, c in rows)),
            "classifier": (sum(b.classifier for _, b, _ in rows), sum(c.classifier for _, _, c in rows))}


def report(res: dict, p: dict) -> str:
    out = ["Voice turn: you stop → he speaks (seconds). Baseline = before Voice 2.0; now = this branch.",
           "Real decisions: endpointing, early commit, routing, chunking. Assumed vendor timings: see --params.", "",
           f"{'turn':24} {'base':>6} {'now':>6}  {'end-of-turn':>12} {'stt after':>10} {'route':>6} {'1st tok':>7} "
           f"{'1st piece':>9} {'voice':>6}"]
    for t, b, c in res["rows"]:
        out.append(f"{t.name:24} {b.total_s:6.2f} {c.total_s:6.2f}  {b.endpoint_s:5.2f}→{c.endpoint_s:4.2f} "
                   f"{b.stt_after_s:4.2f}→{c.stt_after_s:4.2f} {c.route_s:6.2f} {c.first_token_s:7.2f} "
                   f"{b.first_piece_s:4.2f}→{c.first_piece_s:4.2f} {b.tts_s:4.2f}→{c.tts_s:4.2f}"
                   + ("  CUT OFF" if c.cut_off else ""))
    (b50, c50), (b95, c95) = res["p50"], res["p95"]
    out += ["", f"p50: {b50:.2f} s → {c50:.2f} s   p95: {b95:.2f} s → {c95:.2f} s",
            f"cut-offs during mid-thought pauses: {res['cutoffs'][0]} → {res['cutoffs'][1]}",
            f"classifier calls on the critical path: {res['classifier'][0]} → {res['classifier'][1]}", "",
            "assumptions: " + json.dumps(p)]
    return "\n".join(out)


def params_from_traces(folder: Path, p: dict) -> dict:
    from monkey.trace import load_traces, span_stats

    rows = {r["span"]: r for r in span_stats(load_traces(folder))}
    q = dict(p)
    if "speech → text" in rows:
        q["stt_base_s"], q["stt_per_audio_s"] = rows["speech → text"]["p50"] / 1000, 0.0
    if "request → first word" in rows:
        q["first_token_s"] = {k: rows["request → first word"]["p50"] / 1000 for k in p["first_token_s"]}
    if "sentence → first sound" in rows:
        q["fish_first_warm_s"] = q["fish_first_cold_s"] = rows["sentence → first sound"]["p50"] / 1000
        q["output_latency_s"] = 0.0
    return q


def main(argv: list[str]) -> int:
    p = dict(DEFAULTS)
    if "--params" in argv:
        p.update(json.loads(Path(argv[argv.index("--params") + 1]).read_text()))
    if "--from-traces" in argv:
        p = params_from_traces(Path(argv[argv.index("--from-traces") + 1]), p)
    print(report(run(p), p))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

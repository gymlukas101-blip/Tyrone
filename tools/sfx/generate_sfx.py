"""Generate Monkey's sound-effect kit with the ElevenLabs Sound Effects API, then normalize + encode.

    python -m tools.sfx.generate_sfx [--only pop,thump] [--budget 4000] [--dry-run]

The ElevenLabs key is injected by the session's network proxy (never in code). The API reports each
request's cost in the `character-cost` header; the script stops at --budget credits.
Outputs ui/public/sfx/<cue>_<n>.ogg + ui/public/sfx/index.json.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

from .audio import post, qc, write_manifest

ROOT = Path(__file__).resolve().parents[2]
SFX = ROOT / "ui" / "public" / "sfx"
RAW = ROOT / "tools" / "sfx" / "raw"        # untouched API output (gitignored), so re-processing is free
SUFFIX = ". Isolated sound effect, no music, no voice, close-mic, dry, clean, game sound effect."
URL = "https://api.elevenlabs.io/v1/sound-generation?output_format=mp3_44100_128"


def generate(client: httpx.Client, prompt: str, dur: float, loop: bool) -> tuple[bytes, int]:
    body = {"text": prompt + SUFFIX, "duration_seconds": max(0.5, dur), "prompt_influence": 0.4,
            "model_id": "eleven_text_to_sound_v3"}
    if loop:
        body["loop"] = True
    for attempt in range(5):
        r = client.post(URL, json=body)
        if r.status_code == 400 and loop and body["model_id"].endswith("v3"):
            body["model_id"] = "eleven_text_to_sound_v2"   # loops may be v2-only
            continue
        if r.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:200]}")
        return r.content, int(r.headers.get("character-cost", "0") or 0)
    raise RuntimeError("rate limited")


def process(raw: Path, dst: Path, spec: dict, loop: bool):
    """Post + QC; if it clips, retry with a lower ceiling (free) before giving up on the take."""
    check = None
    for ceiling in (-2.0, -4.0, -6.0):
        try:
            post(raw, dst, lufs=spec.get("lufs", -18), max_s=spec["dur"] + 0.3, loop=loop, ceiling_db=ceiling)
        except RuntimeError as exc:
            print(f"post-processing failed ({str(exc)[-80:]})")
        check = qc(dst, min(0.08, spec["dur"] * 0.4), spec["dur"] + 1.0)
        if check.ok or not check.reason.startswith("clipping"):
            break
    return check


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--budget", type=int, default=4000, help="stop after this many credits")
    ap.add_argument("--retries", type=int, default=2, help="extra tries per take if QC fails")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cues = json.loads((Path(__file__).parent / "cues.json").read_text())["cues"]
    ids = [c for c in cues if not args.only or c in args.only.split(",")]
    if args.dry_run:
        print(f"{len(ids)} cues, {sum(cues[c]['takes'] for c in ids)} takes, "
              f"{sum(cues[c]['takes'] * cues[c]['dur'] for c in ids):.0f} s of audio")
        return
    spent = 0
    log = []
    RAW.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120) as client:
        for cue in ids:
            spec = cues[cue]
            loop = bool(spec.get("loop"))
            made = len(list(SFX.glob(f"{cue}_[0-9].ogg")))       # resume: keep takes already made
            if made >= spec["takes"]:
                continue
            for attempt in range(spec["takes"] * (1 + args.retries)):
                if made >= spec["takes"]:
                    break
                if spent >= args.budget:
                    print(f"budget reached ({spent} credits)")
                    break
                audio, cost = generate(client, spec["prompt"], spec["dur"], loop)
                spent += cost
                raw = RAW / f"{cue}_{int(time.time() * 1000)}.mp3"
                raw.write_bytes(audio)
                dst = SFX / f"{cue}_{made + 1}.ogg"
                check = process(raw, dst, spec, loop)
                status = "ok" if check.ok else f"rejected: {check.reason}"
                print(f"{cue} take {made + 1}: {check.dur:.2f}s peak {check.peak_db} mean {check.mean_db} "
                      f"cost {cost} -> {status}")
                log.append({"cue": cue, "take": made + 1, "cost": cost, **check.__dict__})
                if check.ok:
                    made += 1
                else:
                    dst.unlink(missing_ok=True)
    (ROOT / "tools" / "sfx" / "last_run.json").write_text(json.dumps({"spent": spent, "log": log}, indent=1))
    print(f"spent {spent} credits; manifest cues: {len(write_manifest(SFX))}")


if __name__ == "__main__":
    main()

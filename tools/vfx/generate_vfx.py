"""Generate VFX concept sheets for Monkey's animations with GPT Image (style exploration, not final assets).

    python -m tools.vfx.generate_vfx [--only sleep,wake] [--quality high]

Uses the current 3D model render as a reference so Monkey stays on-model. Output: prototypes/vfx/<id>.png
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
from pathlib import Path

from monkey.integrations.image_gen import DEFAULT_MODEL, MONKEY_RULES, generate

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "prototypes" / "vfx"
REFS = [OUT / "reference" / "monkey-3d.png", ROOT / "assets" / "monkey.png"]

STYLE = (
    "VFX art direction: chunky, bouncy, comedic cartoon game effects. Flat 3-tone cel shading with hard color steps "
    "(no soft gradients), thick warm dark-brown outlines (#2A1A10) on every effect shape, rounded lobed 'cauliflower' "
    "smoke puffs, teardrop drops, 4- and 5-point stars, spiky impact bursts, tapered speed lines. Effects in warm "
    "cream/yellow/orange/white so they pop against saturated jungle greens; accent cyan #33E1FF. Squash and stretch "
    "on effect shapes, 1930s rubber-hose cartoon energy blended with modern bright mobile-game VFX polish. "
    "Monkey himself must match the reference images exactly (same 3D model, colors, headset, proportions). "
    "Original designs only: no logos, no existing game or franchise characters."
)

SHEETS = {
    "style-board": (
        "A labeled VFX STYLE BOARD on a clean light background, laid out as a grid of effect swatches, with Monkey small "
        "in one corner for scale: (1) lobed smoke/dust puff in 4 dissipating stages, (2) spiky impact burst + 'POW' "
        "shape, (3) chunky 3D extruded 'Z' letters small/medium/large, (4) cyan sweat drops with white highlight, "
        "(5) bold yellow '!' with spiky white burst and a purple '?', (6) lightbulb with ray dashes, (7) gold 4-point "
        "twinkle sparkles, (8) pink hearts and gold stars, (9) concentric shockwave rings, (10) jagged ground crack with "
        "rounded rock chunks, (11) mini banana confetti with paper bits, (12) music notes. Include a palette strip with "
        "hex labels and a small outline-thickness guide. Title: 'MONKEY VFX STYLE'.", "1536x1024"),
    "sleep": (
        "A 4-panel horizontal storyboard of Monkey falling asleep after being idle a long time, each panel labeled with "
        "timing: 1 'YAWN 0.0-1.2s' (huge yawn, arms stretching up, a pale yawn puff), 2 'SIT 1.2-2.4s' (plops down "
        "sitting, small dust puffs), 3 'LIE DOWN 2.4-3.6s' (lies on his back on jungle grass, belly up, one arm behind "
        "his head, headset still on, mic LED dimmed), 4 'SLEEP LOOP' (snoring, chest rising, a cartoon snot bubble, and "
        "three chunky 3D extruded cream 'Z' letters with dark outlines floating up in a sine wave, growing as they "
        "rise). Comedic and cozy.", "1536x1024"),
    "wake": (
        "A 3-panel storyboard of Monkey WAKING UP when the user says 'Hey Monkey', labeled with timing: 1 'STARTLE "
        "0.0-0.15s' (he jolts up mid-air from lying down, eyes wide, a bold yellow '!' with spiky white burst above "
        "his head, 3 radial shock lines, the floating Z letters popping like bubbles), 2 'LAND 0.15-0.5s' (lands on "
        "his feet in a squash pose with tan dust puffs ring), 3 'READY 0.5-1.0s' (sheepish grin, scratches his head, "
        "headset mic LED glowing bright cyan). Squash and stretch, comedic timing.", "1536x1024"),
    "chest-beat": (
        "A 3-keyframe VFX callout of Monkey doing a proud chest beat: anticipation (arms drawn back, chest puffed), "
        "impact (fists on chest, squash pose) with two concentric white-yellow shockwave rings expanding from his chest "
        "and small impact stars, follow-through (rings at max size thinning, a tiny dust ring at his feet, a cocky grin). "
        "Label each frame with timing at 12 fps and the ring scale (0.3x -> 2.5x).", "1536x1024"),
    "ground-slam": (
        "A 3-keyframe VFX callout of Monkey doing a comedic two-fisted GROUND SLAM on jungle dirt: windup (jumps up, "
        "fists together overhead, speed lines), impact frame (fists hit the ground, big spiky white impact flash, "
        "jagged dark star-shaped crack decal, a ring of lobed tan dust puffs, 8 chunky rounded rock and dirt chunks "
        "flying in arcs), aftermath (dust settling, chunks bounced, a few leaves falling, Monkey grinning). Label "
        "timings.", "1536x1024"),
    "celebrate": (
        "Monkey celebrating a finished assignment: arms up in victory, a cone burst of mini banana confetti plus "
        "yellow/green/orange paper bits, gold 4-point twinkle sparkles around him, a few pink hearts, a big glowing "
        "green checkmark badge popping in beside him with a white ring. Include small callouts: 'confetti 2.5s cone up "
        "then flutter', 'sparkles staggered 0.25s each', 'check pop overshoot 1.4x'.", "1536x1024"),
    "thinking": (
        "A sheet of Monkey's THINKING effects in 3 poses: (1) thinking hard, hand on chin, 2 cyan teardrop sweat drops "
        "popping from his temple, (2) puzzled, scratching head with a wobbly purple '?' above, (3) getting an idea, "
        "finger up, yellow lightbulb with flashing ray dashes popping above his head. Label each with timing and the "
        "attach point (temple, head-top).", "1536x1024"),
    "emotions": (
        "A sheet of Monkey's EMOTION effects in 4 poses: (1) ANGRY with lobed white steam puffs bursting from his ears "
        "and a throbbing red cross-popping vein mark on his forehead, (2) LAUGHING hard with cyan tear droplets "
        "squirting sideways from his eyes, (3) DIZZY with 3 small gold stars orbiting his head and a spiral, (4) HAPPY "
        "with pink hearts and gold stars rising. Label each with duration and loop/one-shot.", "1536x1024"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--quality", default="high")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()
    ids = [i for i in SHEETS if not args.only or i in args.only.split(",")]
    refs = [r for r in REFS if r.exists()]

    def run(sid: str):
        prompt, size = SHEETS[sid]
        full = f"{prompt}\n\n{STYLE}\n\nCharacter rules: {MONKEY_RULES}"
        res = generate(full, OUT, refs=refs, size=size, quality=args.quality, model=args.model, name=sid)
        return sid, [str(p.relative_to(ROOT)) for p in res.paths], res.cost_usd

    total = 0.0
    index = {}
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for sid, paths, cost in ex.map(run, ids):
            total += cost
            index[sid] = {"paths": paths, "prompt": SHEETS[sid][0]}
            print(sid, paths, f"${cost:.3f}")
    idx_file = OUT / "index.json"
    old = json.loads(idx_file.read_text()) if idx_file.exists() else {}
    idx_file.write_text(json.dumps({**old, **index}, indent=1))
    print(f"total ${total:.2f}")


if __name__ == "__main__":
    main()

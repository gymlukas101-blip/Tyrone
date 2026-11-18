"""Generate Monkey design prototypes with GPT Image 2.6 Sunburst.

For each art direction in prototypes/directions.json:
  1. hero.png  - the character in a jungle scene, using the current 3D render as reference
  2. sheet.png - a front / side / back A-pose model sheet for Blender, using hero.png as reference
Writes brief.md per prototype and prototypes/index.json.

Usage:  python tools/prototypes/generate.py [--only 03,05] [--quality high] [--ref path.png]
Needs OPENAI_API_KEY, or a proxy that injects it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from monkey.integrations.image_gen import DEFAULT_MODEL, MONKEY_RULES, generate  # noqa: E402

OUT = ROOT / "prototypes"

HERO = ("Hero illustration: {scene} Polished stylized 3D render, soft fur shading, warm key light and a cyan rim "
        "light, vivid saturated jungle background with bananas and big leaves, full body visible, centered.")
SHEET = ("Character model sheet of EXACTLY this same character for a 3D modeler: three full-body views side by side "
         "- FRONT, SIDE (profile facing right) and BACK - in a relaxed A-pose (arms angled down about 45 degrees, "
         "hands open), neutral expression with mouth closed, identical proportions, colors and outfit in every "
         "view, orthographic look, even flat studio lighting, plain light grey background, no scenery, no text "
         "other than the small labels FRONT, SIDE, BACK under each view.")


def run_one(d: dict, ref: Path, quality: str, model: str) -> dict:
    folder = OUT / f"{d['id']}-{d['slug']}"
    folder.mkdir(parents=True, exist_ok=True)
    hero_prompt = f"{MONKEY_RULES}\n\nArt direction - {d['title']}: {d['direction']}\n\n" + HERO.format(scene=d["scene"])
    hero = generate(hero_prompt, folder, refs=[ref], size="1024x1536", quality=quality, model=model, name="hero",
                    api_key=os.environ.get("OPENAI_API_KEY"))
    sheet_prompt = f"{SHEET}\n\nKeep every design detail from the reference: {d['direction']}"
    sheet = generate(sheet_prompt, folder, refs=[hero.paths[0]], size="1536x1024", quality=quality, model=model,
                     name="sheet", api_key=os.environ.get("OPENAI_API_KEY"))
    cost = round(hero.cost_usd + sheet.cost_usd, 3)
    (folder / "brief.md").write_text(
        f"# {d['id']} - {d['title']}\n\n{d['direction']}\n\n"
        f"**Borrowed generic traits:** {d.get('traits', '')}\n\n"
        f"## Hero prompt\n\n```\n{hero_prompt}\n```\n\n## Model-sheet prompt\n\n```\n{sheet_prompt}\n```\n\n"
        f"Model: `{model}`, quality `{quality}`. Estimated cost ${cost} "
        f"({hero.seconds + sheet.seconds:.0f}s).\n", encoding="utf-8")
    print(f"done {d['id']} {d['title']} ${cost}", flush=True)
    return {**d, "folder": folder.name, "hero": f"{folder.name}/hero.png", "sheet": f"{folder.name}/sheet.png",
            "cost_usd": cost, "model": model}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--quality", default="high")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--ref", default=str(OUT / "reference" / "current-3d.png"))
    a = ap.parse_args()
    directions = json.loads((OUT / "directions.json").read_text(encoding="utf-8"))
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    todo = [d for d in directions if not only or d["id"] in only]
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda d: run_one(d, Path(a.ref), a.quality, a.model), todo))
    index_path = OUT / "index.json"
    index = {e["id"]: e for e in (json.loads(index_path.read_text()) if index_path.exists() else [])}
    for r in results:
        index[r["id"]] = r
    index_path.write_text(json.dumps(sorted(index.values(), key=lambda e: e["id"]), indent=2), encoding="utf-8")
    print("total $", round(sum(r["cost_usd"] for r in results), 2))


if __name__ == "__main__":
    main()

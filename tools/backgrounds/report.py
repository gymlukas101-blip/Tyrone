"""Markdown tables for README.md from the build manifests and the glb check (no Blender needed).

    python tools/backgrounds/report.py character_v2_workspace/backgrounds > /tmp/tables.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_glb import check  # noqa: E402


ORDER = ["sunny_clearing", "treehouse_sunset", "waterfall_lagoon", "night_jungle"]


def _order(p: Path):
    return (ORDER.index(p.name) if p.name in ORDER else len(ORDER), p.name)


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "character_v2_workspace/backgrounds")
    scenes = []
    for d in sorted((p for p in root.iterdir() if (p / "manifest.json").exists()), key=_order):
        m = json.loads((d / "manifest.json").read_text())
        g = check(d / f"{d.name}.glb")
        scenes.append((d, m, g))
    print("| Scene | Assets (animated) | Triangles | Draw calls | Bones | Scene .glb | Still (1080x1800) | Video frame (540x900) |")
    print("|---|---|---|---|---|---|---|---|")
    for d, m, g in scenes:
        t = m.get("times", {})
        anim = sum(a["anim"] != "static" for a in m["assets"])
        print(f"| {m['title']} | {len(m['assets'])} ({anim}) | {g['tris']:,} | {g['draw_calls']} | {g['joints']} | "
              f"{g['bytes'] / 1e6:.2f} MB | {t.get('still_s', '?')} s @ {t.get('still_samples', '?')} spp | "
              f"{t.get('video_s_per_frame', '?')} s @ {t.get('video_samples', '?')} spp |")
    for d, m, g in scenes:
        print(f"\n#### {m['title']} (`{d.name}`)\n\n{m['blurb']}\n")
        print("| Asset | Animation (4 s loop) | Tris | Rig | .glb |")
        print("|---|---|---|---|---|")
        for a in m["assets"]:
            rig = f"{a['bones']} bones" if a.get("bones") else (f"{a['shape_keys']} shape keys" if a.get("shape_keys") else "-")
            print(f"| {a['name']} | {a['anim']} | {a.get('tris', 0):,} | {rig} | {a.get('glb_bytes', 0) / 1024:.0f} KB |")


if __name__ == "__main__":
    main()

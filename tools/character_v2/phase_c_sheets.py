"""Compose Phase C evidence sheets from phase_c_evidence.py renders (numpy + PIL, no Blender).

    python tools/character_v2/phase_c_sheets.py EVIDENCE_DIR

Writes EVIDENCE_DIR/sheet_poses_C1.png (pose x view), sheet_poses_vs_B2.png (pose: B2 | C1, 3/4 view),
sheet_elbow_corrective.png and sheet_brows.png.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

BG = (24, 26, 28)
FG = (235, 235, 235)


def label(im, text):
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, im.width, 18), fill=(0, 0, 0))
    d.text((5, 3), text, fill=FG)
    return im


def grid(rows, cols, cell, tiles, title):
    w, h = cell
    out = Image.new("RGB", (cols * w, rows * h + 26), BG)
    ImageDraw.Draw(out).text((8, 7), title, fill=FG)
    for (r, c), im in tiles.items():
        out.paste(im.resize((w, h)), (c * w, 26 + r * h))
    return out


def main(d: Path):
    meta = json.loads((d / "renders.json").read_text())
    poses = meta["poses"]
    tiles = {}
    for r, p in enumerate(poses):
        for c, az in enumerate((0, 45, 90)):
            tiles[(r, c)] = label(Image.open(d / f"C1_{p}_az{az}.png").convert("RGB"), f"C1 {p}  az{az}")
    # two columns of poses to keep the sheet compact
    half = (len(poses) + 1) // 2
    t2 = {}
    for (r, c), im in tiles.items():
        t2[(r % half, c + 3 * (r // half))] = im
    grid(half, 6, (300, 300), t2, "Phase C1 pose library (left arm/hand), front / 3-4 / side").save(d / "sheet_poses_C1.png")
    tv = {}
    for i, p in enumerate(poses):
        r, c = i // 3, (i % 3) * 2
        tv[(r, c)] = label(Image.open(d / f"B2_{p}_az45.png").convert("RGB"), f"B2 {p}")
        tv[(r, c + 1)] = label(Image.open(d / f"C1_{p}_az45.png").convert("RGB"), f"C1 {p}")
    grid(3, 6, (300, 300), tv, "Same poses: B2 (Tripo mitten + auto weights) vs C1 (articulated hand, underlay, rigid clumps), 3/4 view"
         ).save(d / "sheet_poses_vs_B2.png")
    te = {}
    for c, az in enumerate((0, 45, 90)):
        te[(0, c)] = label(Image.open(d / f"B2_elbow_120_az{az}.png").convert("RGB"), f"B2 elbow 120  az{az}")
        te[(1, c)] = label(Image.open(d / f"C1_elbow_120_corr0_az{az}.png").convert("RGB"), f"C1 elbow 120, corrective off")
        te[(2, c)] = label(Image.open(d / f"C1_elbow_120_corr1_az{az}.png").convert("RGB"), f"C1 elbow 120, elbowBend_L = 1")
    grid(3, 3, (360, 360), te, "Elbow at 120 deg: B2 vs C1 without / with the elbowBend_L corrective").save(d / "sheet_elbow_corrective.png")
    tb = {}
    for i, b in enumerate(meta["brows"]):
        safe = b.split(" (")[0].replace(" ", "_")
        tb[(i // 4, i % 4)] = label(Image.open(d / f"brow_{safe}.png").convert("RGB"), b)
    grid(2, 4, (380, 300), tb, "Brows: new per-side morphs + brow bones (combinations the app's acting can now make)").save(d / "sheet_brows.png")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

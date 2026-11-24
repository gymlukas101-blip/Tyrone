"""Compose one review sheet per clip batch from clip_sheet.py renders: a row per clip (5 frames), in one view.

    python tools/character_v2/batch_sheet.py SHEETS_DIR OUT.png [--view three_quarter] [--cell 240]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def main(d: Path, out: Path, view: str, cell: int):
    clips = sorted(p for p in d.iterdir() if p.is_dir())
    rows = []
    for c in clips:
        frames = sorted(c.glob(f"{view}_f*.png"))
        if frames:
            rows.append((c.name, frames))
    n = max(len(f) for _, f in rows)
    sheet = Image.new("RGB", (cell * n + 170, cell * len(rows)), (24, 26, 28))
    dr = ImageDraw.Draw(sheet)
    for r, (name, frames) in enumerate(rows):
        dr.text((8, r * cell + cell // 2 - 6), name, fill=(235, 235, 235))
        for k, f in enumerate(frames):
            im = Image.open(f).convert("RGB").resize((cell, cell))
            ImageDraw.Draw(im).text((4, 4), f.stem.split("_")[-1], fill=(255, 255, 255))
            sheet.paste(im, (170 + k * cell, r * cell))
    sheet.save(out)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    view = a[a.index("--view") + 1] if "--view" in a else "three_quarter"
    cell = int(a[a.index("--cell") + 1]) if "--cell" in a else 240
    print(main(Path(a[0]), Path(a[1]), view, cell))

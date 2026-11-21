"""Side-by-side review sheets from render_views.py output folders (identical framing, so columns line up).

    python tools/character_v2/sheet.py OUT.png --views front,three_quarter,side --mode clay DIR1:Label1 DIR2:Label2 ...

Rows are the given folders (baseline, candidates), columns the views. Pillow only.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def font(n):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", n)
    except OSError:
        return ImageFont.load_default()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("rows", nargs="+", help="DIR:Label")
    ap.add_argument("--views", default="front,three_quarter,side,back")
    ap.add_argument("--mode", default="clay")
    ap.add_argument("--cell", type=int, default=360)
    a = ap.parse_args()
    views = a.views.split(",")
    c = a.cell
    head, label_w = 30, 150
    sheet = Image.new("RGB", (label_w + c * len(views), head + c * len(a.rows)), (18, 30, 22))
    d = ImageDraw.Draw(sheet)
    for j, v in enumerate(views):
        d.text((label_w + j * c + 8, 6), f"{v} ({a.mode})", fill=(255, 230, 140), font=font(16))
    for i, row in enumerate(a.rows):
        folder, _, label = row.partition(":")
        d.text((8, head + i * c + c // 2 - 10), label or Path(folder).name, fill=(235, 245, 235), font=font(16))
        for j, v in enumerate(views):
            p = Path(folder) / f"{v}_{a.mode}.png"
            if p.exists():
                sheet.paste(Image.open(p).convert("RGB").resize((c, c), Image.LANCZOS), (label_w + j * c, head + i * c))
    sheet.save(a.out)
    print(a.out, sheet.size)


if __name__ == "__main__":
    main()

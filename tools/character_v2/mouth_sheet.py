"""Before/after mouth sheet from two mouth_poses.py runs (plain Python + Pillow, no Blender).

    python tools/character_v2/mouth_sheet.py BEFORE_DIR AFTER_DIR OUT.png [--crop] [--scale 0.6]

Rows: before front, after front, before 3/4, after 3/4; columns: the 12 sheet poses. Each tile is labelled with the
pose and, for the after rows, the hole count from the magenta test (must be 0) and the visible-interior pixels.
--crop keeps the mouth half of each render.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

POSES = ["neutral", "jawOpen", "aa", "O", "E", "PP", "TH", "bigGrin", "laugh", "tongueOut", "smile_aa", "surprised"]
LABEL = {"smile_aa": "smile + aa", "laugh": "laugh (app mix)", "surprised": "surprised (O + wide eyes)"}


def font(n):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, n)
    return ImageFont.load_default()


def main(before: Path, after: Path, out: Path, crop: bool, scale: float = 1.0) -> None:
    jb = json.loads((before / "poses.json").read_text())
    ja = json.loads((after / "poses.json").read_text())
    sample = Image.open(after / f"{POSES[0]}_front.png")
    w, h = sample.size
    box = (0, int(h * 0.30), w, int(h * 0.92)) if crop else (0, 0, w, h)
    tw, th = int((box[2] - box[0]) * scale), int((box[3] - box[1]) * scale)
    head, side = 26, 120
    rows = [("before (E7)", before, "front", jb), ("after (M1)", after, "front", ja),
            ("before, 3/4", before, "three_quarter", jb), ("after, 3/4", after, "three_quarter", ja)]
    sheet = Image.new("RGB", (side + tw * len(POSES), (th + head) * len(rows)), (24, 26, 28))
    d = ImageDraw.Draw(sheet)
    f, fs = font(15), font(12)
    for r, (name, folder, view, js) in enumerate(rows):
        y = r * (th + head)
        d.text((8, y + head + th // 2 - 10), name, fill=(240, 220, 150), font=f)
        for c, p in enumerate(POSES):
            x = side + c * tw
            im = Image.open(folder / f"{p}_{view}.png").convert("RGB").crop(box)
            if scale != 1.0:
                im = im.resize((tw, th), Image.LANCZOS)
            sheet.paste(im, (x, y + head))
            st = js[p][view]
            tag = f"{LABEL.get(p, p)}   holes {st['holes']}  mouth px {st['interior_px']}"
            d.text((x + 4, y + 6), tag, fill=(255, 255, 255) if st["holes"] == 0 else (255, 80, 80), font=fs)
    sheet.save(out)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(Path(a[0]), Path(a[1]), Path(a[2]), "--crop" in a, float(a[a.index("--scale") + 1]) if "--scale" in a else 1.0)

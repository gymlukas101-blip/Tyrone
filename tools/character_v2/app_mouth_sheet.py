"""App mouth sheet: the face close-ups of threejs_face_check.py runs, before and after, side by side (Pillow only).

    python tools/character_v2/app_mouth_sheet.py BEFORE_DIR AFTER_DIR OUT.png

Each tile is the face area of `face_<step>.png` (the app's camera follows the head, so a tight fixed crop would miss the
mouth while idle clips move it); the after rows carry the morph weights read back from the live meshes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

STEPS = ["neutral", "speak_aa", "speak_PP", "speak_O", "speak_E", "speak_FF", "smile_aa", "jaw_open", "big_grin",
         "laugh", "tongue_out", "mouth_O", "surprised", "happy"]
KEYS = ("viseme_aa", "viseme_PP", "viseme_O", "viseme_E", "viseme_FF", "jawOpen", "bigGrin", "tongueOut", "mouthO",
        "smile", "cheeksUp")
BOX, SCALE, COLS = (20, 190, 360, 640), 0.62, 7


def main(before: Path, after: Path, out: Path) -> None:
    fp = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    f, fs = ImageFont.truetype(fp, 13), ImageFont.truetype(fp, 10)
    ra = json.loads((after / "threejs_report.json").read_text())["steps"]
    tw, th = int((BOX[2] - BOX[0]) * SCALE), int((BOX[3] - BOX[1]) * SCALE)
    head = 34
    blocks = (len(STEPS) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * tw, blocks * 2 * (th + head)), (20, 24, 22))
    d = ImageDraw.Draw(sheet)
    for k, s in enumerate(STEPS):
        for r, (lab, folder) in enumerate((("before (E7)", before), ("after (M1)", after))):
            x, y = (k % COLS) * tw, ((k // COLS) * 2 + r) * (th + head)
            im = Image.open(folder / f"face_{s}.png").convert("RGB").crop(BOX).resize((tw, th), Image.LANCZOS)
            sheet.paste(im, (x, y + head))
            d.text((x + 4, y + 2), f"{s}: {lab}", fill=(255, 230, 150) if r else (190, 190, 190), font=f)
            if r:
                w = ", ".join(f"{n} {v:.2f}" for n, v in ra[s].items() if n in KEYS)
                d.text((x + 4, y + 18), w[:46], fill=(200, 230, 200), font=fs)
    sheet.save(out)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))

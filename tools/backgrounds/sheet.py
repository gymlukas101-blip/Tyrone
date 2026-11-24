"""Silhouette versions of each still and a contact sheet of all scenes (Pillow; no Blender needed).

    python tools/backgrounds/sheet.py character_v2_workspace/backgrounds

For each <scene>/ with <scene>_still.png and <scene>_monkey_mask.png (the real avatar, idle pose, rendered from the
same camera by build.py) writes <scene>_still_monkey.png, then <out>/contact_sheet.png.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

INK = (4, 38, 15)
BANANA = (255, 214, 10)


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def silhouette(still: Path, mask: Path, out: Path) -> Image.Image:
    im = Image.open(still).convert("RGBA")
    a = Image.open(mask).convert("RGBA").split()[3].resize(im.size)
    fill = Image.new("RGBA", im.size, (20, 16, 40, 0))
    fill.putalpha(a.point(lambda v: int(v * 0.62)))
    grown = a.filter(ImageFilter.MaxFilter(9))
    ring = ImageChops.subtract(grown, a)
    edge = Image.new("RGBA", im.size, (*BANANA, 0))
    edge.putalpha(ring)
    im = Image.alpha_composite(Image.alpha_composite(im, fill), edge)
    im.convert("RGB").save(out)
    return im


ORDER = ["sunny_clearing", "treehouse_sunset", "waterfall_lagoon", "night_jungle"]


def _order(p: Path):
    return (ORDER.index(p.name) if p.name in ORDER else len(ORDER), p.name)


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "character_v2_workspace/backgrounds")
    cols = []
    for d in sorted((p for p in root.iterdir() if p.is_dir()), key=_order):
        man, still, mask = d / "manifest.json", d / f"{d.name}_still.png", d / f"{d.name}_monkey_mask.png"
        if not (man.exists() and still.exists() and mask.exists()):
            continue
        m = json.loads(man.read_text())
        sil = silhouette(still, mask, d / f"{d.name}_still_monkey.png")
        cols.append((m, Image.open(still).convert("RGB"), sil.convert("RGB")))
        print("wrote", d / f"{d.name}_still_monkey.png")
    if not cols:
        print("nothing to do")
        return
    tw, th, pad, head, foot = 432, 720, 24, 70, 96
    W = pad + len(cols) * (tw + pad)
    H = head + 2 * th + pad * 3 + foot
    sheet = Image.new("RGB", (W, H), INK)
    dr = ImageDraw.Draw(sheet)
    dr.text((pad, 18), "Monkey: toy-block background concepts (top: still, bottom: Monkey's spot)", fill=BANANA,
            font=font(30))
    for i, (m, still, sil) in enumerate(cols):
        x = pad + i * (tw + pad)
        sheet.paste(still.resize((tw, th), Image.LANCZOS), (x, head))
        sheet.paste(sil.resize((tw, th), Image.LANCZOS), (x, head + th + pad))
        y = head + 2 * th + pad * 2
        t = m.get("times", {})
        lines = [m["title"],
                 f"{m['tris']:,} tris  |  glb {m['glb_bytes'] / 1e6:.2f} MB  |  {len(m['assets'])} assets",
                 f"still {t.get('still_s', '?')} s  |  video {t.get('video_s_per_frame', '?')} s/frame"]
        dr.text((x, y), lines[0], fill=(246, 255, 233), font=font(24))
        dr.text((x, y + 34), lines[1], fill=(181, 227, 168), font=font(18))
        dr.text((x, y + 60), lines[2], fill=(181, 227, 168), font=font(18))
    out = root / "contact_sheet.png"
    sheet.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()

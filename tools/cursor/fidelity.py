"""Reference-fidelity pipeline for the banana cursor (numpy + Pillow only).

    # 1. isolate the cursor art from the owner's concept sheet (never committed: it has a third-party wordmark)
    python -m tools.cursor.fidelity extract REFERENCE.png
    # 2. compare what Monkey actually renders (runtime screenshots) against the isolated reference
    python -m tools.cursor.fidelity compare REFERENCE.png
    # 3. validate the pipeline itself on a synthetic sheet (no reference needed)
    python -m tools.cursor.fidelity selftest

extract  → monkey/automation/cursor/ref/{default,hover,click,busy,hero}.png (transparent, original pixels kept;
           edge pixels are colour-decontaminated so there's no dark fringe), effect layers (hover/click/busy minus
           default, aligned on the hotspot), and ref/analysis.json (bboxes, hotspots, palette per region).
compare  → docs/cursor/fidelity/*.png side-by-side, overlay and difference sheets at 32/48/64/96/128 px on dark and
           light backgrounds, plus fidelity.json with silhouette IoU and SSIM. Scores support judgement; they don't
           replace it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
CURSOR = ROOT / "monkey/automation/cursor"
OUT_REF = CURSOR / "ref"
OUT_DOC = ROOT / "docs/cursor/fidelity"

# Search windows on the 1536×1024 concept sheet (scaled if the sheet is another size). The cursor is found inside
# each window by its mask; labels sit below these windows and are never included.
WINDOWS = {"hero": (60, 40, 720, 920), "default": (800, 60, 1080, 360), "hover": (1160, 60, 1480, 370),
           "click": (770, 490, 1100, 810), "busy": (1170, 490, 1480, 810)}
SIZES = (32, 48, 64, 96, 128)


# ------------------------------------------------------------------------------------------------ masking
def hsv(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rgb = arr[..., :3].astype(np.float32) / 255
    mx, mn = rgb.max(-1), rgb.min(-1)
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    d = np.maximum(mx - mn, 1e-6)
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) / 6
    return h, s, mx


def art_mask(arr: np.ndarray) -> np.ndarray:
    """Cursor pixels vs the dark, grey, low-saturation background: saturated (yellow, brown) or bright (cream)."""
    h, s, v = hsv(arr)
    m = ((s > 0.28) & (v > 0.16)) | (v > 0.62)
    return m


def largest_component(m: np.ndarray, extra_near: int = 0) -> np.ndarray:
    """Keep the biggest 8-connected blob (the cursor), plus blobs within `extra_near` px of it (rays, rings)."""
    h, w = m.shape
    lab = np.zeros((h, w), np.int32)
    sizes = [0]
    cur = 0
    ys, xs = np.nonzero(m)
    for y0, x0 in zip(ys, xs):
        if lab[y0, x0]:
            continue
        cur += 1
        stack = [(y0, x0)]
        lab[y0, x0] = cur
        n = 0
        while stack:
            y, x = stack.pop()
            n += 1
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < h and 0 <= xx < w and m[yy, xx] and not lab[yy, xx]:
                        lab[yy, xx] = cur
                        stack.append((yy, xx))
        sizes.append(n)
    if cur == 0:
        return m
    big = int(np.argmax(sizes))
    keep = lab == big
    if extra_near:
        grown = np.array(Image.fromarray(keep.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(2 * extra_near + 1))) > 0
        for i in range(1, cur + 1):
            if i != big and sizes[i] > 12 and (grown & (lab == i)).any():
                keep |= lab == i
    return keep


def fill_holes(m: np.ndarray) -> np.ndarray:
    """Interior pixels the colour test missed (dark facets) become part of the object."""
    h, w = m.shape
    outside = np.zeros((h + 2, w + 2), bool)
    free = np.pad(~m, 1, constant_values=True)
    stack = [(0, 0)]
    outside[0, 0] = True
    while stack:
        y, x = stack.pop()
        for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= yy < h + 2 and 0 <= xx < w + 2 and free[yy, xx] and not outside[yy, xx]:
                outside[yy, xx] = True
                stack.append((yy, xx))
    return ~outside[1:-1, 1:-1]


def decontaminated_rgba(arr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Alpha with a 1.5 px anti-aliased edge whose colour comes from the nearest *interior* pixel, so edges carry no
    dark background (no black fringe on light pages). Interior pixels are the original pixels, untouched."""
    m8 = Image.fromarray(mask.astype(np.uint8) * 255)
    core = np.array(m8.filter(ImageFilter.MinFilter(3))) > 0
    alpha = np.array(m8.filter(ImageFilter.GaussianBlur(0.75))).astype(np.float32) / 255
    alpha = np.where(core, 1.0, np.where(mask, np.maximum(alpha, 0.5), alpha * 0.6))
    rgb = arr[..., :3].astype(np.float32).copy()
    # push interior colour outward 3 px into the edge ring (nearest-interior colour, no background)
    filled = np.where(core[..., None], rgb, 0)
    have = core.copy()
    for _ in range(3):
        acc = np.zeros_like(rgb)
        cnt = np.zeros(have.shape, np.float32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                acc += np.roll(np.roll(filled * have[..., None], dy, 0), dx, 1)
                cnt += np.roll(np.roll(have.astype(np.float32), dy, 0), dx, 1)
        new = (~have) & (cnt > 0)
        filled = np.where(new[..., None], acc / np.maximum(cnt, 1)[..., None], filled)
        have |= new
    out = np.dstack([np.where(core[..., None], rgb, filled), alpha * 255]).clip(0, 255).astype(np.uint8)
    return out


def hotspot(rgba: np.ndarray, thresh: int = 128) -> tuple[int, int]:
    """The pointer tip: the opaque pixel furthest toward the top-left (min x + y)."""
    ys, xs = np.nonzero(rgba[..., 3] >= thresh)
    i = int(np.argmin(xs + ys))
    return int(xs[i]), int(ys[i])


def isolate(sheet: Image.Image, name: str, with_fx: bool) -> tuple[np.ndarray, dict]:
    W, H = sheet.size
    kx, ky = W / 1536, H / 1024
    x0, y0, x1, y1 = WINDOWS[name]
    box = (int(x0 * kx), int(y0 * ky), int(x1 * kx), int(y1 * ky))
    arr = np.array(sheet.convert("RGB").crop(box))
    m = art_mask(arr)
    m = largest_component(m, extra_near=40 if with_fx else 0)
    m = fill_holes(m) if not with_fx else (m | fill_holes(largest_component(m)))
    ys, xs = np.nonzero(m)
    by0, by1, bx0, bx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    pad = 3
    sub_arr = np.pad(arr[by0:by1, bx0:bx1], ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    sub_m = np.pad(m[by0:by1, bx0:bx1], pad)
    rgba = decontaminated_rgba(sub_arr, sub_m)
    hx, hy = hotspot(rgba)
    return rgba, {"sheet_bbox": [box[0] + int(bx0) - pad, box[1] + int(by0) - pad, box[0] + int(bx1) + pad,
                                 box[1] + int(by1) + pad], "size": [rgba.shape[1], rgba.shape[0]], "hotspot": [hx, hy]}


def palette(rgba: np.ndarray) -> dict:
    h, s, v = hsv(rgba)
    a = rgba[..., 3] > 200
    regions = {"cream": a & (s < 0.35) & (v > 0.75), "yellow": a & (s >= 0.55) & (v > 0.7) & (h < 0.17),
               "brown": a & (v < 0.5) & (s > 0.3)}
    out = {}
    for k, r in regions.items():
        if r.sum():
            c = np.median(rgba[r][:, :3], axis=0).astype(int)
            out[k] = {"hex": "#%02x%02x%02x" % tuple(c), "share": round(float(r.sum() / a.sum()), 3)}
    return out


def cmd_extract(ref: Path) -> dict:
    sheet = Image.open(ref)
    OUT_REF.mkdir(parents=True, exist_ok=True)
    info = {"source": ref.name, "sheet_size": list(sheet.size), "states": {}}
    imgs = {}
    for name in WINDOWS:
        rgba, meta = isolate(sheet, name, with_fx=name in ("hover", "click", "busy", "hero"))
        Image.fromarray(rgba).save(OUT_REF / f"{name}.png")
        meta["palette"] = palette(rgba)
        info["states"][name] = meta
        imgs[name] = (rgba, meta)
    # effect layers: state minus default, aligned on the hotspot (what the effect adds around the same banana)
    d, dm = imgs["default"]
    for name in ("hover", "click", "busy"):
        s, sm = imgs[name]
        ox, oy = sm["hotspot"][0] - dm["hotspot"][0], sm["hotspot"][1] - dm["hotspot"][1]
        canvas = np.zeros_like(s)
        hh, ww = d.shape[:2]
        ys, xs = slice(max(oy, 0), max(oy, 0) + hh), slice(max(ox, 0), max(ox, 0) + ww)
        region = canvas[ys, xs]
        region[...] = d[: region.shape[0], : region.shape[1]]
        fx = s.copy()
        cover = canvas[..., 3] > 128
        fx[..., 3] = np.where(cover & (np.abs(s[..., :3].astype(int) - canvas[..., :3].astype(int)).sum(-1) < 60), 0,
                              s[..., 3])
        Image.fromarray(fx).save(OUT_REF / f"fx_{name}.png")
    (OUT_REF / "analysis.json").write_text(json.dumps(info, indent=2))
    return info


# ------------------------------------------------------------------------------------------------ comparison
def _gauss(a: np.ndarray, sigma: float = 1.5) -> np.ndarray:
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    a = np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, "valid"), 0, a)
    return np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, "valid"), 1, a)


def ssim(x: np.ndarray, y: np.ndarray, mask: np.ndarray) -> float:
    x, y = x.astype(np.float64), y.astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mx, my = _gauss(x), _gauss(y)
    vx, vy, cxy = _gauss(x * x) - mx * mx, _gauss(y * y) - my * my, _gauss(x * y) - mx * my
    s = ((2 * mx * my + c1) * (2 * cxy + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2))
    return float(s[mask].mean()) if mask.any() else 0.0


def normalize(rgba: Image.Image, height: int) -> tuple[Image.Image, tuple[int, int]]:
    """Scale to a silhouette height, then report the hotspot (for alignment)."""
    a = np.array(rgba)
    ys, xs = np.nonzero(a[..., 3] > 20)
    crop = rgba.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    k = height / crop.height
    out = crop.resize((max(1, round(crop.width * k)), height), Image.LANCZOS)
    return out, hotspot(np.array(out))


def align_pair(ref: Image.Image, ours: Image.Image, height: int) -> tuple[np.ndarray, np.ndarray]:
    r, rh = normalize(ref, height)
    o, oh = normalize(ours, height)
    W, H = max(r.width, o.width) + 8, height + 8
    cr, co = Image.new("RGBA", (W, H)), Image.new("RGBA", (W, H))
    cr.paste(r, (4, 4))
    co.paste(o, (4 + rh[0] - oh[0], 4 + rh[1] - oh[1]))          # hotspots on top of each other
    return np.array(cr), np.array(co)


def metrics(r: np.ndarray, o: np.ndarray) -> dict:
    ra, oa = r[..., 3] > 127, o[..., 3] > 127
    iou = float((ra & oa).sum() / max(1, (ra | oa).sum()))
    lum = lambda a: 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]  # noqa: E731
    both = ra & oa
    col = float(np.abs(r[..., :3].astype(int) - o[..., :3].astype(int))[both].mean()) if both.any() else 255.0
    return {"silhouette_iou": round(iou, 3), "ssim_luma": round(ssim(lum(r), lum(o), both), 3),
            "mean_rgb_error": round(col, 1)}


def sheet_row(r: np.ndarray, o: np.ndarray, bg: tuple[int, int, int]) -> Image.Image:
    def on(a):
        im = Image.new("RGB", (a.shape[1], a.shape[0]), bg)
        im.paste(Image.fromarray(a), (0, 0), Image.fromarray(a))
        return im
    ov = np.zeros_like(r)
    ra, oa = r[..., 3] > 127, o[..., 3] > 127
    ov[ra & ~oa] = (255, 60, 60, 255)            # only in the reference (missing in ours)
    ov[oa & ~ra] = (60, 200, 255, 255)           # only in ours (extra)
    ov[ra & oa] = (210, 210, 210, 255)
    diff = np.abs(r[..., :3].astype(int) - o[..., :3].astype(int)).sum(-1)
    dif = np.zeros_like(r)
    dif[..., 0] = np.clip(diff, 0, 255)
    dif[..., 1] = np.clip(diff // 3, 0, 255)
    dif[..., 3] = np.where(ra | oa, 255, 0)
    tiles = [on(r), on(o), on(ov), on(dif)]
    w, h = tiles[0].size
    row = Image.new("RGB", (w * 4 + 30, h), bg)
    for i, t in enumerate(tiles):
        row.paste(t, (i * (w + 10), 0))
    return row


def render_runtime(states=("default", "hover", "click", "busy"), px: int = 256) -> dict[str, Image.Image]:
    """Screenshots from the real runtime controller (banana_cursor.js), not from an art tool."""
    import subprocess
    import tempfile

    out = Path(tempfile.mkdtemp(prefix="cursor-rt-"))
    js = ROOT / "tools/cursor/render_states.js"
    subprocess.run(["node", str(js), str(out), str(px)], check=True, cwd=ROOT)
    return {s: Image.open(out / f"{s}.png").convert("RGBA") for s in states}


def cmd_compare(ref_dir: Path = OUT_REF) -> dict:
    OUT_DOC.mkdir(parents=True, exist_ok=True)
    ours = render_runtime()
    report = {}
    for state in ("default", "hover", "click", "busy"):
        ref = Image.open(ref_dir / f"{state}.png").convert("RGBA")
        rows, report[state] = [], {}
        for px in SIZES:
            r, o = align_pair(ref, ours[state], px)
            report[state][px] = metrics(r, o)
            rows += [sheet_row(r, o, (32, 35, 40)), sheet_row(r, o, (240, 240, 236))]
        r, o = align_pair(ref, ours[state], 384)
        big = [sheet_row(r, o, (32, 35, 40))]
        Wd = max(im.width for im in rows + big)
        Ht = sum(im.height + 8 for im in rows + big) + 30
        page = Image.new("RGB", (Wd, Ht), (20, 22, 26))
        d = ImageDraw.Draw(page)
        d.text((6, 6), f"{state.upper()}: reference | Monkey runtime | overlay (red = missing, blue = extra) | difference",
               fill=(255, 214, 10))
        y = 30
        for im in big + rows:
            page.paste(im, (0, y))
            y += im.height + 8
        page.save(OUT_DOC / f"{state}.png")
    (OUT_DOC / "fidelity.json").write_text(json.dumps(report, indent=2))
    return report


def cmd_selftest() -> dict:
    """Validate extraction + comparison on a synthetic sheet built from the runtime render on a textured dark board."""
    ours = render_runtime(px=190)
    rng = np.random.default_rng(1)
    bg = np.full((1024, 1536, 3), 30, np.uint8)
    for _ in range(300):                                    # the reference's blurry grey squares
        x, y, s = rng.integers(0, 1536), rng.integers(0, 1024), rng.integers(20, 70)
        bg[y:y + s, x:x + s] = rng.integers(26, 62)
    sheet = Image.fromarray(bg)
    places = {"default": (840, 90), "hover": (1205, 90), "click": (820, 530), "busy": (1210, 530), "hero": (100, 80)}
    for name, (x, y) in places.items():
        im = ours["hover" if name == "hero" else name]
        if name == "hero":
            im = im.resize((560, 560), Image.LANCZOS)
        sheet.paste(im, (x, y), im)
    tmp = OUT_REF.parent / "_selftest_sheet.png"
    sheet.save(tmp)
    try:
        info = cmd_extract(tmp)
        r, o = align_pair(Image.open(OUT_REF / "default.png"), ours["default"], 128)
        m = metrics(r, o)
    finally:
        tmp.unlink(missing_ok=True)
        import shutil

        shutil.rmtree(OUT_REF, ignore_errors=True)        # synthetic: never mistaken for the reference
    return {"extracted": {k: v["size"] for k, v in info["states"].items()}, "roundtrip_default_128": m}


def cmd_promote() -> dict:
    """After the owner approves ref/default.png: make it the base asset every state is drawn from."""
    src = OUT_REF / "default.png"
    im = Image.open(src).convert("RGBA")
    dst = CURSOR / "banana_sprite.png"
    im.save(dst, optimize=True)
    hx, hy = hotspot(np.array(im))
    man_p = CURSOR / "manifest.json"
    man = json.loads(man_p.read_text())
    man["sprite"] = {"file": dst.name, "width": im.width, "height": im.height, "hotspot": [hx, hy],
                     "source": "isolated from the owner's concept sheet (DEFAULT state), original pixels"}
    man_p.write_text(json.dumps(man, indent=2) + "\n")
    return man["sprite"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("extract", "compare", "selftest", "promote"))
    ap.add_argument("ref", nargs="?")
    a = ap.parse_args()
    if a.cmd == "extract":
        print(json.dumps(cmd_extract(Path(a.ref)), indent=1))
    elif a.cmd == "compare":
        if a.ref:
            cmd_extract(Path(a.ref))
        print(json.dumps(cmd_compare(), indent=1))
    elif a.cmd == "promote":
        print(json.dumps(cmd_promote(), indent=1))
    else:
        print(json.dumps(cmd_selftest(), indent=1))


if __name__ == "__main__":
    sys.exit(main())

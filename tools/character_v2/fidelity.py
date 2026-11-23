"""Visual fidelity loop (numpy + Pillow, no Blender): silhouettes, calibrated alignment, overall + regional IoU.

    python tools/character_v2/fidelity.py extract REF.png OUT_mask.png [--key green]
    python tools/character_v2/fidelity.py calibrate REF_mask.png CAND_PREFIX OUT.json
    python tools/character_v2/fidelity.py score REF_mask.png CAND_PREFIX CALIB.json OUT_DIR [--ref-image REF.png]

extract   Reference silhouette from an illustration: background keyed out (green-screen style: pixels whose green
          clearly dominates), then the largest connected component is kept (drops decorative bananas/leaves/text).
          Thin fur edges are treated consistently by a 1-pixel open/close.
calibrate Camera registration, done ONCE per reference and then locked: a 2D similarity (scale + translation) that
          maps the candidate render onto the reference, found by maximising silhouette IoU over a coarse-to-fine
          grid. Later candidates are scored with the SAME transform, so geometry changes, not camera tweaks,
          move the score.
score     Overall IoU, regional IoU (candidate region masks from fidelity_render's label map; reference pixels
          not covered by the candidate are assigned to the nearest candidate region), per-region missing /
          extra pixel shares, an overlay (green = both, red = reference only, blue = candidate only), a heat map
          of the difference blurred to show where errors cluster, and landmark positions if available.
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

REGIONS = ["head", "shoulders", "upper_arms", "forearms", "hands", "torso", "hips", "legs", "feet"]
PALETTE = [(255, 0, 0), (255, 255, 0), (0, 255, 0), (0, 255, 255), (0, 0, 255), (255, 0, 255), (255, 128, 0),
           (128, 0, 255), (128, 255, 128)]


def load_mask(p) -> np.ndarray:
    return np.asarray(Image.open(p).convert("L")) > 127


def largest_component(m: np.ndarray) -> np.ndarray:
    h, w = m.shape
    lab = np.zeros((h, w), np.int32)
    best, best_n, cur = 0, 0, 0
    for y0 in range(0, h, 4):
        for x0 in range(0, w, 4):
            if not m[y0, x0] or lab[y0, x0]:
                continue
            cur += 1
            n = 0
            q = deque([(y0, x0)])
            lab[y0, x0] = cur
            while q:
                y, x = q.popleft()
                n += 1
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < h and 0 <= xx < w and m[yy, xx] and not lab[yy, xx]:
                        lab[yy, xx] = cur
                        q.append((yy, xx))
            if n > best_n:
                best, best_n = cur, n
    return lab == best


def fill_small_holes(m: np.ndarray, max_frac: float = 0.004) -> np.ndarray:
    """Fill enclosed background pockets smaller than max_frac of the silhouette (keyed-out green irises, dark
    green specks); real gaps between arm, body and legs are larger and stay open."""
    h, w = m.shape
    bg = ~m
    seen = np.zeros((h, w), bool)
    out = m.copy()
    limit = max_frac * m.sum()
    for y0 in range(h):
        for x0 in range(w):
            if not bg[y0, x0] or seen[y0, x0]:
                continue
            comp, border = [], False
            q = deque([(y0, x0)])
            seen[y0, x0] = True
            while q:
                y, x = q.popleft()
                comp.append((y, x))
                if y in (0, h - 1) or x in (0, w - 1):
                    border = True
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < h and 0 <= xx < w and bg[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        q.append((yy, xx))
            if not border and len(comp) < limit:
                ys, xs = zip(*comp)
                out[list(ys), list(xs)] = True
    return out


def extract(ref: Path, out: Path) -> dict:
    im = np.asarray(Image.open(ref).convert("RGB")).astype(np.float32) / 255
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    bg = (g > r + 0.08) & (g > b + 0.02)                       # green backdrop and leaves
    m = ~bg
    pil = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    m = largest_component(np.asarray(pil) > 127)
    pil = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    m = fill_small_holes(np.asarray(pil) > 127)
    Image.fromarray((m * 255).astype(np.uint8)).save(out)
    return {"ref": ref.name, "pixels": int(m.sum()), "bbox": bbox(m)}


def bbox(m):
    ys, xs = np.nonzero(m)
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def warp(arr: np.ndarray, s: float, tx: float, ty: float, shape, nearest=True) -> np.ndarray:
    """Place candidate image (scaled by s, top-left at tx, ty) on a canvas of the reference's shape."""
    h, w = arr.shape[:2]
    im = Image.fromarray(arr)
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    im = im.resize((nw, nh), Image.NEAREST if nearest else Image.BILINEAR)
    canvas = Image.new(im.mode, (shape[1], shape[0]))
    canvas.paste(im, (int(round(tx)), int(round(ty))))
    return np.asarray(canvas)


def iou(a, b) -> float:
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 0.0


def calibrate(ref_mask: Path, cand: str, out: Path) -> dict:
    ref = load_mask(ref_mask)
    cm = load_mask(cand + "_mask.png")
    rb, cb = bbox(ref), bbox(cm)
    s0 = (rb[3] - rb[1]) / (cb[3] - cb[1])                     # start: match heights, align bottoms + centres
    tx0 = (rb[0] + rb[2]) / 2 - s0 * (cb[0] + cb[2]) / 2
    ty0 = rb[3] - s0 * cb[3]
    best = (-1.0, s0, tx0, ty0)
    small = (ref.shape[0] // 3, ref.shape[1] // 3)
    ref_s = np.asarray(Image.fromarray(ref.astype(np.uint8) * 255).resize((small[1], small[0]), Image.NEAREST)) > 127
    cm8 = cm.astype(np.uint8) * 255
    for span_s, span_t, steps in ((0.12, 0.08, 7), (0.03, 0.02, 7), (0.008, 0.005, 5)):
        _, s_c, tx_c, ty_c = best
        for s in np.linspace(s_c * (1 - span_s), s_c * (1 + span_s), steps):
            for tx in np.linspace(tx_c - span_t * ref.shape[1], tx_c + span_t * ref.shape[1], steps):
                for ty in np.linspace(ty_c - span_t * ref.shape[0], ty_c + span_t * ref.shape[0], steps):
                    w_ = warp(cm8, s / 3, tx / 3, ty / 3, small) > 127
                    v = iou(ref_s, w_)
                    if v > best[0]:
                        best = (v, s, tx, ty)
    v, s, tx, ty = best
    full = warp(cm8, s, tx, ty, ref.shape) > 127
    res = {"ref_mask": ref_mask.name, "calibrated_on": Path(cand).name, "scale": s, "tx": tx, "ty": ty,
           "iou_at_calibration": round(iou(ref, full), 4), "locked": True}
    out.write_text(json.dumps(res, indent=1))
    return res


def decode_regions(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    pal = np.array(PALETTE, np.float32)
    d = ((rgb[..., None, :].astype(np.float32) - pal[None, None]) ** 2).sum(-1)
    lab = d.argmin(-1)
    lab[~alpha] = -1
    return lab


def nearest_label(lab: np.ndarray, iters: int = 400) -> np.ndarray:
    """Grow labels into unlabelled pixels (4-neighbour dilation) so every pixel gets its nearest region."""
    out = lab.copy()
    for _ in range(iters):
        un = out < 0
        if not un.any():
            break
        grown = out.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = np.roll(out, (dy, dx), (0, 1))
            take = un & (grown < 0) & (sh >= 0)
            grown[take] = sh[take]
        out = grown
    return out


def score(ref_mask: Path, cand: str, calib: Path, out_dir: Path, ref_image: Path | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    c = json.loads(calib.read_text())
    ref = load_mask(ref_mask)
    cm = warp(load_mask(cand + "_mask.png").astype(np.uint8) * 255, c["scale"], c["tx"], c["ty"], ref.shape) > 127
    reg = np.asarray(Image.open(cand + "_regions.png").convert("RGBA"))
    rgb = warp(reg[..., :3].copy(), c["scale"], c["tx"], c["ty"], ref.shape)
    lab = decode_regions(rgb, cm)
    near = nearest_label(lab)
    res = {"candidate": Path(cand).name, "reference": ref_mask.name, "calibration": calib.name,
           "overall_iou": round(iou(ref, cm), 4), "regions": {}}
    for i, r in enumerate(REGIONS):
        cr = lab == i
        zone = near == i
        if not cr.any():
            continue
        inter = (cr & ref).sum()
        union = (cr | (ref & zone)).sum()
        res["regions"][r] = {"iou": round(float(inter / union), 4) if union else None,
                             "candidate_px": int(cr.sum()),
                             "reference_only_px": int((ref & zone & ~cm).sum()),
                             "candidate_only_px": int((cr & ~ref).sum())}
    ranked = sorted(res["regions"].items(), key=lambda kv: -(kv[1]["reference_only_px"] + kv[1]["candidate_only_px"]))
    res["largest_discrepancies"] = [k for k, _ in ranked[:4]]
    ov = np.zeros(ref.shape + (3,), np.uint8)
    ov[ref & cm] = (60, 170, 90)
    ov[ref & ~cm] = (230, 60, 60)
    ov[~ref & cm] = (60, 110, 240)
    Image.fromarray(ov).save(out_dir / "overlay.png")
    diff = Image.fromarray(((ref ^ cm) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(9))
    d = np.asarray(diff).astype(np.float32)
    d = d / max(1.0, d.max())
    heat = np.stack([np.clip(d * 2, 0, 1), np.clip(d * 2 - 1, 0, 1) * 0.8, 0.15 + 0 * d], -1)
    Image.fromarray((heat * 255).astype(np.uint8)).save(out_dir / "heatmap.png")
    col = Image.open(cand + "_color.png").convert("RGBA")
    colw = Image.fromarray(warp(np.asarray(col), c["scale"], c["tx"], c["ty"], ref.shape, nearest=False))
    if ref_image:
        base = Image.open(ref_image).convert("RGBA")
        side = Image.new("RGB", (base.width * 2, base.height), (30, 30, 30))
        side.paste(base.convert("RGB"), (0, 0))
        bg = Image.new("RGBA", base.size, (40, 60, 45, 255))
        bg.alpha_composite(colw)
        side.paste(bg.convert("RGB"), (base.width, 0))
        side.save(out_dir / "side_by_side.png")
    camj = Path(cand + "_cam.json")
    if camj.exists():
        lm = json.loads(camj.read_text()).get("landmarks_px", {})
        res["landmarks_px_in_reference_frame"] = {k: [round(v[0] * c["scale"] + c["tx"], 1), round(v[1] * c["scale"] + c["ty"], 1)]
                                                  for k, v in lm.items()}
        dr = ImageDraw.Draw(img := Image.open(out_dir / "overlay.png").convert("RGB"))
        for k, (x, y) in res["landmarks_px_in_reference_frame"].items():
            dr.ellipse((x - 4, y - 4, x + 4, y + 4), outline=(255, 255, 255), width=2)
        img.save(out_dir / "overlay.png")
    (out_dir / "score.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("ref", type=Path)
    e.add_argument("out", type=Path)
    k = sub.add_parser("calibrate")
    k.add_argument("ref_mask", type=Path)
    k.add_argument("cand")
    k.add_argument("out", type=Path)
    s = sub.add_parser("score")
    s.add_argument("ref_mask", type=Path)
    s.add_argument("cand")
    s.add_argument("calib", type=Path)
    s.add_argument("out_dir", type=Path)
    s.add_argument("--ref-image", type=Path)
    a = ap.parse_args()
    if a.cmd == "extract":
        print(json.dumps(extract(a.ref, a.out)))
    elif a.cmd == "calibrate":
        print(json.dumps(calibrate(a.ref_mask, a.cand, a.out)))
    else:
        print(json.dumps(score(a.ref_mask, a.cand, a.calib, a.out_dir, a.ref_image), indent=1))

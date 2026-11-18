"""Procedural fur textures for Monkey (numpy only, no API):

  ui/public/textures/fur_detail.png  512x512 tileable gray+alpha. Gray = strand height (runtime bump), alpha = cavity
                                     (darker in the gaps between clumps), drawn as clumps of strands hanging
                                     down (texture V = up).
  tools/fur/tuft_alpha.png           256x256 tuft card: 3 tapering clumped strands, white with alpha, used by
                                     tools/blender/fur_cards.py for the silhouette cards.

    python tools/fur/make_fur_detail.py [--seed 7]
"""
from __future__ import annotations

import argparse
import zlib
import struct
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def png(path: Path, img: np.ndarray) -> None:
    """Minimal PNG writer (RGBA8, or gray+alpha when given 2 channels), so this needs nothing but numpy."""
    h, w, c = img.shape
    img = np.nan_to_num(np.clip(img, 0, 255))
    raw = b"".join(b"\x00" + img[y].astype(np.uint8).tobytes() for y in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6 if c == 4 else 4, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def blur_wrap(a: np.ndarray, r: int) -> np.ndarray:
    """Box blur with wrap-around (keeps tiling), applied twice ~ gaussian."""
    for _ in range(2):
        for ax in (0, 1):
            acc = np.zeros_like(a)
            for d in range(-r, r + 1):
                acc += np.roll(a, d, axis=ax)
            a = acc / (2 * r + 1)
    return a


def strands(n: int, rng, clumps: int = 70, per: tuple = (10, 22)) -> np.ndarray:
    """Height field of hanging strands grouped in clumps; drawn with wrap-around so it tiles."""
    h = np.zeros((n, n), np.float32)
    yy = np.arange(n)
    for _ in range(clumps):
        cx, cy = rng.uniform(0, n, 2)
        lean = rng.uniform(-0.12, 0.12)                       # clump leans a little left/right
        for _ in range(rng.integers(*per)):
            x0 = cx + rng.normal(0, n * 0.012)
            y0 = cy + rng.normal(0, n * 0.02)
            length = rng.uniform(0.10, 0.24) * n
            width = rng.uniform(0.9, 1.8)
            bend = rng.normal(0, 0.04)
            for t in np.linspace(0, 1, int(length)):
                y = int(y0 - t * length) % n                  # strands hang downward (V up = image up)
                x = x0 + (lean + bend * t) * t * length
                taper = (1 - t) ** 0.6 * (0.6 + 0.4 * rng.random())
                xs = np.arange(int(x - 3 * width), int(x + 3 * width) + 1)
                prof = np.exp(-((xs - x) / width) ** 2) * taper
                np.maximum.at(h[y], xs % n, prof)
    return h


def fur_detail(n: int, rng) -> np.ndarray:
    h = strands(n, rng)
    h = 0.75 * h + 0.25 * blur_wrap(h, 1)
    clump = blur_wrap(h, 10)                                  # where strands bunch up
    cav = np.clip(0.55 + 1.6 * (clump - clump.mean()), 0, 1)  # gaps between clumps read darker
    h = (h - h.min()) / (np.ptp(h) or 1)
    out = np.zeros((n, n, 2), np.float32)                     # gray = strand height, alpha = cavity
    out[..., 0] = h * 255
    out[..., 1] = cav * 255
    return out


def tuft(n: int, rng) -> np.ndarray:
    """One tuft card: 3 clumped strands from a wide root (bottom) to soft points (top)."""
    a = np.zeros((n, n), np.float32)
    ys = np.linspace(0, 1, n)[:, None]                         # 0 at root (bottom row), 1 at tip
    xs = np.linspace(-1, 1, n)[None, :]
    # a soft clump: a full rounded body plus 4 locks with rounded tips (reads as fuzz, not twigs)
    body = np.clip(1 - (np.abs(xs) / (0.62 * np.clip(1 - ys / 0.75, 0, 1) ** 0.7 + 1e-3)), 0, 1) ** 0.5
    a = body * (ys < 0.75)
    for cx, length, w in ((-0.45, 0.8, 0.34), (-0.12, 1.0, 0.4), (0.18, 0.92, 0.38), (0.48, 0.72, 0.3)):
        cxn = cx + rng.normal(0, 0.03) + 0.15 * ys ** 2 * np.sign(cx or 1)
        width = w * np.clip(1 - (ys / length) ** 2, 0, 1) ** 0.5                 # rounded tips
        strand = np.clip(1 - np.abs(xs - cxn) / np.maximum(width, 1e-3), 0, 1) ** 0.45
        a = np.maximum(a, strand * (ys < length))
    a[ys[:, 0] < 0.04] *= 0.6                                   # soft at the root so it blends into the skin
    a = a[::-1]                                                 # image row 0 = tip (top)
    out = np.zeros((n, n, 4), np.float32)
    shade = 0.78 + 0.22 * np.linspace(1, 0, n)[:, None]         # lighter tips, darker roots
    out[..., :3] = (shade * 255)[..., None]
    out[..., 3] = np.clip(a * 1.4, 0, 1) * 255
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    rng = np.random.default_rng(ap.parse_args().seed)
    png(ROOT / "ui" / "public" / "textures" / "fur_detail.png", fur_detail(512, rng))
    png(ROOT / "tools" / "fur" / "tuft_alpha.png", tuft(256, rng))
    print("wrote fur_detail.png + tuft_alpha.png")


if __name__ == "__main__":
    main()

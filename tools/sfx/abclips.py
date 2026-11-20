"""Blind A/B listening clips: each side of a pair is a short sequence of a cue's takes at the app's real pace.

    python -m tools.sfx.abclips PAIRS.json OUT_DIR

PAIRS.json: {"pairs": [{"id": "click", "moment": "…", "when": "…", "context": "…",
                         "pace_ms": 450, "count": 4, "sides": {"a": [take files…], "b": […], "c": […]}}]}
(two or three sides per card: the shipped cue plus one or two candidates)
Takes inside a side are leveled to their median (as the engine does), played in shuffle-bag order with the engine's
±5% pitch variation (seeded, so both sides get the same treatment), and both sides of a pair are matched to the same
loudest-10 ms level, so loudness can't decide the vote. Output files get random names; the key stays in
OUT_DIR/key.json (keep it private until the votes are in). Offline, free.
"""
from __future__ import annotations

import json
import secrets
import subprocess
import sys
from pathlib import Path

import numpy as np

from .inventory import SR, decode
from .recipe import peak_rms10, true_peak

MATCH_DB = -16.0


def sequence(files: list[Path], count: int, pace_ms: int, seed: int) -> np.ndarray:
    rnd = np.random.default_rng(seed)
    takes = [decode(f).mean(axis=0).astype(np.float64) for f in files]
    lv = [peak_rms10(t) for t in takes]
    med = float(np.median(lv))
    takes = [t * 10 ** (np.clip(med - v, -6, 6) / 20) for t, v in zip(takes, lv)]
    order: list[int] = []
    while len(order) < count:
        bag = list(rnd.permutation(len(takes)))
        if order and len(bag) > 1 and bag[0] == order[-1]:
            bag.append(bag.pop(0))
        order += bag
    order = order[:count]
    from scipy.signal import resample_poly
    out = np.zeros(int(SR * (pace_ms * count / 1000 + 2.5)))
    for k, i in enumerate(order):
        rate = 1 + rnd.uniform(-0.05, 0.05)
        x = resample_poly(takes[i], 1000, int(round(1000 * rate)))
        x *= 10 ** (rnd.uniform(-2, 2) / 20)
        o = int(SR * k * pace_ms / 1000)
        out[o:o + len(x)] += x[: len(out) - o]
    above = np.nonzero(np.abs(out) > 1e-4)[0]
    return out[: above[-1] + int(0.05 * SR)] if above.size else out


def write_ogg(x: np.ndarray, path: Path) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-",
                    "-c:a", "libopus", "-b:a", "96k", str(path)], input=pcm, check=True)


def build(spec: dict, out: Path, root: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    (out / "s").mkdir(exist_ok=True)
    key, pairs = {}, []
    for n, p in enumerate(spec["pairs"]):
        clips, xs = {}, {}
        for side, files in p["sides"].items():
            x = sequence([root / f for f in files], p.get("count", 3), p.get("pace_ms", 500), seed=1000 + n)
            xs[side] = x * 10 ** ((MATCH_DB - peak_rms10(x)) / 20)
        # every side of a card at one level: if one side would exceed -1 dBTP, all of them come down together
        cut = max(0.0, max(true_peak(x) for x in xs.values()) + 1)
        for side, files in p["sides"].items():
            x = xs[side] * 10 ** (-cut / 20)
            name = f"s/{secrets.token_hex(4)}.ogg"
            write_ogg(x, out / name)
            clips[side] = name
            key[name] = {"pair": p["id"], "side": side, "files": files}
        pairs.append({"id": p["id"], "moment": p["moment"], "when": p["when"], "context": p["context"],
                      "files": list(clips.values())})
    (out / "pairs.json").write_text(json.dumps({"version": spec.get("version", 1), "pairs": pairs}, indent=1))
    (out / "key.json").write_text(json.dumps(key, indent=1))
    return key


if __name__ == "__main__":
    spec = json.loads(Path(sys.argv[1]).read_text())
    k = build(spec, Path(sys.argv[2]), Path(spec.get("root", ".")))
    print(f"{len(k)} clips -> {sys.argv[2]}")

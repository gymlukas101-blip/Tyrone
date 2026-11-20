"""Inventory of the bundled sound kit: every take measured, every cue traced to where the app plays it.

    python -m tools.sfx.inventory [--json OUT.json] [--md OUT.md]

Measures per take (decoded with ffmpeg, so it's what the browser plays): duration, sample peak, true peak (4x
oversampled), integrated loudness (LUFS, only for takes >= 0.4 s where it's defined), leading silence, tail
(peak -> -60 dB), file size and SHA-256. Trigger sites are found by searching the UI source for the cue name.
Offline and free: no network, no API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SR = 48000


def decode(path: Path, sr: int = SR) -> np.ndarray:
    """(channels, samples) float32 at sr, exactly as decoded by ffmpeg."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    ch = int(probe.stdout.strip() or 1)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", str(ch), "-ar", str(sr), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, ch).T.copy()


def dbfs(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def measure(path: Path) -> dict:
    from scipy.signal import resample_poly

    a = decode(path)
    mono = a.mean(axis=0)
    n = a.shape[1]
    peak = float(np.abs(a).max()) if n else 0.0
    tp = float(max(np.abs(resample_poly(c, 4, 1)).max() for c in a)) if n else 0.0
    lufs = None
    if n >= 0.4 * SR:
        import pyloudnorm
        try:
            v = pyloudnorm.Meter(SR).integrated_loudness(a.T if a.shape[0] > 1 else mono)
            lufs = round(float(v), 1) if np.isfinite(v) else None
        except ValueError:
            lufs = None
    env = np.abs(mono)
    thresh = peak * 10 ** (-40 / 20)
    on = int(np.argmax(env > thresh)) if peak > 0 else 0
    ip = int(np.argmax(env))
    above = np.nonzero(env > peak * 10 ** (-60 / 20))[0]
    tail = (above[-1] - ip) / SR if above.size else 0.0
    # 10 ms RMS windows: the loudest short-term level (what a click "hits" at)
    w = int(0.01 * SR)
    rms = np.sqrt(np.convolve(mono ** 2, np.ones(w) / w, mode="valid")) if n > w else np.array([0.0])
    return {
        "file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path), "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "channels": a.shape[0], "dur_s": round(n / SR, 3),
        "peak_dbfs": round(dbfs(peak), 1), "true_peak_dbtp": round(dbfs(tp), 1),
        "lufs_i": lufs, "max_rms10ms_db": round(dbfs(float(rms.max())), 1),
        "onset_ms": round(on / SR * 1000, 1), "tail_s": round(float(tail), 3),
    }


def triggers(cue: str) -> list[str]:
    """Where the UI source plays this cue (file:line): lines that name it in quotes AND involve the sound engine
    (sfx.play / sfx.has / an animation beat's `sfx:`), so a CSS class or element id of the same name doesn't count."""
    hits = []
    pat = re.compile(r"""["'`]""" + re.escape(cue) + r"""["'`]""")
    for f in sorted((ROOT / "ui" / "src").rglob("*.ts")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line) and "sfx" in line:
                hits.append(f"{f.relative_to(ROOT)}:{i}")
    return hits


def inventory() -> dict:
    index = json.loads((ROOT / "ui" / "public" / "sfx" / "index.json").read_text())["cues"]
    design = json.loads((ROOT / "tools" / "sfx" / "cues.json").read_text())["cues"]
    out = {}
    for cue, files in sorted(index.items()):
        takes = [measure(ROOT / "ui" / "public" / f) for f in files]
        out[cue] = {"takes": takes, "triggers": [t for t in triggers(cue) if not t.startswith("ui/src/avatar/sfx.ts")],
                    "engine_rules": [t for t in triggers(cue) if t.startswith("ui/src/avatar/sfx.ts")],
                    "design": design.get(cue, {})}
    return out


def markdown(inv: dict) -> str:
    rows = ["| Cue | Takes | Dur (s) | Peak dBFS | True peak | LUFS-I | Loud 10 ms | Tail (s) | KB | Played from |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for cue, c in inv.items():
        t = c["takes"]
        rng = lambda k: f"{min(x[k] for x in t)}–{max(x[k] for x in t)}" if len(t) > 1 else f"{t[0][k]}"
        lufs = [x["lufs_i"] for x in t if x["lufs_i"] is not None]
        where = ", ".join(sorted({s.split(":")[0].split("/")[-1] for s in c["triggers"]})) or "**never**"
        rows.append(f"| `{cue}` | {len(t)} | {rng('dur_s')} | {rng('peak_dbfs')} | {max(x['true_peak_dbtp'] for x in t)} | "
                    f"{(str(min(lufs)) + '–' + str(max(lufs))) if lufs else 'n/a'} | {rng('max_rms10ms_db')} | "
                    f"{rng('tail_s')} | {round(sum(x['bytes'] for x in t) / 1024)} | {where} |")
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--md")
    a = ap.parse_args()
    inv = inventory()
    if a.json:
        Path(a.json).write_text(json.dumps(inv, indent=1))
    md = markdown(inv)
    if a.md:
        Path(a.md).write_text(md)
    takes = [t for c in inv.values() for t in c["takes"]]
    print(md)
    print(f"{len(inv)} cues, {len(takes)} takes, {sum(t['bytes'] for t in takes) / 1e6:.2f} MB, "
          f"{sum(t['dur_s'] for t in takes):.1f} s of audio; never played: "
          f"{[k for k, c in inv.items() if not c['triggers']]}")

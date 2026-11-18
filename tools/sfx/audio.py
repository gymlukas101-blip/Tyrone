"""Shared audio post-processing + QC for Monkey's sound kit (ffmpeg required).

post(): trim leading silence, 5 ms fade-in, short fade-out, loudness-normalize, encode Opus mono 64 kbps.
qc():   duration in range, no clipping, no long leading silence, enough signal energy.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _run(args: list[str]) -> str:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {r.stderr[-400:]}")
    return r.stderr + r.stdout


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def post(src: Path, dst: Path, lufs: float = -18.0, max_s: float | None = None, loop: bool = False,
         ceiling_db: float = -2.0) -> None:
    """Normalize + encode. Loops keep their tails (no trimming/fades that would click at the seam)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    chain = []
    if not loop:
        chain.append("silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.02")
        chain.append("areverse,silenceremove=start_periods=1:start_threshold=-60dB:start_silence=0.08,areverse")
        chain.append("afade=t=in:d=0.005")
    if max_s:
        chain.append(f"atrim=0:{max_s}")
        if not loop:
            chain.append(f"afade=t=out:st={max(0.0, max_s - 0.06)}:d=0.06")
    # Short transients: loudnorm alone overshoots to 0 dBFS, so a brick-wall limiter after it caps the peak
    # (with headroom for Opus's inter-sample overshoot). The limiter runs at 48 kHz, the encode rate.
    chain.append(f"loudnorm=I={lufs}:TP=-1.5:LRA=11")
    chain.append("aresample=48000")
    chain.append(f"alimiter=limit={10 ** (ceiling_db / 20):.3f}:attack=1:release=30:level=false")
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", ",".join(chain), "-ac", "1", "-ar", "48000",
          "-c:a", "libopus", "-b:a", "64k", str(dst)])


@dataclass
class QC:
    ok: bool
    dur: float
    peak_db: float
    mean_db: float
    reason: str = ""


def qc(path: Path, min_s: float = 0.08, max_s: float = 30.0) -> QC:
    if not path.exists() or path.stat().st_size < 200:
        return QC(False, 0.0, -99.0, -99.0, "empty output (all silence?)")
    try:
        d = duration(path)
        stats = _run(["ffmpeg", "-v", "info", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"])
    except RuntimeError as exc:
        return QC(False, 0.0, -99.0, -99.0, f"unreadable: {str(exc)[-80:]}")
    peak = mean = -99.0
    for line in stats.splitlines():
        if "max_volume:" in line:
            peak = float(line.split("max_volume:")[1].split()[0])
        if "mean_volume:" in line:
            mean = float(line.split("mean_volume:")[1].split()[0])
    reason = ""
    if not (min_s <= d <= max_s):
        reason = f"duration {d:.2f}s outside {min_s}-{max_s}"
    elif peak > -0.2:
        reason = f"clipping (peak {peak} dB)"
    elif mean < -45:
        reason = f"too quiet / empty (mean {mean} dB)"
    return QC(not reason, d, peak, mean, reason)


def write_manifest(root: Path) -> dict:
    """ui/public/sfx/index.json: {cue: ["sfx/cue_1.ogg", ...]} (vocal cues are prefixed 'vocal/')."""
    cues: dict[str, list[str]] = {}
    for p in sorted(root.rglob("*.ogg")):
        rel = p.relative_to(root.parent).as_posix()          # "sfx/..." relative to ui/public
        cue = p.relative_to(root).as_posix().rsplit("_", 1)[0]
        cues.setdefault(cue, []).append(rel)
    (root / "index.json").write_text(json.dumps({"version": 1, "cues": cues}, indent=1))
    return cues

"""Zero-API sound production: render a cue's candidate takes from a JSON recipe of licensed source files.

    python -m tools.sfx.recipe RECIPES.json OUT_DIR [--sources DIR]

No network, no paid API. Every output is reproducible from its recipe: sources are pinned by SHA-256 and every
processing step is a number in the recipe. Outputs: 48 kHz mono WAV master + Opus .ogg (the kit's runtime format)
+ a manifest with QC and checksums. The legacy ElevenLabs generator (generate_sfx.py) is untouched and not called.

Recipe format (one file, many cues):
{
  "cue": {
    "takes": [
      {"layers": [
        {"src": "kenney/impactSoft_heavy_000.ogg", "sha256": "…", "gain_db": -3, "at_ms": 0, "pitch": 0.9,
         "trim_ms": [0, 400], "hp_hz": 80, "lp_hz": 6000, "fade_in_ms": 1, "fade_out_ms": 60}
      ]}
    ],
    "target_db": -12,          # loudest-10 ms level of the finished take (dBFS); takes are matched to it
    "max_ms": 450,             # hard length cap (with fade)
    "ceiling_dbtp": -3         # true-peak ceiling
  }
}
"pitch" is a playback-rate change (cartoon style: higher = shorter), like the engine's own variation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from .inventory import SR, decode

ROOT = Path(__file__).resolve().parents[2]


def _filt(x: np.ndarray, hp: float | None, lp: float | None) -> np.ndarray:
    from scipy.signal import butter, sosfiltfilt
    if hp:
        x = sosfiltfilt(butter(2, hp, "highpass", fs=SR, output="sos"), x)
    if lp and lp < SR / 2 - 100:
        x = sosfiltfilt(butter(2, lp, "lowpass", fs=SR, output="sos"), x)
    return x


def _fade(x: np.ndarray, fin_ms: float, fout_ms: float) -> np.ndarray:
    """Fades never take more than a quarter (in) / half (out) of the sound: a 10 ms tick keeps its body."""
    x = x.copy()
    fi = min(len(x) // 4, int(SR * fin_ms / 1000))
    fo = min(len(x) // 2, int(SR * fout_ms / 1000))
    if fi > 0:
        x[:fi] *= np.linspace(0, 1, fi)
    if fo > 0:
        x[-fo:] *= np.linspace(1, 0, fo) ** 2               # quadratic tail: natural decay, no click
    return x


def _pitch(x: np.ndarray, rate: float) -> np.ndarray:
    if abs(rate - 1) < 1e-4:
        return x
    from scipy.signal import resample_poly
    from fractions import Fraction
    f = Fraction(rate).limit_denominator(200)              # rate 1.1 -> play faster -> fewer samples
    return resample_poly(x, f.denominator, f.numerator)


def peak_rms10(x: np.ndarray) -> float:
    w = int(0.01 * SR)
    if len(x) <= w:
        return float(20 * np.log10(max(np.sqrt(np.mean(x ** 2)), 1e-9)))
    r = np.sqrt(np.convolve(x ** 2, np.ones(w) / w, mode="valid"))
    return float(20 * np.log10(max(r.max(), 1e-9)))


def true_peak(x: np.ndarray) -> float:
    from scipy.signal import resample_poly
    return float(20 * np.log10(max(np.abs(resample_poly(x, 4, 1)).max(), 1e-9)))


def render_take(take: dict, cue: dict, sources: Path) -> np.ndarray:
    parts = []
    for L in take["layers"]:
        path = sources / L["src"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if L.get("sha256") and L["sha256"] != digest:
            raise ValueError(f"{L['src']}: source changed (sha256 {digest[:12]} != {L['sha256'][:12]})")
        x = decode(path).mean(axis=0).astype(np.float64)
        a, b = L.get("trim_ms", [0, None])
        x = x[int(SR * a / 1000): (int(SR * b / 1000) if b else None)]
        x = _pitch(x, L.get("pitch", 1.0))
        x = _filt(x, L.get("hp_hz"), L.get("lp_hz"))
        x = _fade(x, L.get("fade_in_ms", 1), L.get("fade_out_ms", 20))
        x *= 10 ** (L.get("gain_db", 0) / 20)
        parts.append((int(SR * L.get("at_ms", 0) / 1000), x))
    n = max(o + len(x) for o, x in parts)
    mix = np.zeros(n)
    for o, x in parts:
        mix[o:o + len(x)] += x
    # trim leading silence (sound must start at once) and cap the length
    env = np.abs(mix)
    start = int(np.argmax(env > env.max() * 10 ** (-45 / 20)))
    mix = mix[max(0, start - int(0.001 * SR)):]
    if cue.get("max_ms"):
        mix = mix[: int(SR * cue["max_ms"] / 1000)]
    above = np.nonzero(np.abs(mix) > np.abs(mix).max() * 10 ** (-60 / 20))[0]
    mix = mix[: above[-1] + 1] if above.size else mix
    mix = _fade(mix, 1, min(cue.get("tail_fade_ms", 40), len(mix) / SR * 1000 / 3))
    # level: loudest-10 ms to the target, then keep under the true-peak ceiling
    mix *= 10 ** ((cue.get("target_db", -12) - peak_rms10(mix)) / 20)
    over = true_peak(mix) - cue.get("ceiling_dbtp", -3)
    if over > 0:
        mix *= 10 ** (-over / 20)
    return mix


def write(x: np.ndarray, wav: Path, ogg: Path) -> None:
    import wave
    pcm = np.clip(x, -1, 1)
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(3); w.setframerate(SR)
        i = (pcm * (2 ** 23 - 1)).astype(np.int32)
        w.writeframes(b"".join(int(v).to_bytes(3, "little", signed=True) for v in i))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-c:a", "libopus", "-b:a", "64k",
                    "-ar", "48000", "-ac", "1", str(ogg)], check=True)


def render(recipes: dict, out: Path, sources: Path) -> dict:
    from .inventory import measure
    out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for cue, spec in recipes.items():
        if cue.startswith("_"):
            continue
        rows = []
        for i, take in enumerate(spec["takes"], 1):
            x = render_take(take, spec, sources)
            wav, ogg = out / f"{cue}_{i}.wav", out / f"{cue}_{i}.ogg"
            write(x, wav, ogg)
            m = measure(ogg)
            m["recipe"] = take
            m["silent"] = m["max_rms10ms_db"] < -50
            m["clipped"] = m["true_peak_dbtp"] > -0.5
            rows.append(m)
        manifest[cue] = rows
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("recipes")
    ap.add_argument("out")
    ap.add_argument("--sources", default=".")
    a = ap.parse_args()
    man = render(json.loads(Path(a.recipes).read_text()), Path(a.out), Path(a.sources))
    for cue, rows in man.items():
        for r in rows:
            print(f"{cue:12s} {Path(r['file']).name if 'file' in r else ''} dur {r['dur_s']:.3f}s "
                  f"loud {r['max_rms10ms_db']} dB tp {r['true_peak_dbtp']} dBTP"
                  f"{' SILENT' if r['silent'] else ''}{' CLIPPED' if r['clipped'] else ''}")

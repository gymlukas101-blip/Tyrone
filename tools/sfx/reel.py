"""Labeled before/after reel: each moment plays the shipped sound, then candidates B and C, as a captioned video.

    python -m tools.sfx.reel ABSPEC.json OUT.mp4

ABSPEC.json is the same spec tools/sfx/abclips.py takes. Unlike the blind page this one says which is which, for
exploring; decisions come from the blind review. Same pace, variation and loudness matching as the blind clips.
Offline, free (ffmpeg + Pillow).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from .abclips import MATCH_DB, sequence
from .inventory import SR
from .recipe import peak_rms10, true_peak

FPS = 10
LABEL = {"a": "now (shipped)", "b": "candidate B", "c": "candidate C"}


def card(text: str, sub: str, tag: str, path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (960, 540), (24, 46, 30))
    d = ImageDraw.Draw(im)
    try:
        big, mid = ImageFont.truetype("DejaVuSans-Bold.ttf", 46), ImageFont.truetype("DejaVuSans.ttf", 26)
    except OSError:
        big = mid = ImageFont.load_default()
    d.text((60, 150), text, fill=(255, 236, 160), font=big)
    d.text((60, 225), sub, fill=(200, 222, 205), font=mid)
    d.rounded_rectangle((60, 330, 60 + 18 * len(tag) + 50, 390), radius=14,
                        fill=(242, 194, 48) if tag.startswith("now") else (120, 200, 150))
    d.text((85, 343), tag, fill=(30, 25, 0), font=mid)
    im.save(path)


def build(spec: dict, out: Path, root: Path) -> Path:
    tmp = Path(tempfile.mkdtemp())
    audio, segs = [], []
    gap = np.zeros(int(0.7 * SR))
    for n, p in enumerate(spec["pairs"]):
        xs = {}
        for side, files in p["sides"].items():
            x = sequence([root / f for f in files], p.get("count", 3), p.get("pace_ms", 500), seed=1000 + n)
            xs[side] = x * 10 ** ((MATCH_DB - peak_rms10(x)) / 20)
        cut = max(0.0, max(true_peak(x) for x in xs.values()) + 1)
        for side, x in xs.items():
            clip = np.concatenate([x * 10 ** (-cut / 20), gap])
            img = tmp / f"{n:02d}{side}.png"
            card(p["moment"], p["context"][:70], LABEL.get(side, side), img)
            segs.append((img, len(clip) / SR))
            audio.append(clip)
    wav = tmp / "reel.wav"
    pcm = (np.clip(np.concatenate(audio), -1, 1) * 32767).astype("<i2")
    import wave
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    lst = tmp / "cards.txt"
    lst.write_text("".join(f"file '{img}'\nduration {d:.3f}\n" for img, d in segs) + f"file '{segs[-1][0]}'\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(wav),
                    "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-crf", "28", "-c:a", "aac", "-b:a", "160k",
                    "-shortest", str(out)], check=True)
    return out


if __name__ == "__main__":
    spec = json.loads(Path(sys.argv[1]).read_text())
    print(build(spec, Path(sys.argv[2]), Path(spec.get("root", "."))))

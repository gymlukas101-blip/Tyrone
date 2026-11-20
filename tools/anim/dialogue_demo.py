"""A 15-second acted dialogue on Monkey's real model and renderer, baseline face vs face mixer, side by side.

    python -m tools.anim.dialogue_demo OUT_DIR

Scene: attentive listening → he thinks → "Well, actually… that essay is due Friday, not Monday." (skeptical) →
"Whoa, you already finished it? Nice!" (surprised → delighted) → warm recovery → attentive again.

Speech audio: espeak-ng (a robotic stand-in; no paid TTS). Mouth input comes from that real audio through the app's
own viseme analyzer (monkey/audio/visemes.py), frame by frame; the "after" side also runs the text-assisted lip
sync (monkey/audio/lipsync.py) like the app's speaker does. A face close-up row shows what app size hides. Frames are rendered deterministically
(Avatar3D.step), so audio and picture are aligned by construction here; live-app sync is a separate measurement.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FPS = 30
DUR = 15.0
LINES = [(4.2, "Well, actually... that essay is due Friday, not Monday."),
         (8.6, "Whoa, you already finished it? Nice!")]
# (time, state) changes; speaking spans are added from the audio lengths
STATES = [(0.0, "idle"), (0.6, "listening"), (3.0, "transcribing"), (3.5, "thinking")]


def speak(text: str, path: Path) -> np.ndarray:
    subprocess.run(["espeak-ng", "-v", "en-us", "-p", "38", "-s", "165", "-w", str(path), text], check=True)
    w = wave.open(str(path))
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    a *= 0.7 * 32767 / max(1.0, float(np.abs(a).max()))              # normalize like a real voice level
    return a.astype(np.int16), w.getframerate()


def timeline(out: Path):
    from monkey.audio.lipsync import TextLipSync, blend
    from monkey.audio.visemes import estimate_visemes

    track = np.zeros(int(DUR * 22050), dtype=np.int16)
    sr = 22050
    spans = []
    for start, text in LINES:
        a, r = speak(text, out / f"line{len(spans)}.wav")
        assert r == sr, r
        i = int(start * sr)
        track[i:i + len(a)] = a[: len(track) - i]
        spans.append((start, start + len(a) / sr, text))
    frames, prev = [], 0.0
    lips = {a: TextLipSync(txt) for a, _, txt in spans}
    for f in range(int(DUR * FPS)):
        t = f / FPS
        c = int(t * sr)
        block = track[max(0, c - 512): c + 512]
        rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2))) if block.size else 0.0
        vis = estimate_visemes(block, sr, prev) if block.size else {"viseme_sil": 1.0}
        prev = rms
        span = next((a for a, b, _ in spans if a <= t < b), None)
        vis_text = blend(lips[span].feed(rms), vis) if span is not None else vis   # the app's text-assisted path
        state = "idle"
        for ts, s in STATES:
            if t >= ts:
                state = s
        speaking = any(a <= t < b + 0.15 for a, b, _ in spans)
        if speaking:
            state = "speaking"
        elif t >= spans[-1][1] + 0.15:
            state = "idle" if t < 12.2 else "listening"
        sentence = next((txt for a, b, txt in spans if abs(t - a) < 0.5 / FPS), None)
        frames.append({"t": t, "state": state, "level": min(1.0, rms / 6000.0), "visemes": vis, "visemes_text": vis_text, "sentence": sentence})
    with wave.open(str(out / "speech.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(track.tobytes())
    return frames


def render(out: Path, frames: list[dict], mode: str) -> Path:
    from playwright.sync_api import sync_playwright

    from tests.test_m4_avatar import _serve
    from tools.automation_eval import browser_path

    d = out / f"frames_{mode}"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    srv = _serve()
    q = "&face=baseline" if mode == "baseline" else ""
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=browser_path(), args=["--use-gl=angle", "--use-angle=swiftshader"])
        p = b.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=2)   # sharp face close-ups
        p.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo{q}")
        p.wait_for_function("() => window.__monkeyReady && window.__monkeyAvatarObj && window.__monkeyAvatarObj.stats.frames > 3",
                            timeout=60000)
        p.evaluate("() => { const a = window.__monkeyAvatarObj; a.brain.tick = () => ({kind: 'none'}); }")
        p.mouse.move(640, 260)
        clip = p.evaluate("() => { const r = document.querySelector('#avatar canvas').getBoundingClientRect();"
                          " return {x: r.left, y: r.top, width: r.width, height: r.height}; }")
        key = "visemes" if mode == "baseline" else "visemes_text"
        for i, fr in enumerate(frames):
            fr = {**fr, "visemes": fr[key]}
            p.evaluate("""fr => { const a = window.__monkeyAvatarObj;
                if (a.state !== fr.state) a.setState(fr.state);
                if (fr.sentence) a.gestureFor(fr.sentence);
                a.setLevel(fr.state === 'speaking' ? fr.level : 0);
                a.setVisemes(fr.state === 'speaking' ? fr.visemes : {});
                a.step(1 / 30); }""", fr)
            p.screenshot(path=str(d / f"{i:04d}.png"), clip=clip)
        b.close()
    srv.shutdown()
    return d


FACE = (0.3, 0.19, 0.7, 0.46)   # face box as a fraction of the avatar canvas (close-up row)


def compose(out: Path, n: int) -> Path:
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
        small = ImageFont.truetype("DejaVuSans.ttf", 16)
    except OSError:
        font = small = ImageFont.load_default()
    sbs = out / "frames_sbs"
    shutil.rmtree(sbs, ignore_errors=True)
    sbs.mkdir()
    for i in range(n):
        hi = [Image.open(out / f"frames_{m}" / f"{i:04d}.png").convert("RGB") for m in ("baseline", "mixer")]
        W, H = hi[0].size
        w, h = W // 2, H // 2
        fw = w
        fh = int(fw * (FACE[3] - FACE[1]) * H / ((FACE[2] - FACE[0]) * W))
        im = Image.new("RGB", (w * 2 + 12, 40 + h + 8 + fh), (16, 34, 22))
        for j, src in enumerate(hi):
            x = j * (w + 12)
            im.paste(src.resize((w, h), Image.LANCZOS), (x, 40))
            face = src.crop((int(FACE[0] * W), int(FACE[1] * H), int(FACE[2] * W), int(FACE[3] * H)))
            im.paste(face.resize((fw, fh), Image.LANCZOS), (x, 40 + h + 8))
        dr = ImageDraw.Draw(im)
        dr.text((12, 8), "before: old face", fill=(255, 230, 120), font=font)
        dr.text((w + 24, 8), "after: face mixer + acting + lip sync", fill=(255, 230, 120), font=font)
        dr.text((12, 40 + h - 22), "face close-up below", fill=(220, 240, 220), font=small)
        im.save(sbs / f"{i:04d}.png")
    video = out / "monkey_dialogue_before_after.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(sbs / "%04d.png"),
                    "-i", str(out / "speech.wav"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:a", "aac", "-shortest", str(video)], check=True)
    return video


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    frames = timeline(out)
    (out / "timeline.json").write_text(json.dumps(frames[:5] + [{"...": len(frames)}], indent=1))
    for mode in ("baseline", "mixer"):
        render(out, frames, mode)
    print(compose(out, len(frames)))

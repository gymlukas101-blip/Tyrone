"""Face before/after: the real model in the real renderer, baseline face code vs the face mixer.

    python -m tools.anim.face_sheet OUT.png [--size 300] [--full]

Each scenario holds the same inputs (voice state, viseme, loudness, expression, acting cue) in both builds, lets
them settle, and crops a close-up of the face (or the whole avatar at app size with --full). Software rendering
here is slow, so poses are held, not animated; timing is covered by the Vitest tests.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]

# (label, setup JS run in the page with `a` = the avatar object)
SCENARIOS = [
    ("rest", "a.setState('idle');"),
    ("talking 'AH' with a smile",
     "a.setState('speaking'); a.expr = {smile: 0.9, cheeksUp: 0.5}; a.setLevel(0.7); a.setVisemes({viseme_aa: 1});"),
    ("'M' closure mid-smile",
     "a.setState('speaking'); a.expr = {smile: 0.9, cheeksUp: 0.5}; a.setLevel(0.5); a.setVisemes({viseme_PP: 1});"),
    ("'OO' while surprised",
     "a.setState('speaking'); a.expr = {mouthO: 0.8, wideEyes: 1, browsUp: 1}; a.setLevel(0.6); a.setVisemes({viseme_U: 1});"),
    ("talking 'EE', skeptical",
     "a.setState('speaking'); a.setLevel(0.6); a.setVisemes({viseme_E: 1}); a.director && a.director.play('skeptical');"),
    ("listening (attentive)", "a.setState('listening');"),
    ("thinking", "a.setState('thinking');"),
]
FACE_BOX_JS = """() => {
  const a = window.__monkeyAvatarObj, THREE_ = a.camera.constructor;
  const head = a.life.worldPos('head', a.camera.position.clone().set(0,0,0), a.camera.position.clone().set(0, 0.12, 0.05));
  const v = head.clone().project(a.camera); const r = a.renderer.domElement.getBoundingClientRect();
  return [r.left + (v.x + 1) / 2 * r.width, r.top + (1 - v.y) / 2 * r.height, r.width, r.height];
}"""


def render(out: Path, size: int = 300, full: bool = False) -> None:
    from playwright.sync_api import sync_playwright

    from tests.test_m4_avatar import _serve
    from tools.automation_eval import browser_path

    srv = _serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo"
    cols = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=browser_path(), args=["--use-gl=angle", "--use-angle=swiftshader"])
        for mode, query in (("before (baseline)", "&face=baseline"), ("after (face mixer)", "")):
            p = b.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=2)
            p.goto(base + query)
            p.wait_for_function("() => window.__monkeyReady && window.__monkeyAvatarObj && window.__monkeyAvatarObj.stats.frames > 3",
                                timeout=60000)
            p.evaluate("() => { const a = window.__monkeyAvatarObj; a.brain.tick = () => ({kind: 'none'}); a.nextBlink = 1e15; }")
            p.mouse.move(640, 300)
            cells = []
            for label, js in SCENARIOS:
                p.evaluate("js => { const a = window.__monkeyAvatarObj; a.expr = {}; a.emoting = null; a.setVisemes({});"
                           " a.setLevel(0); a.director && (a.director.cue = null); " + "(new Function('a', js))(a); }", js)
                # keep feeding the held inputs while the pose settles (the app resends them ~30x a second)
                for _ in range(10):
                    p.evaluate("js => { const a = window.__monkeyAvatarObj; (new Function('a', js))(a); }", js)
                    p.wait_for_timeout(120)
                x, y, w, h = p.evaluate(FACE_BOX_JS)
                img = Image.open(io.BytesIO(p.screenshot())).convert("RGB")
                k = 2
                if full:
                    r = p.evaluate("() => { const c = document.querySelector('#avatar canvas').getBoundingClientRect();"
                                   " return [c.left, c.top, c.width, c.height]; }")
                    box = (int(r[0] * k), int(r[1] * k), int((r[0] + r[2]) * k), int((r[1] + r[3]) * k))
                else:
                    half = 0.16 * h
                    box = (int((x - half) * k), int((y - half * 0.9) * k), int((x + half) * k), int((y + half * 1.1) * k))
                cells.append(img.crop(box).resize((size, size if not full else int(size * 1.15))))
            cols.append((mode, cells))
            p.close()
        b.close()
    srv.shutdown()
    pad, lab = 8, 26
    ch = cols[0][1][0].height
    sheet = Image.new("RGB", (pad + 2 * (size + pad) + 220, lab + len(SCENARIOS) * (ch + pad) + pad), (20, 40, 26))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    for ci, (mode, cells) in enumerate(cols):
        d.text((220 + pad + ci * (size + pad), 4), mode, fill=(255, 230, 120), font=font)
        for ri, cell in enumerate(cells):
            sheet.paste(cell, (220 + pad + ci * (size + pad), lab + ri * (ch + pad)))
    for ri, (label, _) in enumerate(SCENARIOS):
        d.text((pad, lab + ri * (ch + pad) + ch // 2 - 8), label, fill=(240, 255, 230), font=font)
    sheet.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    render(Path(a[0]), int(a[a.index("--size") + 1]) if "--size" in a else 300, "--full" in a)

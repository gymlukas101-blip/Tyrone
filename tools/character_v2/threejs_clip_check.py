"""Every clip of a candidate in the real app (Three.js): each one played as the app plays it (state clips, emotes,
idle fidgets and the sleep chain as full-body actions; talk gestures through the app's upper-body copies), frozen at
its middle, screenshotted, plus a check that nothing threw. Writes OUT_DIR/app_<clip>.png, sheet.png, clips.json.

    .venv/bin/python tools/character_v2/threejs_clip_check.py UI_DIST MODEL.glb OUT_DIR
"""
from __future__ import annotations

import functools
import http.server
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main(dist: Path, model: Path, out: Path) -> dict:
    from PIL import Image, ImageDraw
    from playwright.sync_api import sync_playwright

    from tools.automation_eval import browser_path

    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    site = Path(tempfile.mkdtemp(prefix="v2clips_")) / "dist"
    shutil.copytree(dist, site)
    (site / "models").mkdir(exist_ok=True)
    shutil.copy2(model, site / "models" / model.name)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    rep: dict = {"model": model.name, "clips": {}, "page_errors": []}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=browser_path(), args=["--use-gl=angle", "--use-angle=swiftshader"])
            p = b.new_page(viewport={"width": 900, "height": 900})
            p.on("pageerror", lambda e: rep["page_errors"].append(str(e)[:300]))
            p.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&model={model.name}")
            p.wait_for_function("() => window.__monkeyAvatar && window.__monkeyAvatar.ready", timeout=120000)
            p.wait_for_timeout(1500)
            names = p.evaluate("""() => { const a = window.__monkeyAvatarObj;
                return [...a.actions.keys(), ...[...a.gestures.keys()].map(k => 'talk_gest_' + k)]; }""")
            for n in sorted(set(names)):
                info = p.evaluate("""(n) => { const a = window.__monkeyAvatarObj; a.mixer.stopAllAction();
                    const g = n.startsWith('talk_gest_'); const act = g ? a.gestures.get(n.slice(10)) : a.actions.get(n);
                    if (!act) return { missing: true };
                    if (g) { const base = a.actions.get('talk'); base.reset().play(); }
                    act.reset(); act.setEffectiveWeight(1); act.play(); act.time = act.getClip().duration * 0.5;
                    act.paused = true; a.mixer.update(0);
                    return { duration: Math.round(act.getClip().duration * 100) / 100, tracks: act.getClip().tracks.length }; }""", n)
                p.wait_for_timeout(250)
                p.screenshot(path=str(out / f"app_{n}.png"), clip={"x": 16, "y": 108, "width": 343, "height": 620},
                             timeout=120000)
                rep["clips"][n] = info
            b.close()
    finally:
        srv.shutdown()
    shots = sorted(out.glob("app_*.png"))
    cols, cw, ch = 8, 172, 310
    sheet = Image.new("RGB", (cols * cw, ((len(shots) + cols - 1) // cols) * ch), (20, 22, 24))
    for i, f in enumerate(shots):
        im = Image.open(f).convert("RGB").resize((cw, ch))
        ImageDraw.Draw(im).text((4, 4), f.stem[4:], fill=(255, 255, 255))
        sheet.paste(im, ((i % cols) * cw, (i // cols) * ch))
    sheet.save(out / "sheet.png")
    (out / "clips.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    r = main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    print(json.dumps({"n": len(r["clips"]), "missing": [k for k, v in r["clips"].items() if v.get("missing")],
                      "page_errors": r["page_errors"]}, indent=1))

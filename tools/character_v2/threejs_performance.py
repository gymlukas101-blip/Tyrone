"""A recorded facial performance of a V2 candidate in the real Monkey UI (demo build), driven by the app's own code.

    .venv/bin/python tools/character_v2/threejs_performance.py UI_DIST MODEL.glb OUT_DIR

The built UI (`ui/dist` of this branch) is copied to a temp folder with MODEL.glb in models/ (the production model
is never touched), opened as `index.html?demo&model=<name>` in headless Chromium (SwiftShader), and driven only
through what the app already listens to:
  - real pointer moves (the app's look-at: eyes lead, head and neck follow),
  - `state` / `level` / `visemes` events (the speech path: FaceMixer smoothing, jaw from loudness),
  - `emote` events (expression presets), the new `wink` event, and the app's own blink timer.
The model has no body clips yet, so an emote's face preset never "ends" by itself; the script clears it
(`a.expr = {}`) between beats. Records a video (webm -> mp4), key-frame screenshots, and per-beat morph weights
plus eye/head bone rotations measured inside the render call. Software WebGL: correctness, not GPU timing.
"""
from __future__ import annotations

import functools
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# A short line, as (viseme, ms): "Hey! I'm Monkey... want some bananas?"
LINE = [("viseme_sil", 80), ("viseme_kk", 70), ("viseme_E", 140), ("viseme_I", 120), ("viseme_sil", 90),
        ("viseme_aa", 120), ("viseme_I", 80), ("viseme_PP", 110), ("viseme_PP", 70), ("viseme_aa", 140),
        ("viseme_nn", 80), ("viseme_kk", 80), ("viseme_E", 130), ("viseme_sil", 140), ("viseme_U", 110),
        ("viseme_aa", 120), ("viseme_nn", 70), ("viseme_TH", 80), ("viseme_SS", 110), ("viseme_aa", 90),
        ("viseme_PP", 90), ("viseme_PP", 60), ("viseme_O", 150), ("viseme_E", 90), ("viseme_nn", 80),
        ("viseme_aa", 140), ("viseme_SS", 120), ("viseme_sil", 120)]
WATCH = ["viseme_aa", "viseme_PP", "viseme_O", "viseme_E", "jawOpen", "smile", "frown", "bigGrin", "grimace", "mouthO",
         "blink_L", "blink_R", "squint", "wideEyes", "angryEyes", "sadEyes", "browsUp", "browsAngry", "browsSad",
         "cheeksUp"]


def main(dist: Path, model: Path, out: Path) -> dict:
    from playwright.sync_api import sync_playwright

    from tools.automation_eval import browser_path

    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="v2perf_"))
    site = tmp / "dist"
    shutil.copytree(dist, site)
    (site / "models").mkdir(exist_ok=True)
    shutil.copy2(model, site / "models" / model.name)
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    h.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    rep: dict = {"model": model.name, "beats": {}, "console_errors": []}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=browser_path(), args=["--use-gl=angle", "--use-angle=swiftshader"])
            ctx = b.new_context(viewport={"width": 900, "height": 900})
            p = ctx.new_page()
            frames: list[tuple[float, bytes]] = []                # Chromium screencast (system ffmpeg encodes)
            cdp = ctx.new_cdp_session(p)

            def on_frame(params):
                import base64
                frames.append((params["metadata"]["timestamp"], base64.b64decode(params["data"])))
                try:
                    cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
                except Exception:  # noqa: BLE001
                    pass
            cdp.on("Page.screencastFrame", on_frame)
            p.on("pageerror", lambda e: rep["console_errors"].append(f"pageerror: {str(e)[:300]}"))
            p.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&model={model.name}")
            p.wait_for_function("() => window.__monkeyAvatar && window.__monkeyAvatar.ready", timeout=120000)
            p.wait_for_timeout(1200)
            # face camera fixed at the head's rest position (so head turns stay visible), measure bones in render()
            p.evaluate("""() => {
                const a = window.__monkeyAvatarObj; const V = a.camera.position.constructor;
                let head = null; a.model.traverse(o => { if (!head && o.isBone && /Head$/.test(o.name)) head = o; });
                a.model.updateMatrixWorld(true);
                const c = head.getWorldPosition(new V());
                const fwd = new V(0, 0, 1).applyQuaternion(a.model.getWorldQuaternion(a.model.quaternion.clone()));
                const pos = c.clone().addScaledVector(fwd, 1.45).add(new V(0, 0.02, 0));
                const aim = () => { a.camera.position.copy(pos); a.camera.lookAt(c.x, c.y - 0.01, c.z); requestAnimationFrame(aim); };
                aim();
                const r = a.renderer; const orig = r.render.bind(r); const rest = new Map();
                a.model.traverse(o => { if (o.isBone && /^(eyeL|eyeR|mixamorigHead|mixamorigNeck)$/.test(o.name)) rest.set(o, o.quaternion.clone()); });
                r.render = (sc, cam) => { const out = {};
                    for (const [bn, q0] of rest) out[bn.name] = Math.round(q0.angleTo(bn.quaternion) * 573) / 10;
                    window.__boneDeg = out; return orig(sc, cam); };
            }""")

            def ev(events):
                p.evaluate("ev => window.__monkeyEvents(ev)", events)

            def js(code):
                p.evaluate(f"() => {{ const a = window.__monkeyAvatarObj; {code} }}")

            def snap(label):
                vals = p.evaluate("""names => { const a = window.__monkeyAvatarObj; const r = {};
                    for (const n of names) { const refs = a.morphMap.get(n) || [];
                      if (refs.length) r[n] = Math.round(Math.max(...refs.map(x => x.influences[x.index])) * 100) / 100; }
                    return r; }""", WATCH)
                rep["beats"][label] = {"morphs": {k: v for k, v in vals.items() if v > 0.02},
                                       "bones_deg": p.evaluate("() => window.__boneDeg || {}")}
                p.screenshot(path=str(out / f"beat_{len(rep['beats']):02d}_{label}.png"))

            def speak(line, mood=None, cursor=None, wink_at=None):
                ev([["state", {"state": "speaking"}]])
                for i, (v, ms) in enumerate(line):
                    level = 0.15 if v in ("viseme_sil", "viseme_PP") else 0.55
                    ev([["visemes", {v: 1.0}], ["level", {"v": level}]])
                    if cursor:
                        x, y = cursor(i / len(line))
                        p.mouse.move(x, y)
                    if wink_at is not None and i == wink_at:
                        ev([["wink", {"side": "L"}]])
                    p.wait_for_timeout(ms)
                    if mood and i == len(line) // 2:
                        snap(f"{mood}_mid_sentence")
                ev([["visemes", {}], ["level", {"v": 0}], ["state", {"state": "idle"}]])

            cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 85, "maxWidth": 900, "maxHeight": 900})
            snap("neutral_rest")
            for k in range(12):                                   # cursor tracking: sweep left -> right -> up
                p.mouse.move(80 + 60 * k, 450 - 25 * max(0, k - 8))
                p.wait_for_timeout(120)
            snap("looking_at_cursor_right")
            p.mouse.move(60, 600)
            p.wait_for_timeout(900)
            snap("looking_at_cursor_left_down")
            p.mouse.move(450, 300)
            speak(LINE, mood="plain", cursor=lambda f: (200 + 500 * f, 380))
            ev([["emote", {"name": "happy"}]])
            p.wait_for_timeout(500)
            speak(LINE[:16], mood="smiling", wink_at=8)
            snap("happy_after_line")
            js("a.expr = {};")
            ev([["emote", {"name": "sad"}]])
            p.wait_for_timeout(500)
            speak(LINE[10:], mood="sad_frowning")
            snap("sad_after_line")
            js("a.expr = {};")
            ev([["emote", {"name": "angry"}]])
            p.wait_for_timeout(900)
            snap("angry_reaction")
            js("a.expr = {};")
            ev([["emote", {"name": "surprised"}]])
            p.wait_for_timeout(900)
            snap("surprised_reaction")
            js("a.expr = {};")
            ev([["emote", {"name": "laugh"}]])
            p.wait_for_timeout(900)
            snap("laugh_reaction")
            js("a.expr = {};")
            ev([["wink", {"side": "R", "ms": 1200}]])
            p.wait_for_timeout(450)
            snap("wink_right")
            js("a.blinkUntil = performance.now() + 600;")
            p.wait_for_timeout(120)
            snap("blink")
            p.wait_for_timeout(900)
            snap("back_to_neutral")
            cdp.send("Page.stopScreencast")
            ctx.close()
            b.close()
        if len(frames) > 2:                                      # frames at their real timestamps -> mp4
            fdir = tmp / "frames"
            fdir.mkdir()
            lines = []
            for i, (ts, data) in enumerate(frames):
                (fdir / f"f{i:05d}.jpg").write_bytes(data)
                dur = (frames[i + 1][0] - ts) if i + 1 < len(frames) else 0.1
                lines += [f"file 'f{i:05d}.jpg'", f"duration {max(0.01, dur):.4f}"]
            (fdir / "list.txt").write_text("\n".join(lines) + "\n")
            mp4 = out.resolve() / "performance.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
                            "-vf", "crop=343:620:16:108,scale=344:-2,fps=25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-crf", "22", str(mp4)], cwd=fdir, check=False, timeout=600)
            rep["video"] = {"mp4": mp4.name if mp4.exists() else None, "frames": len(frames),
                            "seconds": round(frames[-1][0] - frames[0][0], 1)}
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    (out / "performance_report.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    r = main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    for k, v in r["beats"].items():
        print(k, v)
    print("video:", r.get("video"), "errors:", r["console_errors"])

"""Three.js evidence for a V2 candidate GLB in the real Monkey UI (the demo build, no Python backend).

    .venv/bin/python tools/character_v2/threejs_face_check.py UI_DIST MODEL.glb OUT_DIR

Copies the built UI (`ui/dist`) to a temporary folder, drops MODEL.glb into its models/ folder (the repo's
ui/public/models/monkey.glb is never touched), serves it over HTTP and opens `index.html?demo&model=<name>`
in headless Chromium (SwiftShader WebGL). The app's own code then drives the face: speaking state + viseme
frames go through Avatar3D's viseme smoothing, emotes through its expression presets, the blink through its
blink timer. Screenshots (full body and a face close-up) and a JSON report (morphs found, clips, console
errors, per-step morph influences read back from the live meshes) go to OUT_DIR.

Software WebGL proves the model loads and the morphs drive in Three.js; it says nothing about GPU frame time.
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

STEPS = [  # (label, events, extra js, wait ms)
    ("neutral", [["state", {"state": "idle"}]], "", 1500),
    ("speak_aa", [["state", {"state": "speaking"}], ["level", {"v": 0.6}], ["visemes", {"viseme_aa": 1}]], "", 900),
    ("speak_PP", [["visemes", {"viseme_PP": 1}], ["level", {"v": 0.0}]], "", 900),
    ("speak_O", [["visemes", {"viseme_O": 1}], ["level", {"v": 0.3}]], "", 900),
    ("speak_E", [["visemes", {"viseme_E": 1}], ["level", {"v": 0.3}]], "", 900),
    ("speak_FF", [["visemes", {"viseme_FF": 1}], ["level", {"v": 0.1}]], "", 900),
    ("barge_in_reset", [["visemes", {}], ["level", {"v": 0}], ["state", {"state": "idle"}]], "", 1200),
    ("blink", [], "a.blinkUntil = 1e15;", 600),
    ("happy", [["emote", {"name": "happy"}]], "a.blinkUntil = 0; a.nextBlink = 1e15;", 1200),
    ("angry", [["emote", {"name": "angry"}]], "", 1200),
    ("sad", [["emote", {"name": "sad"}]], "", 1200),
    ("surprised", [["emote", {"name": "surprised"}]], "", 1200),
]
WATCH = ["viseme_aa", "viseme_PP", "viseme_O", "viseme_E", "viseme_FF", "jawOpen", "blink_L", "blink_R", "smile",
         "squint", "browsAngry", "angryEyes", "browsSad", "sadEyes", "frown", "grimace", "mouthO", "wideEyes", "browsUp"]


def main(dist: Path, model: Path, out: Path) -> dict:
    from playwright.sync_api import sync_playwright

    from tools.automation_eval import browser_path

    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="v2ui_"))
    site = tmp / "dist"
    shutil.copytree(dist, site)
    (site / "models").mkdir(exist_ok=True)
    shutil.copy2(model, site / "models" / model.name)
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    h.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    rep: dict = {"model": model.name, "console_errors": [], "steps": {}}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=browser_path(), args=["--use-gl=angle", "--use-angle=swiftshader"])
            p = b.new_page(viewport={"width": 900, "height": 900})
            p.on("console", lambda m: m.type == "error" and rep["console_errors"].append(m.text[:300]))
            p.on("pageerror", lambda e: rep["console_errors"].append(f"pageerror: {str(e)[:300]}"))
            p.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&model={model.name}")
            p.wait_for_function("() => window.__monkeyAvatar && window.__monkeyAvatar.ready", timeout=120000)
            info = p.evaluate("() => window.__monkeyAvatar")
            rep.update({"kind": info["kind"], "morphs": sorted(info["morphs"]), "clips": info["clips"]})
            if info["kind"] != "3d":
                raise SystemExit("the 3D avatar did not load (fell back to SVG)")
            p.wait_for_timeout(1500)
            p.screenshot(path=str(out / "app_full.png"))
            # Face close-up: re-aim the app's camera every frame (Three.js: Y up, the model faces +Z).
            p.evaluate("""() => {
                const a = window.__monkeyAvatarObj; const V = a.camera.position.constructor;
                let head = null;
                a.model.traverse(o => { if (!head && o.isBone && /Head$/i.test(o.name)) head = o; });
                const aim = () => {
                    a.model.updateMatrixWorld(true);
                    const c = head.getWorldPosition(new V());
                    const q = a.model.getWorldQuaternion(a.model.quaternion.clone());
                    const fwd = new V(0, 0, 1).applyQuaternion(q);
                    window.__v2face = [c.x, c.y, c.z];
                    a.camera.position.copy(c).addScaledVector(fwd, 1.25).add(new V(0, 0.03, 0));
                    a.camera.lookAt(c.x, c.y + 0.0, c.z);
                    requestAnimationFrame(aim);
                };
                aim();
            }""")
            p.wait_for_timeout(300)
            rep["face_center_threejs"] = p.evaluate("() => window.__v2face")
            for label, events, js, wait in STEPS:
                if js:
                    p.evaluate(f"() => {{ const a = window.__monkeyAvatarObj; {js} }}")
                if events:
                    p.evaluate("ev => window.__monkeyEvents(ev)", events)
                p.wait_for_timeout(wait)
                vals = p.evaluate("""names => { const a = window.__monkeyAvatarObj; const r = {};
                    for (const n of names) { const refs = a.morphMap.get(n) || [];
                      r[n] = refs.length ? Math.max(...refs.map(x => x.influences[x.index])) : null; }
                    return r; }""", WATCH)
                rep["steps"][label] = {k: (round(v, 3) if isinstance(v, (int, float)) else v) for k, v in vals.items()
                                       if v is None or v > 0.02}
                p.screenshot(path=str(out / f"face_{label}.png"))
            b.close()
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    (out / "threejs_report.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    r = main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    print(json.dumps({k: v for k, v in r.items() if k != "morphs"}, indent=1)[:3500])
    print("morphs found:", len(r.get("morphs", [])))

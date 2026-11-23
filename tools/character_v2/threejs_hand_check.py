"""Phase C in the real app (Three.js): pose the candidate with its hand / elbow clips and the in-app upper-body
gesture (with the app's own UPPER filter), freeze the mixer, and screenshot the avatar. Also reads the corrective
driver's weight and the left-hand finger bone rotation per shot.

    .venv/bin/python tools/character_v2/threejs_hand_check.py UI_DIST MODEL.glb OUT_DIR

Shots: idle rest; hand_open / hand_point / hand_grip / hand_knuckle_support / elbow_120 (full clips, frame 0);
the talk_gest_open_palms gesture as the app plays it (upper body only) at 25% / 55% / 90% of the clip.
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

SHOTS = [("rest_idle", "idle", 0.0, False), ("hand_open", "hand_open", 0.0, False), ("hand_point", "hand_point", 0.0, False),
         ("hand_grip", "hand_grip", 0.0, False), ("hand_knuckle_support", "hand_knuckle_support", 0.0, False),
         ("elbow_120", "elbow_120", 0.0, False), ("gesture_25", "talk_gest_open_palms", 0.25, True),
         ("gesture_55", "talk_gest_open_palms", 0.55, True), ("gesture_90", "talk_gest_open_palms", 0.9, True)]


def main(dist: Path, model: Path, out: Path) -> dict:
    from playwright.sync_api import sync_playwright

    from tools.automation_eval import browser_path

    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    site = Path(tempfile.mkdtemp(prefix="v2hand_")) / "dist"
    shutil.copytree(dist, site)
    (site / "models").mkdir(exist_ok=True)
    shutil.copy2(model, site / "models" / model.name)
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    h.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    rep: dict = {"model": model.name, "shots": {}, "page_errors": []}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=browser_path(), args=["--use-gl=angle", "--use-angle=swiftshader"])
            p = b.new_page(viewport={"width": 900, "height": 900}, device_scale_factor=1)
            p.on("pageerror", lambda e: rep["page_errors"].append(str(e)[:300]))
            p.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&model={model.name}")
            p.wait_for_function("() => window.__monkeyAvatar && window.__monkeyAvatar.ready", timeout=120000)
            p.wait_for_timeout(1500)
            only = sys.argv[4] if len(sys.argv) > 4 else ""
            for label, clip, frac, gesture in [s for s in SHOTS if s[0].startswith(only)]:
                info = p.evaluate("""([clip, frac, gesture]) => { const a = window.__monkeyAvatarObj;
                    a.mixer.stopAllAction();
                    const act = gesture ? a.gestures.get(clip.replace("talk_gest_", "")) : a.actions.get(clip);
                    if (!act) return { missing: clip };
                    act.reset(); act.setEffectiveWeight(1); act.play();
                    act.time = act.getClip().duration * frac; act.paused = true;
                    a.mixer.update(0);
                    const b = a.model.getObjectByName("f201L");
                    return { clip: act.getClip().name, tracks: act.getClip().tracks.length,
                             f2_01_L_quat: b ? b.quaternion.toArray().map(x => Math.round(x * 1000) / 1000) : null }; }""",
                                [clip, frac, gesture])
                p.wait_for_timeout(700)          # a few rendered frames (life layer + corrective driver run)
                info["elbowBend_L"] = p.evaluate("() => { const c = window.__monkeyAvatarObj.correctives; return c ? c.last.elbowBend_L ?? null : null; }")
                p.screenshot(path=str(out / f"app_{label}.png"), clip={"x": 16, "y": 108, "width": 343, "height": 620}, timeout=180000)
                rep["shots"][label] = info
            b.close()
    finally:
        srv.shutdown()
    old = json.loads((out / "hand_check.json").read_text()) if (out / "hand_check.json").exists() else {"shots": {}}
    old["shots"].update(rep["shots"])
    rep["shots"] = old["shots"]
    (out / "hand_check.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])), indent=1))

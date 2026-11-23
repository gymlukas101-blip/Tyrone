"""Full-body performance of a V2 candidate in the real Monkey UI: listening -> thinking -> speaking (smile, gaze, a
talk gesture) -> relaxing to idle, recorded at real time. Driven only by what the app listens to.

    .venv/bin/python tools/character_v2/threejs_body_performance.py UI_DIST MODEL.glb OUT_DIR

The app's own code chooses everything: `state` events pick the state clips (listen / think / talk / idle), the
speech path drives visemes and jaw, `delta` text events stream a reply whose "?" sentence makes the app pick a
talk gesture (`gestureFor`), an `emote` sets the face preset (and the app's clip-independent cleanup must return
it to neutral), real pointer moves drive the look-at. Per phase the report lists the clip actions actually running
(name + weight), the gesture, morph weights and head/eye angles, plus measured frame rate and the animation-time
to wall-time ratio (the mixer clamps a frame to 0.1 s, so below 10 fps animation would run slow - reported, not
hidden). Video: CDP screencast frames at their own timestamps -> mp4 (system ffmpeg). Software WebGL.
"""
from __future__ import annotations

import base64
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

VIS = [("viseme_sil", 90), ("viseme_kk", 70), ("viseme_E", 130), ("viseme_aa", 120), ("viseme_TH", 70),
       ("viseme_kk", 80), ("viseme_U", 120), ("viseme_PP", 100), ("viseme_aa", 140), ("viseme_nn", 80),
       ("viseme_E", 120), ("viseme_sil", 150), ("viseme_U", 110), ("viseme_aa", 120), ("viseme_nn", 70),
       ("viseme_TH", 80), ("viseme_SS", 110), ("viseme_aa", 90), ("viseme_PP", 90), ("viseme_O", 150),
       ("viseme_E", 90), ("viseme_nn", 80), ("viseme_aa", 140), ("viseme_SS", 120), ("viseme_sil", 140)]
WATCH = ["viseme_aa", "viseme_PP", "viseme_O", "jawOpen", "smile", "squint", "cheeksUp", "blink_L", "blink_R",
         "browsUp", "browsAngry", "browsSad", "browInnerUp_L", "browInnerUp_R", "browOuterUp_L", "browOuterUp_R", "browDown_L", "browDown_R", "browSqueeze", "elbowBend_L"]


def main(dist: Path, model: Path, out: Path) -> dict:
    from playwright.sync_api import sync_playwright

    from tools.automation_eval import browser_path

    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="v2body_"))
    site = tmp / "dist"
    shutil.copytree(dist, site)
    (site / "models").mkdir(exist_ok=True)
    shutil.copy2(model, site / "models" / model.name)
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    h.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    rep: dict = {"model": model.name, "phases": {}, "page_errors": []}
    frames: list[tuple[float, bytes]] = []
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=browser_path(), args=["--use-gl=angle", "--use-angle=swiftshader"])
            ctx = b.new_context(viewport={"width": 900, "height": 900})
            p = ctx.new_page()
            p.on("pageerror", lambda e: rep["page_errors"].append(str(e)[:300]))
            # Virtual time (test harness only): once switched on, every animation frame advances performance.now()
            # by exactly 1/30 s and the app's timers are scaled to match, so the recorded frames play back at
            # normal speed even though software WebGL renders only a few frames per real second.
            p.add_init_script("""(() => {
                const now0 = performance.now.bind(performance), raf0 = window.requestAnimationFrame.bind(window);
                const st0 = window.setTimeout.bind(window);
                const vt = window.__vt = { on: false, t: 0, step: 1000 / 30, scale: 1 };
                performance.now = () => vt.on ? vt.t : now0();
                window.requestAnimationFrame = (cb) => raf0(() => { if (vt.on) vt.t += vt.step; cb(performance.now()); });
                window.setTimeout = (fn, ms, ...a) => st0(fn, vt.on ? (ms || 0) * vt.scale : ms, ...a);
            })()""")
            cdp = ctx.new_cdp_session(p)

            def on_frame(params):
                frames.append((params["metadata"]["timestamp"], base64.b64decode(params["data"])))
                try:
                    cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
                except Exception:  # noqa: BLE001
                    pass
            cdp.on("Page.screencastFrame", on_frame)
            p.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&model={model.name}")
            p.wait_for_function("() => window.__monkeyAvatar && window.__monkeyAvatar.ready", timeout=120000)
            info = p.evaluate("() => window.__monkeyAvatar")
            rep["clips_in_model"] = info["clips"]
            p.evaluate("""() => { const a = window.__monkeyAvatarObj; window.__frames = 0;
                const r = a.renderer; const orig = r.render.bind(r); const V = a.camera.position.constructor;
                const rest = new Map(); a.model.traverse(o => { if (o.isBone && /^(head|neck|eyeL|chest)$/.test(o.name)) rest.set(o, o.quaternion.clone()); });
                r.render = (sc, cam) => { window.__frames++; const out = {};
                    for (const [bn, q0] of rest) out[bn.name] = Math.round(q0.angleTo(bn.quaternion) * 573) / 10;
                    window.__boneDeg = out; return orig(sc, cam); }; }""")
            p.evaluate("() => { window.__vt.t = performance.now(); window.__vt.on = true; }")
            r0 = p.evaluate("() => [window.__vt.t, window.__frames]")
            p.wait_for_timeout(3000)
            r1 = p.evaluate("() => [window.__vt.t, window.__frames]")
            ratio = max(0.02, (r1[0] - r0[0]) / 3000.0)               # virtual ms per real ms
            p.evaluate(f"() => {{ window.__vt.scale = {1.0 / ratio}; }}")
            rep["virtual_time"] = {"virtual_ms_per_real_ms": round(ratio, 3), "frames_per_real_s": round((r1[1] - r0[1]) / 3, 1)}
            p.evaluate("""() => { const a = window.__monkeyAvatarObj; window.__gestures = [];
                const g = a.gestureFor.bind(a);
                a.gestureFor = (s) => { const before = a.gesture; g(s);
                    window.__gestures.push({ sentence: s, played: a.gesture && a.gesture !== before ? a.gesture.getClip().name : null,
                                             at_ms: Math.round(performance.now()) }); }; }""")
            cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 85, "maxWidth": 900, "maxHeight": 900})

            def vwait(ms):
                p.wait_for_timeout(ms / ratio)

            def ev(events):
                p.evaluate("ev => window.__monkeyEvents(ev)", events)

            def probe():
                return p.evaluate("""names => { const a = window.__monkeyAvatarObj; const m = {};
                    for (const n of names) { const refs = a.morphMap.get(n) || [];
                      if (refs.length) { const v = Math.max(...refs.map(x => x.influences[x.index])); if (v > 0.02) m[n] = Math.round(v * 100) / 100; } }
                    const running = a.mixer._actions.filter(x => x.isRunning() && x.getEffectiveWeight() > 0.05)
                        .map(x => x.getClip().name + "@" + Math.round(x.getEffectiveWeight() * 100) / 100);
                    return { running, gesture: a.gesture ? a.gesture.getClip().name : null, morphs: m,
                             expr_until_in_ms: a.exprUntil ? Math.round(a.exprUntil - performance.now()) : 0,
                             bones_deg: window.__boneDeg || {}, expr: Object.keys(a.expr || {}), state: a.state,
                             correctives: a.correctives ? a.correctives.last : null, cue: a.director.cue,
                             finger_f2_01_L_deg: (() => { const b = a.model && a.model.getObjectByName("f201L");
                               return b ? Math.round(2 * Math.acos(Math.min(1, Math.abs(b.quaternion.w))) * 180 / Math.PI) : null; })() }; }""", WATCH)

            def phase(label, ms, snap=True):
                f0 = p.evaluate("() => [window.__frames, performance.now(), window.__monkeyAvatarObj.mixer.time]")
                vwait(ms)
                f1 = p.evaluate("() => [window.__frames, performance.now(), window.__monkeyAvatarObj.mixer.time]")
                dt = (f1[1] - f0[1]) / 1000
                rec = probe()
                rec["virtual_fps"] = round((f1[0] - f0[0]) / dt, 1) if dt else None
                rec["anim_time_ratio"] = round((f1[2] - f0[2]) / dt, 2) if dt else None   # mixer s per (virtual) s
                rep["phases"][label] = rec
                if snap:
                    p.screenshot(path=str(out / f"phase_{len(rep['phases']):02d}_{label}.png"))

            phase("idle", 3000)
            for k in range(8):
                p.mouse.move(150 + 60 * k, 300)
                vwait(100)
            ev([["state", {"state": "listening"}], ["user", {"text": "Hey Monkey, what should I do this afternoon?"}]])
            phase("listening", 3200)
            ev([["state", {"state": "thinking"}]])
            phase("thinking", 3200)
            ev([["state", {"state": "speaking"}], ["emote", {"name": "happy"}]])
            ev([["delta", {"text": "Great question. "}]])
            for i, (v, ms) in enumerate(VIS):
                ev([["visemes", {v: 1.0}], ["level", {"v": 0.15 if v in ("viseme_sil", "viseme_PP") else 0.55}]])
                if i == 6:
                    ev([["delta", {"text": "Want to knock out your homework first? "}]])     # "?" -> talk gesture
                if i == 18:
                    ev([["delta", {"text": "Uh-oh, your essay is due tomorrow. "}]])         # worried brows (V2)
                if i % 4 == 0:
                    p.mouse.move(200 + 18 * i, 260 + (i % 3) * 40)
                vwait(ms)
                if i == 9:
                    phase("speaking_smiling_gesture", 10)
            phase("speaking_end", 10)
            ev([["visemes", {}], ["level", {"v": 0}], ["done", {}], ["state", {"state": "idle"}]])
            phase("relax_to_idle", 1500)
            phase("idle_again_face_neutral", 2500)
            rep["gesture_calls"] = p.evaluate("() => window.__gestures")
            cdp.send("Page.stopScreencast")
            ctx.close()
            b.close()
        if len(frames) > 2:
            fdir = tmp / "frames"
            fdir.mkdir()
            lines = []
            for i, (ts, data) in enumerate(frames):
                (fdir / f"f{i:05d}.jpg").write_bytes(data)
                # screencast frames come at real time (UI repaints too); map their real spacing to virtual time
                dur = ((frames[i + 1][0] - ts) if i + 1 < len(frames) else 0.033) * ratio
                lines += [f"file 'f{i:05d}.jpg'", f"duration {max(0.001, dur):.5f}"]
            (fdir / "list.txt").write_text("\n".join(lines) + "\n")
            mp4 = out / "body_performance.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
                            "-vf", "crop=343:620:16:108,scale=344:-2,fps=30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-crf", "22", str(mp4)], cwd=fdir, check=False, timeout=600)
            rep["video"] = {"mp4": mp4.name if mp4.exists() else None, "frames": len(frames),
                            "virtual_seconds": round((frames[-1][0] - frames[0][0]) * ratio, 1),
                            "real_seconds_recorded": round(frames[-1][0] - frames[0][0], 1)}
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    (out / "body_performance_report.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    r = main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    print("clips:", r.get("clips_in_model"))
    for k, v in r["phases"].items():
        print(k, v)
    print("video:", r.get("video"), "errors:", r["page_errors"])

"""Stacked-sound peak check in the real browser audio engine (Chromium's decoder + DynamicsCompressor).

    python -m tools.sfx.mixcheck [--json OUT.json]

Renders the app's busiest moments offline (an OfflineAudioContext, so it's exact and needs no speakers) with the
real bundled takes at the engine's gains and the beat timings from ui/src/avatar/events.ts, worst case (every
take at +2 dB jitter, the loudest take of each cue). Reports the master peak without and with the safety limiter.
Offline and free.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (scene, [(seconds, cue, intensity, trim dB from SAMPLE_DB)])  — timings from events.ts at 30 fps
SCENES = {
    "mini chest-beat": [(12 / 30, "chest_thump", 0.8, 0), (18 / 30, "chest_thump", 0.88, 0),
                        (24 / 30, "chest_thump", 0.96, 0), (30 / 30, "chest_thump", 1.04, 0)],
    "wake startle": [(0, "startle", 1, 0), (6 / 30, "slide_up", 0.7, 0), (16 / 30, "thump", 1, 0),
                     (28 / 30, "scratch", 0.5, 0)],
    "sit down": [(10 / 30, "whoosh", 0.5, 0), (24 / 30, "thump", 1, 0)],
    "celebrate": [(0, "confetti", 0.7, 0), (0.05, "sparkle", 1, 0), (0.1, "heart_pop", 1, 0)],
    "click → open → error": [(0, "ui_click", 1, -6), (0.03, "ui_open", 1, -4.5), (0.25, "ui_error", 1, -5)],
}

JS = """async ({scenes, files, limiter}) => {
  const sr = 48000, dur = 3;
  const out = {};
  const ctx0 = new OfflineAudioContext(1, sr, sr);
  const cache = {};
  for (const f of files) cache[f] = await ctx0.decodeAudioData(await (await fetch(f)).arrayBuffer());
  const loudest = (cue) => {           // the take with the highest sample peak
    let best = null, bp = -1;
    for (const f of files.filter((x) => x.startsWith('sfx/' + cue + '_'))) {
      const b = cache[f]; let p = 0;
      for (let c = 0; c < b.numberOfChannels; c++) for (const v of b.getChannelData(c)) p = Math.max(p, Math.abs(v));
      if (p > bp) { bp = p; best = b; }
    }
    return best;
  };
  for (const [name, beats] of Object.entries(scenes)) {
    const ctx = new OfflineAudioContext(2, sr * dur, sr);
    const master = ctx.createGain();
    if (limiter) {
      const lim = ctx.createDynamicsCompressor();
      lim.threshold.value = -6; lim.knee.value = 3; lim.ratio.value = 20; lim.attack.value = 0.002; lim.release.value = 0.12;
      const makeup = ctx.createGain(); makeup.gain.value = Math.pow(10, -2.91 / 20);   // as in sfx.ts
      master.connect(lim).connect(makeup).connect(ctx.destination);
    } else master.connect(ctx.destination);
    for (const [t, cue, intensity, trim] of beats) {
      const s = ctx.createBufferSource(); s.buffer = loudest(cue);
      const g = ctx.createGain(); g.gain.value = Math.pow(10, (trim + 2) / 20) * intensity;   // +2 dB = worst jitter
      s.connect(g).connect(master); s.start(t);
    }
    const r = await ctx.startRendering();
    let p = 0, over = 0;
    for (let c = 0; c < r.numberOfChannels; c++) for (const v of r.getChannelData(c)) { const a = Math.abs(v); p = Math.max(p, a); if (a > 1) over++; }
    out[name] = { peak_dbfs: Math.round(200 * Math.log10(Math.max(p, 1e-9))) / 10, clipped_samples: over };
  }
  return out;
}"""


def run() -> dict:
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(ROOT))
    from tests.test_m4_avatar import _serve
    from tools.automation_eval import browser_path

    index = json.loads((ROOT / "ui" / "public" / "sfx" / "index.json").read_text())["cues"]
    cues = {c for beats in SCENES.values() for _, c, _, _ in beats}
    files = [f for c in cues for f in index.get(c, [])]
    srv = _serve()
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=browser_path())
            p = b.new_page()
            p.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo")
            res = {"without_limiter": p.evaluate(JS, {"scenes": SCENES, "files": files, "limiter": False}),
                   "with_limiter": p.evaluate(JS, {"scenes": SCENES, "files": files, "limiter": True})}
            b.close()
    finally:
        srv.shutdown()
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    r = run()
    for scene in SCENES:
        w, l = r["without_limiter"][scene], r["with_limiter"][scene]
        print(f"{scene:24s} no limiter: {w['peak_dbfs']:6.1f} dBFS, {w['clipped_samples']:6d} clipped | "
              f"limiter: {l['peak_dbfs']:6.1f} dBFS, {l['clipped_samples']} clipped")
    if a.json:
        Path(a.json).write_text(json.dumps(r, indent=1))

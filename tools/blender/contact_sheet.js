// Contact sheets of Monkey's clips, rendered by the real app renderer (three.js) from the demo build.
//   node tools/blender/contact_sheet.js --models monkey.glb,rt.glb --clips idle,wave --frames 4 --out sheet.png
// Needs `npm run build` in ui/ and ui/dist served on --port (default 8765), with the models in ui/dist/models.
const { chromium } = require("playwright");
const fs = require("fs");

const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > 0 ? process.argv[i + 1] : d; };
const models = arg("models", "monkey.glb").split(",");
const clips = arg("clips", "idle").split(",");
const frames = Number(arg("frames", "4"));
const out = arg("out", "sheet.png");
const port = arg("port", "8765");
const query = arg("query", "");           // extra URL params, e.g. "tm=aces"
const size = Number(arg("size", "260"));
// --crop x,y,w,h (fractions of the frame) for close-ups, e.g. 0.05,0.15,0.5,0.45 = his right shoulder/arm
const crop = arg("crop", "") ? arg("crop").split(",").map(Number) : null;
const vw = crop ? 840 : 420, vh = crop ? 1040 : 520;

(async () => {
  const browser = await chromium.launch();
  const cells = [];
  for (const m of models) {
    const page = await browser.newPage({ viewport: { width: vw, height: vh } });
    // Avatar alone, filling the window (the camera frames him to the host size at load).
    await page.addInitScript(() => document.addEventListener("DOMContentLoaded", () => {
      const st = document.createElement("style");
      st.textContent = "#avatar{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;" +
        "z-index:9999;background:#2b6b3a!important;visibility:visible!important} #avatar *{visibility:visible!important} body *{visibility:hidden}";
      document.head.appendChild(st);
    }));
    const errs = [];
    page.on("pageerror", (e) => errs.push(String(e)));
    await page.goto(`http://localhost:${port}/index.html?demo&model=${m}${query ? "&" + query : ""}`);
    await page.waitForFunction(() => window.__monkeyAvatar?.ready, null, { timeout: 60000 });
    const durations = await page.evaluate(() => Object.fromEntries([
      ...[...window.__monkeyAvatarObj.actions].map(([k, a]) => [k, a.getClip().duration]),
      ...[...window.__monkeyAvatarObj.gestures].map(([k, a]) => ["talk_gest_" + k, a.getClip().duration])]));
    for (const c of clips) {
      const d = durations[c];
      for (let i = 0; i < frames; i++) {
        let img = null;
        if (d !== undefined) {
          const t = frames === 1 ? 0 : (d * i) / (frames - 1);
          await page.evaluate(([c, t]) => window.__monkeyAvatarObj.poseAt(c, t), [c, t]);
          await page.waitForTimeout(150);
          img = (await page.screenshot(crop ? { clip: { x: crop[0] * vw, y: crop[1] * vh, width: crop[2] * vw, height: crop[3] * vh } } : {})).toString("base64");
        }
        cells.push({ m, c, i, img, t: d === undefined ? "missing" : ((d * i) / Math.max(1, frames - 1)).toFixed(2) + "s" });
      }
    }
    if (errs.length) console.error(m, errs);
    await page.close();
  }
  // Rows = model x clip, columns = frames.
  const page = await browser.newPage({ viewport: { width: 140 + frames * size, height: 400 } });
  const rows = [];
  for (const m of models) for (const c of clips) rows.push({ m, c, cells: cells.filter((x) => x.m === m && x.c === c) });
  await page.setContent(`<body style="margin:0;background:#173d22;font:13px sans-serif;color:#eee">
    ${rows.map((r) => `<div style="display:flex;align-items:center">
      <div style="width:140px;padding:4px"><b>${r.c}</b><br>${r.m}</div>
      ${r.cells.map((x) => x.img ? `<div style="position:relative"><img src="data:image/png;base64,${x.img}" style="width:${size}px;height:${Math.round(size * (crop ? crop[3] * vh / (crop[2] * vw) : 520 / 420))}px;object-fit:cover"><span style="position:absolute;left:4px;top:2px">${x.t}</span></div>`
        : `<div style="width:${size}px">missing</div>`).join("")}
    </div>`).join("")}</body>`);
  await page.screenshot({ path: out, fullPage: true });
  await browser.close();
  console.log("wrote", out);
})();

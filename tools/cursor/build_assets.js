// Builds the banana cursor's derived assets from the ONE source geometry (monkey/automation/cursor/banana.svg):
//   * measures the hotspot (the sharp tip) from the rendered alpha, writes manifest.json
//   * transparent PNGs per state and size (used by the Windows desktop overlay), and a contact sheet
// Run:  node tools/cursor/build_assets.js     (needs Playwright + Chromium; set PW_CHROMIUM to a binary if needed)
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const DIR = path.join(ROOT, "monkey/automation/cursor");
const svg = fs.readFileSync(path.join(DIR, "banana.svg"), "utf8");
const js = fs.readFileSync(path.join(DIR, "banana_cursor.js"), "utf8");
const VB = 128;

(async () => {
  const exe = process.env.PW_CHROMIUM || (fs.existsSync("/opt/pw-browsers/chromium") ? "/opt/pw-browsers/chromium" : undefined);
  const b = await chromium.launch(exe ? { executablePath: exe } : {});
  const p = await b.newPage({ viewport: { width: 1200, height: 700 }, deviceScaleFactor: 1 });

  // 1. Hotspot: the opaque pixel that sticks out furthest toward the top-left (min x + y) at 1024 px.
  await p.setContent(`<body style="margin:0;background:transparent">${svg.replace(/width="128" height="128"/, 'width="1024" height="1024"')}</body>`);
  const shot = await p.screenshot({ clip: { x: 0, y: 0, width: 300, height: 300 }, omitBackground: true });
  const tip = await p.evaluate(async (b64) => {
    const img = new Image(); img.src = "data:image/png;base64," + b64; await img.decode();
    const c = document.createElement("canvas"); c.width = img.width; c.height = img.height;
    const g = c.getContext("2d"); g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    let best = null;
    for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) {
      if (d[(y * c.width + x) * 4 + 3] < 128) continue;
      if (!best || x + y < best.x + best.y) best = { x, y };
    }
    return best;
  }, shot.toString("base64"));
  const hotspot = [+(tip.x / 8 + 0.5 / 8).toFixed(2), +(tip.y / 8 + 0.5 / 8).toFixed(2)];

  // 2. Transparent PNGs per state and size, rendered by the real controller (same code the app uses).
  const out = path.join(DIR, "png");
  fs.mkdirSync(out, { recursive: true });
  const states = { default: [], hover: ["hover"], pressed: ["press"], busy: ["busy"] };
  const sizes = [32, 48, 64, 96];
  for (const [name, actions] of Object.entries(states)) {
    for (const px of sizes) {
      const scale = px / 48, pad = Math.round(px * 0.6), W = px + pad * 2;
      await p.setContent(`<body style="margin:0;background:transparent"><div id="h" style="position:relative;width:${W}px;height:${W}px"></div>
        <script>${js}</script></body>`);
      await p.evaluate(({ svg, hotspot, scale, pad, actions }) => {
        const c = window.MonkeyBananaCursor.create({ host: document.getElementById("h"), svg, hotspot });
        c.configure({ scale, glow: 0.8, motion: "reduced" });
        c.moveTo(pad + 4, pad + 4);
        if (actions.includes("hover")) c.hover("button");
        if (actions.includes("press")) c.press();
        if (actions.includes("busy")) { c.setState("busy"); }
      }, { svg, hotspot, scale, pad, actions });
      await p.waitForTimeout(250);
      await p.screenshot({ path: path.join(out, `${name}_${px}.png`), clip: { x: 0, y: 0, width: W, height: W }, omitBackground: true });
    }
  }

  const manifest = {
    source: "banana.svg (original low-poly vector; one geometry for every state)",
    viewBox: VB, hotspot, hotspotNote: "pointer tip in viewBox units; the tip is drawn exactly on the action coordinate",
    pngs: Object.fromEntries(Object.keys(states).map((s) => [s, sizes.map((px) => {
      const pad = Math.round(px * 0.6);
      return { file: `png/${s}_${px}.png`, size: px, tip: [pad + 4, pad + 4] };
    })])),
    timings: { press_ms: 70, release_ms: 110, ripple_ms: 320, glow_in_ms: 130, glow_out_ms: 170 },
    palette: { pointer: "#fff7dc", peel: "#fde8a2", fruit: "#ffd21c", stem: "#8e5426", edge: "#4d2b0f", glow: "#ffd60a" },
  };
  fs.writeFileSync(path.join(DIR, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  console.log("hotspot", hotspot, "pngs", Object.keys(states).length * sizes.length);
  await b.close();
})();

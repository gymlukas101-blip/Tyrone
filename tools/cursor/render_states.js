// Renders the four states from the REAL runtime controller (banana_cursor.js + the active base asset), transparent.
// node tools/cursor/render_states.js OUT_DIR [PX]
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

(async () => {
  const out = process.argv[2], px = Number(process.argv[3] || 256);
  const D = path.resolve(__dirname, "../../monkey/automation/cursor");
  const svg = fs.readFileSync(path.join(D, "banana.svg"), "utf8");
  const js = fs.readFileSync(path.join(D, "banana_cursor.js"), "utf8");
  const man = JSON.parse(fs.readFileSync(path.join(D, "manifest.json"), "utf8"));
  const sprite = man.sprite && fs.existsSync(path.join(D, man.sprite.file))
    ? { ...man.sprite, src: "data:image/png;base64," + fs.readFileSync(path.join(D, man.sprite.file)).toString("base64") } : null;
  const exe = process.env.PW_CHROMIUM || (fs.existsSync("/opt/pw-browsers/chromium") ? "/opt/pw-browsers/chromium" : undefined);
  const b = await chromium.launch(exe ? { executablePath: exe } : {});
  const p = await b.newPage({ viewport: { width: px * 2, height: px * 2 }, deviceScaleFactor: 1 });
  for (const state of ["default", "hover", "click", "busy"]) {
    await p.setContent(`<body style="margin:0;background:transparent"><div id="h" style="position:relative;width:${px * 2}px;height:${px * 2}px"></div><script>${js}</script></body>`);
    await p.evaluate(({ svg, sprite, hot, px, state }) => {
      const c = MonkeyBananaCursor.create({ host: document.getElementById("h"), svg, sprite, hotspot: hot });
      c.configure({ scale: px / 48, glow: 0.85, motion: "full" });
      c.moveTo(px * 0.45, px * 0.4);
      if (state === "hover") c.hover("button");
      if (state === "click") { c.press(); setTimeout(() => c.release(), 20); }
      if (state === "busy") c.setState("busy");
    }, { svg, sprite, hot: man.hotspot, px, state });
    await p.waitForTimeout(state === "click" ? 120 : 300);
    await p.screenshot({ path: path.join(out, `${state}.png`), omitBackground: true });
  }
  await b.close();
})();

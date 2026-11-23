// Font pairing comparison for the to-do panel (prototype page; not part of the app build).
// Renders the real panel (renderTodos) once per pairing and measures each face: x-height, cap height, width,
// tabular figures, and how much contrast the glyphs actually reach when rendered small on the panel's background.
import "@fontsource/lilita-one/latin-400.css";
import "@fontsource/titan-one/latin-400.css";
import "@fontsource/luckiest-guy/latin-400.css";
import "@fontsource/bungee/latin-400.css";
import "@fontsource/rowdies/latin-400.css";
import "@fontsource-variable/nunito/wght.css";
import "@fontsource-variable/fredoka/wght.css";
import "@fontsource-variable/baloo-2/wght.css";
import "@fontsource-variable/lexend/wght.css";
import "@fontsource-variable/atkinson-hyperlegible-next/wght.css";
import "../../src/style.css";
import "../../src/game.css";
import "../../src/theme-blocky.css";
import { h } from "../../src/dom";
import { renderTodos, type Todo } from "../../src/todo";

interface Pair { id: string; name: string; display: string; text: string; lic: string; why: string }
const PAIRS: Pair[] = [
  { id: "lilita-nunito", name: "Lilita One + Nunito", display: "Lilita One", text: "Nunito Variable",
    lic: "OFL 1.1 + OFL 1.1", why: "Today's display face, plus a rounded text face with open counters." },
  { id: "titan-nunito", name: "Titan One + Nunito", display: "Titan One", text: "Nunito Variable",
    lic: "OFL 1.1 + OFL 1.1", why: "Rounder, chunkier 'toy block' display face; same rounded text face." },
  { id: "titan-fredoka", name: "Titan One + Fredoka", display: "Titan One", text: "Fredoka Variable",
    lic: "OFL 1.1 + OFL 1.1", why: "Both faces fully rounded: the most toy-like pair." },
  { id: "luckiest-baloo", name: "Luckiest Guy + Baloo 2", display: "Luckiest Guy", text: "Baloo 2 Variable",
    lic: "Apache 2.0 + OFL 1.1", why: "Comic-book display caps with a soft, tall-x-height text face." },
  { id: "bungee-lexend", name: "Bungee + Lexend", display: "Bungee", text: "Lexend Variable",
    lic: "OFL 1.1 + OFL 1.1", why: "Blocky signage caps (the most 'voxel') with a reading-proficiency text face." },
  { id: "rowdies-atkinson", name: "Rowdies + Atkinson Hyperlegible Next", display: "Rowdies", text: "Atkinson Hyperlegible Next Variable",
    lic: "OFL 1.1 + OFL 1.1", why: "Heavy rounded display with the most legibility-engineered text face (low-vision research)." },
];
const CHOSEN = "titan-nunito";
const TEXT_FONTS = ["Nunito Variable", "Fredoka Variable", "Baloo 2 Variable", "Lexend Variable", "Atkinson Hyperlegible Next Variable", "system-ui"];
const DISPLAY_FONTS = ["Lilita One", "Titan One", "Luckiest Guy", "Bungee", "Rowdies"];

// ---------------------------------------------------------------- sample data (same shape as the demo bridge)
const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date, time = true) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` + (time ? `T${pad(d.getHours())}:${pad(d.getMinutes())}` : "");
const day = (n: number, hh = 17, mm = 0) => { const d = new Date(); d.setDate(d.getDate() + n); d.setHours(hh, mm, 0, 0); return d; };
const now = Date.now() / 1000;
const ITEMS: Todo[] = [
  { id: "t1", text: "Email Prof. Kim about the lab makeup", notes: "", due: iso(day(-1)), priority: "high", list: "school",
    status: "open", steps: [], source: "voice", created: now - 9e4, done_at: null },
  { id: "t2", text: "Pick up package at the post office", notes: "Before the counter closes", due: iso(day(0, 18, 30)), priority: "normal",
    list: "", status: "open", steps: [], source: "typed", created: now - 5e4, done_at: null },
  { id: "t3", text: "Finish CS 400 project proposal", notes: "", due: iso(day(3), false), priority: "high", list: "school", status: "open",
    steps: [{ text: "Re-read the rubric", done: true }, { text: "Outline the three sections", done: false }, { text: "Write the first draft", done: false }],
    source: "Monkey", created: now - 4e4, done_at: null },
  { id: "t4", text: "Call the dentist to book a cleaning", notes: "", due: null, priority: "low", list: "", status: "open", steps: [],
    source: "typed", created: now - 3e4, done_at: null },
  { id: "t5", text: "Renew bus pass", notes: "", due: iso(day(-2), false), priority: "normal", list: "", status: "done", steps: [],
    source: "typed", created: now - 2e5, done_at: now - 7e4 },
  { id: "t6", text: "Return 11 library books (0 overdue fees)", notes: "", due: iso(day(-3), false), priority: "low", list: "", status: "done", steps: [],
    source: "typed", created: now - 3e5, done_at: now - 9e4 },
];
const fakeApi: any = new Proxy({}, { get: () => async () => ({ ok: true, items: ITEMS, settings: { reminders: true, speak: false } }) });

function panel(tab: "open" | "done") {
  const c = h("div", { class: "card" },
    h("button", { class: "close", title: "Close", "aria-label": "Close To-do" }, "✕"),
    h("h3", { "aria-level": "2" }, h("button", { type: "button", class: "cardtitle" }, "📝 To-do")));
  const host = h("div", { id: "cards" }, c);
  document.body.append(host);
  renderTodos(c, fakeApi, { items: ITEMS.map((t) => ({ ...t, steps: t.steps.map((s) => ({ ...s })) })) }, { celebrate() {}, ask() {} }, tab);
  const clone = c.cloneNode(true) as HTMLElement;
  host.remove();
  return clone;
}

// ---------------------------------------------------------------- measurements
const SAMPLE = "Email Prof. Kim about the lab makeup · due Tue 5:00 PM";
function faceMetrics(family: string, weight: number) {
  const ctx = document.createElement("canvas").getContext("2d")!;
  ctx.font = `${weight} 100px "${family}"`;
  const xh = ctx.measureText("x").actualBoundingBoxAscent / 100;
  const cap = ctx.measureText("H").actualBoundingBoxAscent / 100;
  const em = ctx.measureText(SAMPLE).width / SAMPLE.length / 100;
  const span = (txt: string, tnum: boolean) => {
    const s = h("span", { style: `font: ${weight} 40px "${family}"; position:absolute; visibility:hidden; white-space:pre;` +
      (tnum ? "font-variant-numeric: tabular-nums;" : "") }, txt);
    document.body.append(s); const w = s.getBoundingClientRect().width; s.remove(); return w;
  };
  const tnum = Math.abs(span("1111", true) - span("0000", true)) < 0.5;
  return { xh, cap, em, tnum };
}

const hex = (c: string) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
const lin = (v: number) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
const lum = ([r, g, b]: number[]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const ratio = (a: number, b: number) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);

/** Render a line small on the real background and measure the contrast the glyph pixels reach. Thin strokes at
 *  12 px are mostly anti-aliased edge pixels, so a light face loses effective contrast that a sturdier one keeps. */
function renderedContrast(family: string, weight: number, px: number, dpr: number, fg: string, bg: string) {
  const cv = document.createElement("canvas"), ctx = cv.getContext("2d", { willReadFrequently: true })!;
  const font = `${weight} ${px * dpr}px "${family}"`;
  ctx.font = font;
  cv.width = Math.ceil(ctx.measureText(SAMPLE).width) + 8; cv.height = Math.ceil(px * dpr * 1.8);
  ctx.fillStyle = bg; ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.font = font; ctx.fillStyle = fg; ctx.textBaseline = "middle"; ctx.fillText(SAMPLE, 4, cv.height / 2);
  const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
  const Lb = lum(hex(bg)), Lf = lum(hex(fg)), full = ratio(Lf, Lb);
  const cs: number[] = [];
  let solid = 0;
  for (let i = 0; i < d.length; i += 4) {
    const L = lum([d[i], d[i + 1], d[i + 2]]);
    const cover = (L - Lb) / (Lf - Lb);
    if (cover < 0.1) continue;                        // background
    const c = ratio(L, Lb);
    cs.push(c);
    if (c >= 4.5) solid++;
  }
  cs.sort((a, b) => a - b);
  return { full, p90: cs[Math.floor(cs.length * 0.9)] ?? 0, solid: cs.length ? solid / cs.length : 0, ink: cs.length / (dpr * dpr) };
}

// ---------------------------------------------------------------- page
const results: Record<string, any> = {};
async function main() {
  await Promise.all([...DISPLAY_FONTS.map((f) => document.fonts.load(`400 20px "${f}"`)),
    ...TEXT_FONTS.filter((f) => f !== "system-ui").flatMap((f) => [500, 600, 700].map((w) => document.fonts.load(`${w} 20px "${f}"`)))]);
  await document.fonts.ready;

  const pairsEl = document.getElementById("pairs")!;
  for (const p of PAIRS) {
    const open = panel("open"), done = panel("done");
    done.classList.add("done-only");
    const tm = faceMetrics(p.text, 700), dm = faceMetrics(p.display, 400);
    const box = h("section", { class: `pair ${p.id === CHOSEN ? "chosen" : ""}`, id: p.id },
      h("header", {}, h("b", { style: `font-family:"${p.display}"` }, p.name, p.id === CHOSEN ? h("span", { class: "badge" }, "PICK") : null),
        h("small", {}, `${p.lic}. ${p.why}`)),
      open, done,
      h("div", { class: "specimen" },
        h("span", { class: "big", style: `font-family:"${p.display}"` }, "ALL CLEAR!"),
        h("span", { class: "num", style: `font-family:"${p.display}"` }, "12 · 3/5 · 0"),
        h("button", { type: "button", class: "primary", style: `font-family:"${p.display}"` }, "Add"),
        h("button", { type: "button", class: "ghost", style: `font-family:"${p.display}"` }, "Help me do this")),
      h("table", { class: "m" },
        h("tr", {}, h("th", {}, ""), h("th", {}, "x-height"), h("th", {}, "cap"), h("th", {}, "x/cap"), h("th", {}, "width/char"), h("th", {}, "tabular 0-9")),
        h("tr", {}, h("td", {}, `Text: ${p.text.replace(" Variable", "")}`), h("td", {}, tm.xh.toFixed(3)), h("td", {}, tm.cap.toFixed(3)),
          h("td", {}, (tm.xh / tm.cap).toFixed(2)), h("td", {}, `${tm.em.toFixed(3)} em`), h("td", {}, tm.tnum ? "yes" : "no")),
        h("tr", {}, h("td", {}, `Display: ${p.display}`), h("td", {}, dm.xh.toFixed(3)), h("td", {}, dm.cap.toFixed(3)),
          h("td", {}, (dm.xh / dm.cap).toFixed(2)), h("td", {}, `${dm.em.toFixed(3)} em`), h("td", {}, dm.tnum ? "yes" : "no"))));
    for (const card of [open, done]) {
      card.style.setProperty("--display", `"${p.display}"`);
      card.style.setProperty("--text-font", `"${p.text}", system-ui, sans-serif`);
      card.style.fontFamily = "var(--text-font)";
    }
    pairsEl.append(box);
  }

  // Small sizes: every text face at 12/14/16 px, weight as used in the panel.
  const sizes = document.getElementById("sizes")!;
  for (const f of TEXT_FONTS) {
    const fm = faceMetrics(f, 700);
    const rc: Record<string, any> = {};
    for (const px of [12, 14, 16]) for (const dpr of [1, 2]) {
      rc[`${px}@${dpr}x text`] = renderedContrast(f, 700, px, dpr, "#f6ffe9", "#0b4321");
      rc[`${px}@${dpr}x muted`] = renderedContrast(f, 600, px, dpr, "#b5e3a8", "#0b4321");
      rc[`${px}@${dpr}x muted700`] = renderedContrast(f, 700, px, dpr, "#b5e3a8", "#0b4321");
      rc[`${px}@${dpr}x text800`] = renderedContrast(f, 800, px, dpr, "#f6ffe9", "#0b4321");
    }
    results[f] = { ...fm, rendered: rc };
    sizes.append(h("div", { class: "sz", "data-font": f },
      h("div", { class: "lbl" }, h("b", {}, f.replace(" Variable", "")), h("br", {}),
        `x-height ${fm.xh.toFixed(3)} em · 12px muted line: ${(rc["12@1x muted"].solid * 100).toFixed(0)}% of ink ≥ 4.5:1 at 1x`),
      h("div", { class: "lines" }, ...[12, 14, 16].flatMap((px) => [
        h("div", { style: `font: 700 ${px}px "${f}"` }, `${px}px · Email Prof. Kim about the lab makeup  Il1 O0 rn m 3/5`),
        h("div", { class: "muted", style: `font: 600 ${px}px "${f}"; font-variant-numeric: tabular-nums` },
          `${px}px · overdue · was due Mon, Nov 23, 5:00 PM · 10/12 steps`)]))));
  }
  for (const f of DISPLAY_FONTS) results[f] = faceMetrics(f, 400);

  // Contrast of every text/background pair the panel uses (font-independent WCAG 2 ratios).
  const pairs: [string, string, string, string][] = [
    ["Task title", "#f6ffe9", "#0b4321", "row"],
    ["Due line / steps (muted)", "#b5e3a8", "#0b4321", "row"],
    ["Hint text (muted) on panel top", "#b5e3a8", "#14713a", "panel gradient top"],
    ["Hint text (muted) on panel bottom", "#b5e3a8", "#0d5229", "panel gradient bottom"],
    ["OVERDUE flag", "#ffffff", "#c8102e", "flag"],
    ["Button label (ink) on banana", "#14240f", "#ffd43b", "Add / tab on"],
    ["Tab label (white) on leaf button", "#ffffff", "#1f7a3c", "tab off"],
    ["Header outline (ink) on header strip", "#14240f", "#1fae49", "h3 strip"],
    ["Headline (white) with ink outline vs panel", "#14240f", "#14713a", "outline vs panel"],
  ];
  results.wcag = pairs.map(([name, fg, bg]) => ({ name, fg, bg, ratio: ratio(lum(hex(fg)), lum(hex(bg))) }));
  document.getElementById("contrast")!.append(h("table", {},
    h("tr", {}, h("th", {}, "Text"), h("th", {}, "Sample"), h("th", {}, "WCAG 2 ratio"), h("th", {}, "Needs")),
    ...results.wcag.map((r: any) => h("tr", {}, h("td", {}, r.name),
      h("td", {}, h("span", { class: "swatch", style: `color:${r.fg};background:${r.bg}` }, "Due Tue 5:00 PM")),
      h("td", {}, `${r.ratio.toFixed(2)} : 1`), h("td", {}, r.ratio >= 4.5 ? "AA ✓" : r.ratio >= 3 ? "AA large / outline only" : "decorative")))),
    h("p", {}, "Rendered contrast per face (the share of glyph pixels that reach 4.5:1 when drawn small) is in the strip labels above " +
      "and in window.__fontMetrics; thin faces lose it at 12 px even though their nominal color ratio is the same."));

  document.getElementById("verdict")!.innerHTML = VERDICT;
  (window as any).__fontMetrics = results;
  (window as any).__fontsReady = true;
}

const VERDICT = `<p><b>Titan One</b> (display) + <b>Nunito</b> (text), both SIL OFL 1.1. See <code>docs/ui/TODO-FONTS.md</code> for the
numbers and the reasons; in short: Titan One's soft, heavy, rounded block letters read as a chunky toy at 15–30 px and stay
legible at the 12–14 px of tabs and badges, while Nunito's rounded terminals match it and its x-height, open counters,
distinct I/l/1 and tabular figures keep task titles and due dates readable down to 12 px.</p>`;

void main();

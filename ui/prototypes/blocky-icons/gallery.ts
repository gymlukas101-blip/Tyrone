// Blocky icon gallery: every UI icon as a procedural toy-block model, four build approaches side by side, three
// background prototypes, and live measurements (window.__blockyStats) for docs/ui/BLOCKY_ICONS.md.
import "../../src/theme-blocky.css";
import "./gallery.css";
import type { Clip } from "../../src/blocky/anim";
import { type Sheet, bakeSheet, bakeTile } from "../../src/blocky/bake";
import { BACKGROUNDS, INVENTORY } from "../../src/blocky/icons";
import { THREE, block, slab } from "../../src/blocky/kit";
import { play, release } from "../../src/blocky/sprite";
import { Live } from "./live";

const $ = (id: string) => document.getElementById(id)!;
const el = (tag: string, cls = "", html = "") => { const e = document.createElement(tag); if (cls) e.className = cls; if (html) e.innerHTML = html; return e; };
const stats: Record<string, any> = { approaches: {} };
(window as any).__blockyStats = stats;

const live = new Live();
const COMPARE = ["checked", "trash", "banana", "gear"];

// ---------------------------------------------------------------- the CSS / layered-SVG approach (hand drawn)
const lay = (face: string, side: string, d: string, extra = "") => `
  <g stroke="#14240f" stroke-width="5" stroke-linejoin="round">
    <path d="${d}" fill="${side}" transform="translate(0 8)"/>
    <path d="${d}" fill="${face}"/>
  </g>
  <path d="${d}" fill="none" stroke="#fff" stroke-opacity=".45" stroke-width="4" stroke-dasharray="40 400" stroke-linecap="round" transform="translate(2 3) scale(.97)"/>
  ${extra}`;
const SVG: Record<string, string> = {
  checked: lay("#ffd43b", "#c98f00", "M26 12 H74 Q88 12 88 26 V70 Q88 84 74 84 H26 Q12 84 12 70 V26 Q12 12 26 12 Z",
    `<path d="M28 50 L43 64 L72 32" fill="none" stroke="#14240f" stroke-width="17" stroke-linecap="round" stroke-linejoin="round"/>
     <path d="M28 50 L43 64 L72 32" fill="none" stroke="#1e7a2e" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>`),
  trash: lay("#3cc24a", "#1e7a2e", "M24 30 H76 L71 86 Q70 90 66 90 H34 Q30 90 29 86 Z",
    `<g class="lid" stroke="#14240f" stroke-width="5" stroke-linejoin="round"><rect x="14" y="16" width="72" height="14" rx="6" fill="#7ee07f"/>
     <path d="M40 16 V10 H60 V16" fill="none"/></g><path d="M40 42 V78 M50 42 V78 M60 42 V78" stroke="#1e7a2e" stroke-width="5" stroke-linecap="round"/>`),
  banana: lay("#ffd43b", "#c98f00", "M22 18 Q30 12 34 20 Q40 60 82 70 Q90 74 84 82 Q40 92 22 46 Q18 30 22 18 Z",
    `<rect x="22" y="10" width="10" height="12" rx="3" fill="#6b3f1d" stroke="#14240f" stroke-width="4"/>`),
  gear: lay("#ffd43b", "#c98f00",
    "M44 6 H56 L58 18 L68 22 L78 14 L86 22 L78 32 L82 42 L94 44 V56 L82 58 L78 68 L86 78 L78 86 L68 78 L58 82 L56 94 H44 L42 82 L32 78 L22 86 L14 78 L22 68 L18 58 L6 56 V44 L18 42 L22 32 L14 22 L22 14 L32 22 L42 18 Z",
    `<circle cx="50" cy="50" r="13" fill="#c98f00" stroke="#14240f" stroke-width="5"/>`),
};
function svgIcon(id: string) {
  const wrap = el("div", "slot");
  wrap.innerHTML = `<svg class="svgicon" viewBox="-4 -4 108 112" aria-hidden="true">${SVG[id]}</svg>`;
  const s = wrap.firstElementChild as SVGElement;
  const restart = (c: string) => { s.classList.remove("hover", "pop"); void s.getBoundingClientRect(); s.classList.add(c); };
  wrap.addEventListener("pointerenter", () => restart("hover"));
  wrap.addEventListener("pointerdown", () => s.classList.add("press"));
  wrap.addEventListener("pointerup", () => s.classList.remove("press"));
  wrap.addEventListener("pointerleave", () => s.classList.remove("press"));
  wrap.addEventListener("click", () => restart("pop"));
  return wrap;
}

// ---------------------------------------------------------------- baked sprite cells
function spriteSlot(sheet: Sheet, id: string, size: number) {
  const s = el("div", "slot bi-slot");
  const row = sheet.map[id].row;
  Object.assign(s.style, { width: `${size}px`, height: `${size}px`, backgroundImage: `url("${sheet.url}")`,
    backgroundSize: `${sheet.cols * size}px ${sheet.rows * size}px`, backgroundPosition: `0 ${-row * size}px` });
  const go = (c: Clip) => void play(s, sheet, id, c);
  s.addEventListener("pointerenter", () => go("hover"));
  s.addEventListener("pointerdown", () => go("press"));
  s.addEventListener("pointerup", () => release(s));
  s.addEventListener("click", () => go("pop"));
  return s;
}

// ---------------------------------------------------------------- Blender sprites (rendered offline by tools/blender/blocky_icons.py)
async function blenderSlot(id: string) {
  const cell = el("div", "slot bi-slot");
  try {
    const meta = await (await fetch(`./blender/${id}.json`)).json() as { frames: number; cell: number; ms: number; bytes: number; render_s: number };
    const size = 96;
    Object.assign(cell.style, { width: `${size}px`, height: `${size}px`, backgroundImage: `url("./blender/${id}.webp")`,
      backgroundSize: `${meta.frames * size}px ${size}px` });
    cell.addEventListener("click", () => cell.animate([{ backgroundPositionX: "0px" }, { backgroundPositionX: `${-(meta.frames - 1) * size}px` }],
      { duration: meta.ms, easing: `steps(${meta.frames - 1}, jump-none)` }));
    cell.addEventListener("pointerenter", () => cell.click());
    stats.blender = { ...(stats.blender ?? {}), [id]: meta };
    return cell;
  } catch {
    return el("div", "missing", "not rendered<br>(needs bpy)");
  }
}

// ---------------------------------------------------------------- page
async function main() {
  await document.fonts.ready;
  // 1. approach comparison
  const cmp = $("compare");
  cmp.append(el("div"), ...[["Live 3D", "one shared WebGL canvas"], ["Baked sprites", "three.js once → sheet"], ["CSS + layered SVG", "no WebGL"],
    ["Blender (offline)", "pre-rendered PNG strips"]].map(([a, b]) => el("div", "hd", `${a}<small>${b}</small>`)));
  const tb = performance.now();
  const cmpSheet = await bakeSheet(COMPARE.map((id) => ({ id, clips: ["hover", "press", "pop"] as Clip[] })), 96, Math.min(2, devicePixelRatio));
  stats.approaches.baked = { icons: COMPARE.length, cell: 96, ms: Math.round(performance.now() - tb), bytes: cmpSheet.bytes, frames: cmpSheet.frames,
    px: [cmpSheet.cols * 96 * cmpSheet.dpr, cmpSheet.rows * 96 * cmpSheet.dpr] };
  for (const id of COMPARE) {
    const a = el("div", "cell"), slot = el("div", "slot"); a.append(slot); live.add(slot, id);
    const b = el("div", "cell"); b.append(spriteSlot(cmpSheet, id, 96));
    const c = el("div", "cell"); c.append(svgIcon(id));
    const d = el("div", "cell"); d.append(await blenderSlot(id));
    cmp.append(el("div", "rowname", INVENTORY.find((i) => i.id === id)?.name ?? id), a, b, c, d);
  }
  stats.approaches.svg = { bytes: COMPARE.reduce((n, id) => n + SVG[id].length, 0) };

  // 2. inventory
  $("count").textContent = `${INVENTORY.length} icons, ${BACKGROUNDS.length} backgrounds`;
  const inv = $("inventory");
  const groups = [...new Set(INVENTORY.map((i) => i.group))];
  const invSlots: { slot: HTMLElement; id: string; group: string }[] = [];
  for (const g of groups) {
    inv.append(el("h3", "", g));
    const box = el("div", "inv-group");
    for (const it of INVENTORY.filter((i) => i.group === g)) {
      const card = el("div", "inv"), slot = el("div", "slot");
      card.append(slot, el("div", "g", it.glyph), el("b", "", it.name), el("small", "", it.where));
      box.append(card);
      invSlots.push({ slot, id: it.id, group: g });
    }
    inv.append(box);
  }
  const liveItems = invSlots.map(({ slot, id }) => live.add(slot, id));

  // Baked mode: per-group sheets (whole inventory in one sheet would be a huge bitmap).
  let bakedSheets: Record<string, Sheet> | null = null;
  async function setMode(mode: string) {
    if (mode === "baked" && !bakedSheets) {
      const t = performance.now();
      bakedSheets = {};
      for (const g of groups) {
        bakedSheets[g] = await bakeSheet(INVENTORY.filter((i) => i.group === g).map((i) => ({ id: i.id, clips: ["hover", "press", "pop"] as Clip[] })), 80, Math.min(2, devicePixelRatio));
      }
      const all = Object.values(bakedSheets);
      stats.inventoryBake = { icons: INVENTORY.length, ms: Math.round(performance.now() - t), bytes: all.reduce((n, s) => n + s.bytes, 0),
        frames: all.reduce((n, s) => n + s.frames, 0), sheets: all.length };
    }
    invSlots.forEach(({ slot, id, group }, i) => {
      const keep = slot.parentElement!;
      if (mode === "baked") {
        liveItems[i].visible = false;
        const s = spriteSlot(bakedSheets![group], id, 80);
        keep.replaceChild(s, slot); invSlots[i].slot = s;
      } else if (!liveItems.includes(liveItems[i]) || slot.classList.contains("bi-slot")) {
        keep.replaceChild(liveItems[i].el, slot); invSlots[i].slot = liveItems[i].el;
      }
    });
    live.kick();
  }
  document.querySelectorAll<HTMLInputElement>("input[name=mode]").forEach((r) => r.addEventListener("change", () => void setMode(r.value)));
  ($("idle") as HTMLInputElement).addEventListener("change", (e) => { live.idle = (e.target as HTMLInputElement).checked; live.kick(); });

  if (/[?&]baked\b/.test(location.search)) {            // ?baked: start in sprite mode (full-page screenshots)
    document.querySelector<HTMLInputElement>("input[value=baked]")!.checked = true;
    await setMode("baked");
  }

  // 3. backgrounds
  await backgrounds();
  live.kick();
  setInterval(() => {
    const s = live.stats();
    $("stats").textContent = `live: ${s.visible}/${s.total} on screen · frame CPU p50 ${s.p50.toFixed(2)} ms · p95 ${s.p95.toFixed(2)} ms`;
    stats.live = s;
  }, 500);
  fillMeasure();
  stats.ready = true;
}

const PIECES_FAR = [
  { id: "leafBlock", x: 30, y: 40, s: 0.55, rz: 0.6 }, { id: "cube", x: 150, y: 70, s: 0.35, rz: 0.3 }, { id: "leafBlock", x: 210, y: 190, s: 0.6, rz: -0.9 },
  { id: "cube", x: 70, y: 180, s: 0.3, rz: 1.1 }, { id: "leafBlock", x: 120, y: 130, s: 0.45, rz: 2.4 },
];
const PIECES_NEAR = [
  { id: "leafBlock", x: 40, y: 200, s: 0.9, rz: 0.9 }, { id: "banana", x: 190, y: 60, s: 0.42, rz: -0.4 }, { id: "leafBlock", x: 230, y: 230, s: 0.8, rz: -2.2 },
  { id: "cube", x: 120, y: 20, s: 0.42, rz: 0.5 },
];

async function backgrounds() {
  const host = $("backgrounds");
  const row = `<div class="row"><b>Email Prof. Kim about the lab makeup</b><span>overdue · was due Mon 5:00 PM</span></div>
               <div class="row"><b>Pick up package at the post office</b><span>due Today 6:30 PM</span></div>`;
  const box = (title: string, cap: string, cls = "") => { const b = el("div", `bg ${cls}`, `<div class="over"><div class="tag">${title}</div>${row}</div><div class="cap">${cap}</div>`); host.append(b); return b; };
  const parallax = (b: HTMLElement) => b.addEventListener("pointermove", (e) => {
    const r = b.getBoundingClientRect();
    b.style.setProperty("--px", `${((e.clientX - r.left) / r.width - 0.5) * 2}px`);
    b.style.setProperty("--py", `${((e.clientY - r.top) / r.height - 0.5) * 2}px`);
  });
  const layer = (b: HTMLElement, url: string, size: number, opacity: number, depth: number, t: number, dx: number) => {
    const l = el("div", "layer");
    Object.assign(l.style, { backgroundImage: `url("${url}")`, backgroundSize: `${size}px`, opacity: String(opacity) });
    l.style.setProperty("--d", String(depth)); l.style.setProperty("--t", `${t}s`); l.style.setProperty("--dx", `${dx}px`); l.style.setProperty("--dy", `${size}px`);
    b.prepend(l);
  };

  // A: baked voxel canopy tiles (three.js once) + CSS transform drift/parallax
  const t0 = performance.now();
  const far = await bakeTile({ size: 260, pieces: PIECES_FAR.map((p) => ({ ...p })) });
  const near = await bakeTile({ size: 300, pieces: PIECES_NEAR.map((p) => ({ ...p })) });
  stats.tiles = { ms: Math.round(performance.now() - t0), bytes: far.bytes + near.bytes };
  const a = box("A · Voxel canopy", `Baked once with three.js (2 tiles, ${((far.bytes + near.bytes) / 1024).toFixed(0)} KB WebP, ${stats.tiles.ms} ms); CSS transform drift + pointer parallax. Recommended.`, "drift");
  layer(a, far.url, 260, 0.16, 6, 90, 260); layer(a, near.url, 300, 0.22, 14, 60, -300); parallax(a);

  // B: layered SVG leaf blocks (no WebGL)
  const leaf = (x: number, y: number, r: number, s: number, c: string, lip: string) => `<g transform="translate(${x} ${y}) rotate(${r}) scale(${s})" stroke="#14240f" stroke-width="5" stroke-linejoin="round">
      <path d="M0 50 C18 14 78 8 100 50 C78 92 18 86 0 50 Z" fill="${lip}" transform="translate(0 10)"/><path d="M0 50 C18 14 78 8 100 50 C78 92 18 86 0 50 Z" fill="${c}"/>
      <path d="M8 50 H92" stroke="${lip}" stroke-width="5"/></g>`;
  const tile = (inner: string, n: number) => `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${n}" height="${n}" viewBox="0 0 ${n} ${n}">${inner}</svg>`)}`;
  const svgFar = tile(leaf(10, 20, 30, 0.6, "#3cc24a", "#1e7a2e") + leaf(140, 130, -40, 0.7, "#3cc24a", "#1e7a2e") + `<rect x="150" y="30" width="40" height="40" rx="10" fill="#3cc24a" stroke="#14240f" stroke-width="4"/>`, 260);
  const svgNear = tile(leaf(30, 160, 60, 1.0, "#7ee07f", "#1e7a2e") + leaf(170, 20, -20, 0.9, "#7ee07f", "#1e7a2e") + `<rect x="200" y="200" width="56" height="56" rx="14" fill="#ffd43b" stroke="#14240f" stroke-width="5"/>`, 300);
  stats.svgTiles = { bytes: svgFar.length + svgNear.length };
  const b = box("B · Layered SVG leaves", `Hand-drawn SVG tiles with a lip shadow (${((svgFar.length + svgNear.length) / 1024).toFixed(1)} KB, no WebGL); same CSS drift. Flatter.`, "drift");
  layer(b, svgFar, 260, 0.16, 6, 90, 260); layer(b, svgNear, 300, 0.2, 14, 60, -300); parallax(b);

  // C: live floating blocks in the shared renderer (30 fps cap)
  const c = box("C · Live floating blocks", "Real 3D, drawn every frame by the shared renderer (30 fps). Prettiest motion, but a constant GPU/CPU cost.");
  const target = el("div"); Object.assign(target.style, { position: "absolute", inset: "0", zIndex: "-1", opacity: "0.32" }); c.prepend(target);
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xfff6d8, 0x2a5a2a, 1.2));
  const key = new THREE.DirectionalLight(0xffffff, 2); key.position.set(-2, 3, 5); scene.add(key);
  const cam = new THREE.PerspectiveCamera(40, 1.6, 0.1, 60); cam.position.set(0, 0, 12);
  const bits = Array.from({ length: 16 }, (_, i) => {
    const m = i % 3 ? block(0.9, 0.9, 0.9, i % 2 ? 0x3cc24a : 0x7ee07f, 0.2) : slab("M0 50 C18 14 78 8 100 50 C78 92 18 86 0 50 Z", 0.2, 0x3cc24a, 0.016, 0.06);
    m.position.set((i % 8) * 2.4 - 8.4, Math.floor(i / 8) * 4 - 2 + (i % 2), -2 - (i % 4) * 2);
    scene.add(m);
    return { m, ph: i * 0.7, y: m.position.y };
  });
  live.addCustom(target, scene, cam, (t, w, h) => {
    cam.aspect = w / h; cam.updateProjectionMatrix();
    for (const bt of bits) { bt.m.rotation.set(t * 0.3 + bt.ph, t * 0.4 + bt.ph, 0); bt.m.position.y = bt.y + Math.sin(t * 0.8 + bt.ph) * 0.4; }
  });
}

function fillMeasure() {
  const s = stats.approaches, kb = (n: number) => `${(n / 1024).toFixed(1)} KB`;
  const rows = [
    ["Approach", "Look", "Runtime cost", "Bytes", "Crisp 1x/2x", "Reduced motion"],
    ["Live 3D (shared canvas)", "Best: real light/rim/outline every frame", "1 WebGL context; CPU per frame in the stats bar (all visible icons)", "≈ code only (kit + recipes)", "Yes (renders at DPR)", "Stop the loop; draw rest pose once"],
    ["Baked sprites", "Same frames as live (identical renders)", `Bake ${s.baked?.ms} ms once for ${s.baked?.icons} icons at 96 px (${s.baked?.frames} frames); then CSS steps only`, `${kb(s.baked?.bytes ?? 0)} sheet (generated, not shipped)`, "Yes (baked at DPR)", "Don't play clips; rest frame"],
    ["CSS + layered SVG", "Flat 2.5D; flips look like cards", "Style + paint only during animations", `${kb(s.svg?.bytes ?? 0)} of SVG`, "Yes (vector)", "Drop the keyframes"],
    ["Blender offline", "Best materials (AO, bevels)", "CSS steps only", stats.blender ? kb(Object.values(stats.blender as Record<string, any>).reduce((n: number, m: any) => n + m.bytes, 0)) + " PNG for 4 icons × 1 clip (shipped)" : "n/a here", "Only at the size rendered", "Rest frame"],
  ];
  $("measure").innerHTML = rows.map((r, i) => `<tr>${r.map((c) => (i ? `<td>${c}</td>` : `<th>${c}</th>`)).join("")}</tr>`).join("");
}

void main();

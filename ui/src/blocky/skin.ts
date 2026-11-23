// Shared runtime for the toy-block icons (docs/ui/BLOCKY_ICONS.md): bake once (or load the cached bake), expose the
// sheets as CSS variables on <html>, make icon elements, and play their hover / press / pop clips.
// The icons are procedural three.js models baked ONCE into sprite sheets by a short-lived renderer (cached in
// localStorage, so later launches need no WebGL at all) and played as CSS background frames. Nothing runs at rest.
// If WebGL is missing, it is software GL, or the bake fails, callers keep their normal glyphs.
import type { Clip } from "./anim";
import { type BakeSpec, type Sheet, bakeSheet, bakeTile, webglInfo } from "./bake";
import { play, reducedMotion, release, sheetVars } from "./sprite";

const VERSION = 5;                    // bump when a recipe, clip, size or tile changes, so cached sheets are re-baked
/** 32-px icons: header buttons, composer, and the to-do panel. The check-off "pop" gets its own row so the other
 *  rows stay narrow (the sheet is as wide as its longest row). */
const ICONS: BakeSpec[] = [
  // header and composer
  { id: "flask", clips: ["hover", "press"] }, { id: "sun", clips: ["hover", "press"] }, { id: "checkBadge", clips: ["hover", "press"] },
  { id: "notepad", clips: ["hover", "press"] }, { id: "hand", clips: ["hover", "press"] }, { id: "heart", clips: ["hover", "press"] },
  { id: "newChat", clips: ["hover", "press"] }, { id: "gear", clips: ["hover", "press"] }, { id: "mic", clips: ["hover", "press"] },
  // to-do panel
  { id: "box", clips: ["hover", "press"] }, { id: "checked", clips: ["hover", "press"] }, { id: "checked", key: "checkedPop", clips: ["pop"] },
  { id: "add", clips: ["hover", "press"] }, { id: "edit", clips: ["hover", "press"] }, { id: "trash", clips: ["hover", "press"] },
  { id: "calendar", clips: ["hover"] }, { id: "alarm", clips: ["hover"] }, { id: "monkey", clips: ["hover"] },
];
/** 72-px empty-state heroes for the to-do panel. */
const HEROES: BakeSpec[] = [{ id: "banana", clips: ["hover"] }, { id: "lock", clips: ["hover"] }, { id: "box", clips: ["hover"] }];
const FAR = { size: 220, pieces: [
  { id: "leafBlock", x: 30, y: 40, s: 0.5, rz: 0.6 }, { id: "cube", x: 150, y: 60, s: 0.3, rz: 0.3 }, { id: "leafBlock", x: 180, y: 170, s: 0.55, rz: -0.9 },
  { id: "cube", x: 60, y: 160, s: 0.26, rz: 1.1 }] };
const NEAR = { size: 280, pieces: [
  { id: "leafBlock", x: 40, y: 190, s: 0.85, rz: 0.9 }, { id: "banana", x: 190, y: 60, s: 0.4, rz: -0.4 }, { id: "leafBlock", x: 230, y: 230, s: 0.7, rz: -2.2 },
  { id: "cube", x: 110, y: 20, s: 0.38, rz: 0.5 }] };

export interface Baked { icons: Sheet; heroes: Sheet; far: string; near: string; bakeMs: number; cached: boolean }
export let baked: Baked | null = null;
let baking: Promise<Baked | null> | null = null;
const listeners: (() => void)[] = [];
export const blockyStats = { bakeMs: 0, cached: false, bytes: 0, failed: "", phases: {} as Record<string, number> };
(window as any).__monkeyBlocky = () => ({ ...blockyStats });          // for the browser tests and the cost measurements

export const juice = () => document.documentElement.dataset.juice ?? "full";
export const motionOK = () => !reducedMotion() && juice() !== "minimal";

// ---------------------------------------------------------------- bake once (or load the cached bake)
const key = (dpr: number) => `monkey.blocky.v${VERSION}.${dpr}`;
const toDataUrl = async (url: string) => {
  const b = await (await fetch(url)).blob();
  return await new Promise<string>((res) => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.readAsDataURL(b); });
};

async function bakeAll(): Promise<Baked | null> {
  const dpr = Math.min(3, Math.max(1, Math.round((window.devicePixelRatio || 1) * 4) / 4));
  try {
    const hit = localStorage.getItem(key(dpr));
    if (hit) { const b = JSON.parse(hit) as Baked; b.cached = true; return b; }
  } catch { /* storage blocked or bad JSON: bake again */ }
  const gl = webglInfo();
  if (!gl.ok) { blockyStats.failed = "no WebGL"; return null; }
  // Software GL (no GPU, e.g. Remote Desktop or the CI browser): keep the plain glyphs rather than spend seconds of CPU.
  // `?blocky` in the URL forces the bake (browser tests and measurements).
  if (gl.software && !/[?&]blocky\b/.test(location.search)) { blockyStats.failed = `software GL (${gl.renderer})`; return null; }
  const t0 = performance.now();
  let t = t0;
  const lap = (k: string) => { const n = performance.now(); blockyStats.phases[k] = Math.round(n - t); t = n; };
  const icons = await bakeSheet(ICONS, 32, dpr); lap("icons");
  const heroes = await bakeSheet(HEROES, 72, dpr); lap("heroes");
  const far = await bakeTile(FAR, Math.min(2, dpr)), near = await bakeTile(NEAR, Math.min(2, dpr)); lap("tiles");
  const out: Baked = { icons, heroes, far: far.url, near: near.url, bakeMs: performance.now() - t0, cached: false };
  blockyStats.bytes = icons.bytes + heroes.bytes + far.bytes + near.bytes;
  try {                                    // cache as data URLs (blob: URLs die with the page)
    const [a, b, c, d] = await Promise.all([icons.url, heroes.url, far.url, near.url].map(toDataUrl));
    for (let i = 0; i < localStorage.length; i++) {            // drop older versions / other DPRs' stale entries
      const k = localStorage.key(i);
      if (k?.startsWith("monkey.blocky.") && !k.startsWith(`monkey.blocky.v${VERSION}.`)) { localStorage.removeItem(k); i--; }
    }
    localStorage.setItem(key(dpr), JSON.stringify({ ...out, icons: { ...icons, url: a }, heroes: { ...heroes, url: b }, far: c, near: d }));
  } catch { /* quota or blocked: bake again next launch */ }
  lap("cache");
  return out;
}

/** Start (or join) the bake. `then` runs once the sheets are ready (right away if they already are). */
export function ensureBaked(then?: () => void): Promise<Baked | null> {
  if (then) { if (baked) then(); else listeners.push(then); }
  baking ??= bakeAll().then((b) => {
    baked = b;
    if (b) {
      blockyStats.bakeMs = Math.round(b.bakeMs); blockyStats.cached = b.cached;
      const root = document.documentElement;
      for (const [k, v] of Object.entries({ ...sheetVars(b.icons), ...sheetVars(b.heroes, "hero") })) root.style.setProperty(k, v);
      root.style.setProperty("--bk-far", `url("${b.far}")`);
      root.style.setProperty("--bk-near", `url("${b.near}")`);
      root.classList.add("blocky");
      listeners.splice(0).forEach((f) => f());
    }
    return b;
  }).catch((e) => { blockyStats.failed = String(e); return null; });
  return baking;
}

// ---------------------------------------------------------------- icon elements
export function icon(id: string, cls = "") {
  const i = document.createElement("i");
  i.className = `bi ${cls}`.trim();
  i.setAttribute("aria-hidden", "true");
  i.dataset.bi = id;
  i.style.setProperty("--bi-row", `var(--bi-row-${id})`);
  return i;
}
export function heroIcon(id: string) {
  const i = icon(id, "bi-hero");
  i.style.setProperty("--bi-row", `var(--hero-row-${id})`);
  return i;
}
/** Replace an element's glyph text with an icon (its aria-label / title still names it). */
export function glyph(el: Element | null, id: string) {
  if (!el || el.querySelector(":scope > .bi")) return;
  el.textContent = "";
  el.append(icon(id));
}

// ---------------------------------------------------------------- playback
const sheetOf = (i: HTMLElement) => (i.classList.contains("bi-hero") ? baked!.heroes : baked!.icons);
const idOf = (i: HTMLElement) => (i.classList.contains("cb-ico") ? (i.closest(".cb")?.classList.contains("on") ? "checked" : "box") : i.dataset.bi!);
/** Play a clip on an icon element (nothing under reduced motion or Minimal juice). `id` overrides the row. */
export function go(i: HTMLElement | null | undefined, clip: Clip, id?: string) {
  if (i && baked && motionOK()) void play(i, sheetOf(i), id ?? idOf(i), clip);
}
export { release };

/** Hover / press for every icon inside `root`'s controls, delegated (one set of listeners per root). */
export function wireHoverPress(root: HTMLElement, controls = "button, .src") {
  const target = (e: Event) => (e.target as Element | null)?.closest?.(controls) as HTMLElement | null;
  const iconIn = (el: Element | null) => el?.querySelector<HTMLElement>(":scope > .bi");
  root.addEventListener("pointerover", (e) => {
    const t = target(e);
    if (!t || t.contains(e.relatedTarget as Node | null)) return;      // only when entering a new control
    go(iconIn(t), "hover");
  });
  root.addEventListener("pointerdown", (e) => go(iconIn(target(e)), "press"));
  const up = (e: Event) => { const i = iconIn(target(e)); if (i) release(i); };
  root.addEventListener("pointerup", up);
  root.addEventListener("pointerout", up);
}

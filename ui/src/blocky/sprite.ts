// Sprite playback: an element shows one cell of a baked sheet as its background; a clip steps the background
// through that clip's frames with the Web Animations API (a few hundred ms, then nothing runs).
import { type Clip, CLIPS } from "./anim";
import type { Sheet } from "./bake";

/** CSS custom properties an ancestor sets so `.bi` elements can draw from the sheet at any size. */
export function sheetVars(sheet: Sheet, prefix = "bi"): Record<string, string> {
  const v: Record<string, string> = { [`--${prefix}-url`]: `url("${sheet.url}")`, [`--${prefix}-cols`]: String(sheet.cols), [`--${prefix}-rows`]: String(sheet.rows) };
  for (const [id, r] of Object.entries(sheet.map)) v[`--${prefix}-row-${id}`] = String(r.row);
  return v;
}

export const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

const running = new WeakMap<Element, Animation>();
/** Play `clip` of icon `id` on `el` (an element sized like one cell). Resolves when it ends. */
export function play(el: HTMLElement, sheet: Sheet, id: string, clip: Clip): Promise<void> {
  const row = sheet.map[id], cols = row?.cols[clip];
  if (!cols || reducedMotion()) return Promise.resolve();
  running.get(el)?.cancel();
  const s = el.clientWidth || sheet.cell;
  const n = cols.n, y = `${-row.row * s}px`;              // the row too: a clip may live in its own row (e.g. the pop)
  const a = el.animate(
    [{ backgroundPosition: `${-cols.x0 * s}px ${y}` }, { backgroundPosition: `${-(cols.x0 + n - 1) * s}px ${y}` }],
    { duration: CLIPS[clip].ms, easing: `steps(${n - 1}, jump-none)`, fill: clip === "press" ? "forwards" : "none" },
  );
  running.set(el, a);
  return a.finished.then(() => undefined, () => undefined);
}

/** Drop a held frame (the end of "press") so the element shows its rest frame again. */
export function release(el: HTMLElement) {
  const a = running.get(el);
  if (a && a.effect?.getTiming().fill === "forwards") { a.cancel(); running.delete(el); }
}

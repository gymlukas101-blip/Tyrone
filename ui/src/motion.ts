// UI motion: one small vocabulary for every panel, list, toast and button (docs/ui/MOTION.md).
//
// Rules this file keeps:
//  - Only transform-type properties (translate / scale / rotate) and opacity are animated, so the compositor does
//    the work. The individual `translate`/`scale`/`rotate` properties are used, never `transform`, so motion stacks
//    on top of an element's own transform (a toast's centring, a button's hover lift) instead of fighting it.
//  - Readability first: anything with text is fully opaque within READ_MS; the bounce continues after that but
//    the words are already readable. Errors, approvals and reminders appear at once and only then move.
//  - Three levels: "full" (default: cartoon springs baked from spring.ts: wind-up, big overshoot, squash-and-stretch,
//    wobbly settle; exits hop then suck back), "calm" (Juice calm: half the travel, the springs scaled way down, half
//    the confetti) and "min" (Juice minimal or the OS "reduce motion": short fades only, nothing moves).
//    Settings → Look & feel → Bounciness scales the full level's springs (spring.ts setBounciness).
//  - Nothing loops while idle, and nothing starts while the window is hidden (it just jumps to the end state).
// The avatar has its own animation system; this file never touches #avatar.
import {
  bakeSamples, calmFeel, exitKeyframes, feel, onBounciness, punchSamples, SPRING, springCss, toKeyframes, type BakeIn, type Feel,
} from "./spring";

export type Juice = "auto" | "full" | "calm" | "minimal";
export type Level = "full" | "calm" | "min";

/** Motion tokens (ms). motion.css mirrors them as --m-* custom properties. */
export const T = {
  instant: 80, fast: 150, base: 240, slow: 400, celebrate: 900,
  read: 110,          // text is fully opaque by then
  fade: 90,           // the whole animation in "min"
  stagger: 30,        // between list items (calm; full: STAGGER_FULL)
  staggerCap: 120,    // a cascade never delays the last item by more than this (calm; full: STAGGER_FULL)
  exit: 160,          // calm exits (full: spring.ts SPRING.ms.exit, a hop then a suck-back)
};
/** Full level: each child of a cascade pops a beat after the one before (the springs are longer there). */
export const STAGGER_FULL = { step: 45, cap: 180 };
export const EASE = {
  out: "cubic-bezier(.2, .8, .2, 1)",
  in: "cubic-bezier(.5, 0, .75, 0)",
  pop: "cubic-bezier(.34, 1.56, .64, 1)",       // overshoot (same curve as game.css --ease-pop)
  snap: "cubic-bezier(.2, 1.4, .4, 1)",
  linear: "linear",
};

export type Enter = "pop" | "rise" | "drop" | "left" | "right" | "fade";
export type Exit = "drop" | "shrink" | "fade" | "left" | "right";
type Frames = Keyframe[];
export interface Step { frames: Frames; opts: KeyframeAnimationOptions }

// ------------------------------------------------------------------ level
/** Which motion level applies. A ?motion=full|calm|min URL flag wins (demo recordings, tests). */
export function resolveLevel(juice: string | undefined, reduced: boolean, override?: string | null): Level {
  if (override === "full" || override === "calm" || override === "min") return override;
  if (reduced || juice === "minimal") return "min";
  if (juice === "calm") return "calm";
  return "full";
}

let juice: string = "auto";
let current: Level = "full";
const hasDom = typeof document !== "undefined";
const reducedNow = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const overrideFlag = () => (typeof location !== "undefined" ? new URLSearchParams(location.search).get("motion") : null);

export function level(): Level { return current; }
export function hidden(): boolean { return hasDom && document.hidden; }

function refresh() {
  current = resolveLevel(juice, reducedNow(), overrideFlag());
  if (hasDom) document.documentElement.dataset.motion = current;
}
/** Settings → Look & feel → Juice level ("auto" follows the OS reduce-motion setting). */
export function setJuice(j: string | undefined) { juice = j || "auto"; refresh(); }

// ------------------------------------------------------------------ plans (pure: what each animation does)
const amp = (lv: Level) => (lv === "calm" ? 0.5 : 1);
const feelFor = (lv: Level): Feel => (lv === "calm" ? calmFeel() : feel());

/** Where each entrance kind starts (full level); calm travels half as far and doesn't tilt. */
const ENTER_FROM: Record<Exclude<Enter, "fade">, Pick<BakeIn, "scale" | "x" | "y" | "rotate">> = {
  pop: { scale: 0.55, y: 12 },
  rise: { scale: 0.7, y: 16 },
  drop: { scale: 0.8, y: -16 },
  left: { scale: 0.75, x: -30, rotate: -1 },
  right: { scale: 0.75, x: 30, rotate: 1 },
};

// Baked springs are cached per kind/level and dropped when the Bounciness slider moves.
const baked = new Map<string, { frames: Keyframe[]; duration: number }>();
onBounciness(() => baked.clear());
function bakeOnce(key: string, make: () => { frames: Keyframe[]; duration: number }) {
  let b = baked.get(key);
  if (!b) { b = make(); baked.set(key, b); }
  return b;
}

/** The keyframes for an entrance. Opacity reaches 1 by T.read (so the wind-up is seen); the spring settles later. */
export function enterPlan(kind: Enter, lv: Level, delay = 0): Step[] {
  const fill: FillMode = "backwards";
  if (lv === "min" || kind === "fade") {
    return [{ frames: [{ opacity: 0 }, { opacity: 1 }], opts: { duration: lv === "min" ? T.fade : T.read, delay: lv === "min" ? 0 : delay, easing: EASE.linear, fill } }];
  }
  const { frames, duration } = bakeOnce(`e:${kind}:${lv}`, () => {
    const a = amp(lv), f = feelFor(lv), from = ENTER_FROM[kind];
    const { samples, duration } = bakeSamples({
      spring: SPRING.item, feel: f, ms: SPRING.ms.item, windupMs: SPRING.ms.windupItem,
      scale: 1 - (1 - (from.scale ?? 1)) * a, x: (from.x ?? 0) * a, y: (from.y ?? 0) * a, rotate: (from.rotate ?? 0) * f.tilt * 0.4,
    });
    return { frames: toKeyframes(samples, { translate: true }), duration };
  });
  return [
    { frames: [{ opacity: 0 }, { opacity: 1 }], opts: { duration: T.read, delay, easing: EASE.linear, fill } },
    { frames, opts: { duration, delay, easing: EASE.linear, fill } },
  ];
}

/** How long an exit takes at a level (full: the hop-and-suck-back; faster than any entrance). */
export function exitMs(lv: Level = current): number {
  return lv === "min" ? T.fade : lv === "calm" ? T.exit : Math.round(SPRING.ms.exit * feel().durScale);
}

/** An exit. Full: a squat, a little hop that grows it, then it sucks back small and drops (or flies to the side).
 *  `baseY` keeps a toast's place in the stack while it leaves. */
export function exitPlan(kind: Exit, lv: Level, baseY = 0): Step[] {
  const dur = exitMs(lv);
  const fade: Step = { frames: [{ opacity: 1 }, { opacity: 0 }], opts: { duration: dur, easing: EASE.in, fill: "forwards" } };
  if (lv === "min" || kind === "fade") return [fade];
  if (lv === "calm") {
    const a = amp(lv);
    const to: Record<Exclude<Exit, "fade">, Keyframe> = {
      drop: { translate: `0px ${Math.round(10 * a) + baseY}px`, scale: `${1 - 0.04 * a}` },
      shrink: { translate: `0px ${baseY}px`, scale: `${1 - 0.12 * a}` },
      left: { translate: `${Math.round(-40 * a)}px ${baseY}px` },
      right: { translate: `${Math.round(40 * a)}px ${baseY}px` },
    };
    return [fade, { frames: [{ translate: `0px ${baseY}px`, scale: "1" }, to[kind]], opts: { duration: dur, easing: EASE.in, fill: "forwards" } }];
  }
  const f = feel();
  const end: Record<Exclude<Exit, "fade">, { to: number; x?: number; y?: number; rotate?: number }> = {
    drop: { to: 0.45, y: 22, rotate: f.tilt * 0.6 },
    shrink: { to: 0.3, y: 8 },
    left: { to: 0.7, x: -70, rotate: -f.tilt },
    right: { to: 0.7, x: 70, rotate: f.tilt },
  };
  const k = exitKeyframes({ feel: f, ms: SPRING.ms.exit, baseY, ...end[kind] });
  return [{ frames: k.fade, opts: { duration: k.duration, fill: "forwards" } }, { frames: k.move, opts: { duration: k.duration, fill: "forwards" } }];
}

/** A one-shot punch: confirms ("saved", a choice, a count that changed). Full: a jelly jump; nothing in "min". */
export function popPlan(lv: Level, strength = 1): Step[] {
  if (lv === "min") return [];
  if (lv === "calm") return [{ frames: [{ scale: "1" }, { scale: `${1 + 0.05 * strength}` }, { scale: "1" }], opts: { duration: T.base, easing: EASE.out } }];
  const { frames, duration } = bakeOnce(`p:${strength}`, () => {
    const { samples, duration } = punchSamples(strength, feel());
    return { frames: toKeyframes(samples, { translate: false, rotate: false }), duration };
  });
  return [{ frames, opts: { duration, easing: EASE.linear } }];
}

/** A list row gliding to its new place (FLIP): a spring that overshoots a little and settles. */
export function movePlan(dx: number, dy: number, lv: Level): Step[] {
  if (lv === "min") return [];
  if (lv === "calm") return [{ frames: [{ translate: `${dx}px ${dy}px` }, { translate: "0 0" }], opts: { duration: T.base, easing: EASE.out } }];
  const f = feel();
  const { samples, duration } = bakeSamples({ spring: SPRING.move, feel: { ...f, squash: f.squash * 0.25, windup: 0 }, ms: SPRING.ms.move, x: dx, y: dy });
  return [{ frames: toKeyframes(samples, { translate: true, rotate: false }), opts: { duration, easing: EASE.linear } }];
}

/** A short horizontal shake ("no", an error). Nothing in "min" (the colour change carries it). */
export function shakePlan(lv: Level): Step[] {
  if (lv === "min") return [];
  const d = lv === "calm" ? 3 : 7;
  const xs = [0, -d, d, -d * 0.7, d * 0.7, -d * 0.3, 0];
  return [{ frames: xs.map((x) => ({ translate: `${x}px 0` })), opts: { duration: 380, easing: EASE.out } }];
}

/** "Look here" for things that are already on screen: a little wobble and grow, twice. */
export function attentionPlan(lv: Level): Step[] {
  if (lv === "min") return [];
  if (lv === "calm") return popPlan(lv, 1);
  const r = [0, -2.5, 2.5, -1.5, 1.5, 0];
  return [{ frames: r.map((deg, i) => ({ rotate: `${deg}deg`, scale: i === 0 || i === r.length - 1 ? "1" : "1.03" })),
            opts: { duration: 560, easing: EASE.out, iterations: 1 } }];
}

/** The numbers a count-up shows: about `hz` updates a second, always ending exactly on `to`. */
export function countFrames(from: number, to: number, ms: number, hz = 15): number[] {
  const n = Math.max(1, Math.round((ms / 1000) * hz));
  const out: number[] = [];
  for (let i = 1; i <= n; i++) {
    const t = i / n, e = 1 - Math.pow(1 - t, 3);          // ease-out cubic
    out.push(i === n ? to : from + (to - from) * e);
  }
  return out;
}

/** Stagger delay for the i-th item of a cascade (never more than T.staggerCap in total; none in "min"). */
export const staggerDelay = (i: number, lv: Level, step = T.stagger) =>
  (lv === "min" ? 0 : lv === "full" ? Math.min(i * step * (STAGGER_FULL.step / T.stagger), STAGGER_FULL.cap) : Math.min(i * step, T.staggerCap));

/** How many confetti bits a celebration gets at each level. */
export const confettiCount = (lv: Level, n = 16) => (lv === "full" ? n : lv === "calm" ? Math.ceil(n / 2) : 0);

// ------------------------------------------------------------------ runtime helpers (DOM)
type Animatable = Element & { animate?: Element["animate"] };

/** Run a plan on an element. Skips (returns []) when the window is hidden or the element is gone. */
export function run(el: Animatable | null | undefined, steps: Step[]): Animation[] {
  if (!el || !steps.length || !el.animate || hidden() || (hasDom && !el.isConnected)) return [];
  const out: Animation[] = [];
  for (const s of steps) {
    try { out.push(el.animate(s.frames, { ...s.opts, id: "m" })); } catch { /* an engine without individual transforms: no motion */ }
  }
  return out;
}

export function enter(el: Element | null | undefined, kind: Enter = "pop", delay = 0) { return run(el, enterPlan(kind, current, delay)); }
export function pop(el: Element | null | undefined, strength = 1) { return run(el, popPlan(current, strength)); }
export function shake(el: Element | null | undefined) { return run(el, shakePlan(current)); }
export function attention(el: Element | null | undefined) { return run(el, attentionPlan(current)); }

/** Entrance cascade for a list of new items. */
export function stagger(els: Iterable<Element>, kind: Enter = "rise", step = T.stagger) {
  let i = 0;
  for (const el of els) enter(el, kind, staggerDelay(i++, current, step));
}

/** Animate out, then call `done` (default: remove the element). The element stops taking clicks at once. */
export function leave(el: HTMLElement | null | undefined, kind: Exit = "drop", done?: () => void, baseY = 0) {
  if (!el || el.dataset.leaving) return;
  const finish = done ?? (() => el.remove());
  if (!el.isConnected) { finish(); return; }
  el.dataset.leaving = "1";
  el.setAttribute("aria-hidden", "true");
  el.inert = true;
  el.style.pointerEvents = "none";
  const anims = run(el, exitPlan(kind, current, baseY));
  if (!anims.length) { finish(); return; }
  let called = false;
  const once = () => { if (!called) { called = true; finish(); } };
  anims[0].finished.then(once, once);
  setTimeout(once, exitMs() + 120);                       // never stuck on screen if the animation is cancelled
}

/** A fixed, click-through layer for ghosts and confetti (aria-hidden, above the page, below modal dialogs). */
function fxLayer(): HTMLElement {
  let fx = document.getElementById("m-fx");
  if (!fx) {
    fx = document.createElement("div");
    fx.id = "m-fx";
    fx.setAttribute("aria-hidden", "true");
    fx.inert = true;
    document.body.append(fx);
  }
  return fx;
}

/** A still copy of a removed element, drawn where it was so it can animate out (the real one is already gone). */
function ghostAt(node: HTMLElement, r: DOMRect, kind: Exit) {
  if (hidden() || current === "min" || r.width === 0 || r.height === 0) return;
  const g = node.cloneNode(true) as HTMLElement;
  g.removeAttribute("id");
  g.querySelectorAll("[id]").forEach((x) => x.removeAttribute("id"));
  g.classList.add("m-ghost");
  Object.assign(g.style, { position: "fixed", left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px`,
                           margin: "0", boxSizing: "border-box", animation: "none" });
  fxLayer().append(g);
  const a = run(g, exitPlan(kind, current));
  const rm = () => g.remove();
  if (a.length) a[0].finished.then(rm, rm); else rm();
  setTimeout(rm, exitMs() + 200);
}

/** Remove an item from a list smoothly: it animates out from where it was and its neighbours glide into place. */
export function removeSmoothly(el: HTMLElement | null | undefined, kind: Exit = "shrink") {
  if (!el?.isConnected) { el?.remove(); return; }
  const parent = el.parentElement;
  const rect = el.getBoundingClientRect();
  const play = parent ? flip(parent, ":scope > *", (x) => x) : null;
  el.remove();
  ghostAt(el, rect, kind);
  play?.({ enter: false });
}

interface Before { rect: DOMRect; node: HTMLElement; bar: number | null }

type FlipOpts = { enter?: boolean; exits?: boolean; kind?: Enter };
interface FlipJob { before: Map<unknown, Before>; first: boolean; opts: FlipOpts | null; scheduled: boolean }
const flips = new Map<string, Map<Element, FlipJob>>();

/**
 * FLIP for a list that is about to be redrawn (or reordered, or have items added/removed).
 *   const play = flip(listParent, "li[data-id]", (el) => el.dataset.id);   // before the change
 *   ...redraw...
 *   play();                                                                // after it
 * Items that moved glide from where they were; new items pop in (a short cascade on the first draw); removed
 * items animate out as ghosts; a progress bar (.prio) that changed grows from its old width.
 * Bursts are cheap: changes to the same list within one frame share one "before" snapshot, and the "after"
 * positions are read once, in the next animation frame (one layout, not one per event).
 */
export function flip(root: Element, selector: string, key: (el: HTMLElement) => unknown = (el) => el.dataset.id) {
  if (hidden()) return (_opts: FlipOpts = {}) => {};
  const jobs = flips.get(selector) ?? flips.set(selector, new Map()).get(selector)!;
  let job = jobs.get(root);
  if (!job) {
    const before = new Map<unknown, Before>();
    root.querySelectorAll<HTMLElement>(selector).forEach((el) => {
      const k = key(el);
      if (k == null || el.dataset.leaving) return;
      const bar = el.querySelector<HTMLElement>(":scope > .prio");
      before.set(k, { rect: el.getBoundingClientRect(), node: el, bar: bar ? bar.getBoundingClientRect().width : null });
    });
    job = { before, first: before.size === 0, opts: null, scheduled: false };
    jobs.set(root, job);
  }
  const j = job;
  return (opts: FlipOpts = {}) => {
    // several changes in one frame: stay quiet if any of them asked to (a tab switch), use the latest entrance kind
    j.opts = j.opts ? { enter: j.opts.enter !== false && opts.enter !== false, exits: j.opts.exits !== false && opts.exits !== false,
                        kind: opts.kind ?? j.opts.kind } : { ...opts };
    if (j.scheduled) return;
    j.scheduled = true;
    requestAnimationFrame(() => { jobs.delete(root); playFlip(root, selector, key, j); });
  };
}

function playFlip(root: Element, selector: string, key: (el: HTMLElement) => unknown, job: FlipJob) {
  if (hidden() || !root.isConnected) return;
  const opts = job.opts ?? {};
  const els = [...root.querySelectorAll<HTMLElement>(selector)];
  // a move still gliding from an earlier change would skew the new positions: stop it first (no layout needed)
  for (const el of els) el.getAnimations?.().forEach((a) => { if (a.id === "m-flip") a.cancel(); });
  const seen = new Set<unknown>();
  let n = 0;
  for (const el of els) {
    const k = key(el);
    seen.add(k);
    const b = k == null ? undefined : job.before.get(k);
    if (!b) {
      if (opts.enter !== false) enter(el, opts.kind ?? (job.first ? "rise" : "pop"), staggerDelay(n++, current));
      continue;
    }
    if (current === "min") continue;
    const r = el.getBoundingClientRect();
    const dx = b.rect.left - r.left, dy = b.rect.top - r.top;
    if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
      const a = run(el, movePlan(dx, dy, current));
      a.forEach((x) => { x.id = "m-flip"; });
    }
    const bar = el.querySelector<HTMLElement>(":scope > .prio");
    if (bar && b.bar != null) progress(bar, b.bar, bar.getBoundingClientRect().width);
  }
  if (current === "min" || opts.exits === false) return;
  for (const [k, b] of job.before) {
    if (seen.has(k) || b.node.classList.contains("checking")) continue;     // a checked-off row already collapsed itself
    ghostAt(b.node, b.rect, "shrink");
  }
}

/** A bar grows (or shrinks) from its old width to its new one, on the compositor (scaleX from the left). */
export function progress(bar: HTMLElement, fromPx: number, toPx: number) {
  if (current === "min" || toPx <= 0 || Math.abs(fromPx - toPx) < 1) return [];
  (bar.style as any).transformOrigin = "left center";
  return run(bar, [{ frames: [{ scale: `${Math.max(0, fromPx / toPx)} 1` }, { scale: "1 1" }],
                     opts: { duration: T.slow, easing: current === "calm" ? EASE.out : EASE.pop } }]);
}

/** Text that changed in place (a status label): the new words rise in quickly. Instant in "min". */
export function swapText(el: Element | null | undefined) {
  if (current === "min") return [];
  return run(el, [{ frames: [{ opacity: 0.25, translate: `0 ${current === "calm" ? 3 : 6}px` }, { opacity: 1, translate: "0 0" }],
                    opts: { duration: T.read + 30, easing: EASE.out } }]);
}

/** Count a number up (or down) in an element's text, then punch it. Jumps straight to the end in "min" or hidden. */
const counting = new WeakMap<Element, number>();
export function countUp(el: HTMLElement | null | undefined, from: number, to: number, fmt: (n: number) => string, ms = 450) {
  if (!el) return;
  const prev = counting.get(el);
  if (prev) clearTimeout(prev);
  if (current === "min" || hidden() || from === to || !Number.isFinite(from)) { el.textContent = fmt(to); return; }
  const frames = countFrames(from, to, ms);
  const gap = ms / frames.length;
  let i = 0;
  const tick = () => {
    el.textContent = fmt(frames[i++]);
    if (i < frames.length) counting.set(el, window.setTimeout(tick, gap));
    else { counting.delete(el); pop(el, 0.8); }
  };
  tick();
}

const CONFETTI = ["#ffd43b", "#3cc24a", "#ff4fa3", "#6ec6ff", "#fff3c4", "#ff9f1a"];
/** A small burst of confetti from an element (or a point). A few DOM bits, gone in under a second. */
export function confetti(at: Element | { x: number; y: number } | null | undefined, n = 16) {
  const count = confettiCount(current, n);
  if (!at || !count || hidden()) return;
  let x: number, y: number;
  if (at instanceof Element) {
    if (!at.isConnected) return;
    const r = at.getBoundingClientRect(); x = r.left + r.width / 2; y = r.top + r.height / 2;
  } else ({ x, y } = at);
  const fx = fxLayer();
  for (let i = 0; i < count; i++) {
    const bit = document.createElement("i");
    bit.className = "m-confetti";
    bit.style.left = `${x}px`; bit.style.top = `${y}px`;
    bit.style.background = CONFETTI[i % CONFETTI.length];
    fx.append(bit);
    const ang = (i / count) * Math.PI * 2 + Math.random() * 0.5;
    const dist = 50 + Math.random() * 60;
    const dx = Math.cos(ang) * dist, dy = Math.sin(ang) * dist - 40;
    const spin = (Math.random() * 2 - 1) * 540;
    const a = run(bit, [{ frames: [
      { translate: "0 0", rotate: "0deg", scale: "1", opacity: 1 },
      { translate: `${dx}px ${dy}px`, rotate: `${spin / 2}deg`, scale: "1", opacity: 1, offset: 0.45 },
      { translate: `${dx * 1.15}px ${dy + 90}px`, rotate: `${spin}deg`, scale: ".6", opacity: 0 },
    ], opts: { duration: 760 + Math.random() * 200, easing: EASE.out, fill: "forwards" } }]);
    const rm = () => bit.remove();
    if (a.length) a[0].finished.then(rm, rm); else rm();
  }
}

/** Busy state on a control (a slow save, a download): a gentle opacity breathe while it lasts, off when done. */
export function busy(el: Element | null | undefined, on: boolean) {
  el?.classList.toggle("m-busy", on);
}

/** The voice state, for the panel glows in motion.css (listening = banana, thinking = label breathes, speaking = leaf). */
export function voice(state: string) {
  if (hasDom) document.documentElement.dataset.voice = state;
}

// ------------------------------------------------------------------ toasts: newest at the bottom, older ones step up
const STACK_GAP = 8;
export function restack(host: Element = document.body) {
  // One column for every toast (reminders sit higher in CSS): newest at the bottom, each older one above it.
  const toasts = [...host.querySelectorAll<HTMLElement>(":scope > .toast:not([data-leaving])")];
  const box = new Map(toasts.map((t) => [t, { h: t.offsetHeight, base: parseFloat(getComputedStyle(t).bottom) || 0 }] as const));
  if (!toasts.length) return;
  let at = box.get(toasts[toasts.length - 1])!.base;                  // the newest keeps its own spot (reminders sit higher)
  for (let i = toasts.length - 1; i >= 0; i--) {
    const { h, base } = box.get(toasts[i])!;
    toasts[i].style.setProperty("--m-stack", `${base - at}px`);
    at += h + STACK_GAP;
  }
}
/** Restack once per frame however many toasts came and went in it. */
const restacking = new Set<Element>();
function restackSoon(host: Element) {
  if (restacking.has(host) || hidden()) { if (hidden()) restack(host); return; }
  restacking.add(host);
  requestAnimationFrame(() => { restacking.delete(host); if (host.isConnected) restack(host); });
}
/** Call after a toast is appended: stacks it with the others and gives alerts a "look here" once they're shown. */
export function toastShown(t: HTMLElement) {
  const host = t.parentElement ?? document.body;
  if (t.getAttribute("role") === "alert" || t.classList.contains("m-now")) {
    // an alert lands in its final place at once (it's never slid in), then wobbles
    t.style.transition = "none";
    restack(host);
    requestAnimationFrame(() => { t.style.transition = ""; });
    attention(t);
  } else restackSoon(host);
}
/** Remove a toast with a quick exit, then let the rest of the stack settle. */
export function toastGone(t: HTMLElement) {
  const host = t.parentElement;
  const stack = parseFloat(t.style.getPropertyValue("--m-stack")) || 0;      // leave from its place in the stack
  leave(t, "drop", () => { t.remove(); if (host) restackSoon(host); }, stack);
}

// ------------------------------------------------------------------ buttons: jelly press, hover bob (full only)
/** The chunky buttons that squash and jelly. Buttons wearing a toy-block icon (.bi) are left to the icon's own clips. */
export const JELLY = "#send, .primary, .ghost, .draft .send, #importance button, .tabs button, .star, .opt, .card .close, header .icon, #mic, .m-retry";
const jellyTarget = (t: EventTarget | null): HTMLElement | null => {
  const b = (t as Element | null)?.closest?.(JELLY) as HTMLElement | null;
  if (!b || (b as HTMLButtonElement).disabled || b.querySelector(":scope > .bi") || current !== "full" || hidden()) return null;
  return b;
};
/** The squash while a button is held: wider and shorter, anchored on its bottom edge. */
export function pressPlan(f: Feel = feel()): Step[] {
  const a = SPRING.press * f.b;
  return [{ frames: [{ scale: "1 1" }, { scale: `${1 + a} ${1 - a}` }], opts: { duration: 90, easing: EASE.out, fill: "forwards" } }];
}
/** Let go: it springs back past its shape (taller, narrower) and jiggles home. `held` = how far the squash got (0..1). */
export function releasePlan(held = 1, f: Feel = feel()): Step[] {
  const a = SPRING.press * f.b * Math.max(0, Math.min(1, held));
  if (a <= 0.001) return [];
  const { samples, duration } = bakeSamples({ spring: SPRING.jelly, feel: f, ms: SPRING.ms.jelly, jelly: a });
  return [{ frames: toKeyframes(samples, { translate: false, rotate: false }), opts: { duration, easing: EASE.linear } }];
}
/** Pointer over a button: one little bob (not a loop). */
export function hoverPlan(f: Feel = feel()): Step[] {
  const h = (4 * f.b) / (SPRING.bounciness / 100);
  if (h < 0.5) return [];
  return [{ frames: [{ translate: "0 0" }, { translate: `0 ${-h}px`, offset: 0.3 }, { translate: `0 ${h * 0.25}px`, offset: 0.6 },
                     { translate: `0 ${-h * 0.3}px`, offset: 0.8 }, { translate: "0 0" }], opts: { duration: 440, easing: EASE.out } }];
}
function installJelly() {
  let held: { el: HTMLElement; anim: Animation | null; at: number } | null = null;
  const bobbed = new WeakMap<Element, number>();
  const anchor = (b: HTMLElement) => { if (!b.style.transformOrigin) b.style.transformOrigin = "50% 100%"; };
  const release = () => {
    if (!held) return;
    const { el, anim, at } = held;
    held = null;
    const got = Math.min(1, (performance.now() - at) / 90);
    try { anim?.cancel(); } catch { /* gone */ }
    run(el, releasePlan(got)).forEach((x) => { x.id = "m-jelly"; });
  };
  document.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const b = jellyTarget(e.target);
    if (!b) return;
    release();
    anchor(b);
    b.getAnimations?.().forEach((x) => { if (x.id === "m-jelly" || x.id === "m-hop") x.cancel(); });
    const anim = run(b, pressPlan())[0] ?? null;
    if (anim) anim.id = "m-press";
    held = { el: b, anim, at: performance.now() };
  }, true);
  document.addEventListener("pointerup", release, true);
  document.addEventListener("pointercancel", release, true);
  // keyboard (Enter / Space): a click with no pointer gets a full jelly
  document.addEventListener("click", (e) => {
    if (e.detail !== 0) return;
    const b = jellyTarget(e.target);
    if (b) { anchor(b); run(b, releasePlan(1)).forEach((x) => { x.id = "m-jelly"; }); }
  }, true);
  document.addEventListener("pointerover", (e) => {
    if (e.pointerType !== "mouse" || held) return;
    const b = jellyTarget(e.target);
    if (!b || b.contains(e.relatedTarget as Node | null)) return;
    const now = performance.now();
    if (now - (bobbed.get(b) ?? -1e9) < 600) return;
    bobbed.set(b, now);
    run(b, hoverPlan()).forEach((x) => { x.id = "m-hop"; });
  }, true);
}

// ------------------------------------------------------------------ boot
/** The springs motion.css uses (@keyframes ms-*), baked from spring.ts; rebuilt when the Bounciness slider moves. */
function installSpringCss() {
  let st = document.getElementById("m-spring") as HTMLStyleElement | null;
  if (!st) { st = document.createElement("style"); st.id = "m-spring"; document.head.append(st); }
  st.textContent = springCss();
}
if (hasDom) {
  refresh();
  installSpringCss();
  onBounciness(installSpringCss);
  installJelly();
  try { matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", refresh); } catch { /* old engine */ }
  // Hidden window (tray, minimised): pause the CSS loops (vines, shine, pulses) and skip new motion; finish this
  // file's one-shots so nothing is left half-way when it comes back. Done here rather than with a CSS rule on
  // `*`, which every style recalc would have to check.
  let paused: Animation[] = [];
  const vis = () => {
    if (document.hidden) {
      for (const a of document.getAnimations?.() ?? []) {
        if (a.id.startsWith("m")) a.finish();
        else if (a.playState === "running") { a.pause(); paused.push(a); }
      }
    } else {
      for (const a of paused) if (a.playState === "paused") a.play();
      paused = [];
    }
  };
  document.addEventListener("visibilitychange", vis);
  vis();
}

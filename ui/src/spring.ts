// Cartoon springs: the one place the UI's bounce is tuned (docs/ui/MOTION.md, "Springs").
//
// Every entrance, exit, button jelly and badge punch at the "full" Juice level is baked from these tokens into
// multi-keyframe animations (WAAPI keyframes for motion.ts / menu-motion.ts, CSS @keyframes for motion.css), so
// there are no single cubic-beziers left to tune one by one. To make the whole UI bouncier or calmer, change a
// token here (or the owner moves Settings → Look & feel → Bounciness, which scales the overshoot, squash, wind-up,
// tilt and length together).
//
//   stiffness  how fast a spring snaps home (k, with mass 1: ω = √k rad/s). Higher = snappier, shorter.
//   damping    damping ratio ζ at Bounciness 100. Lower = more overshoot and more wobbles (1 = no overshoot).
//              The first overshoot is e^(−πζ/√(1−ζ²)) of the travel (overshoot() below).
//   peak       no scale axis ever goes past this, whatever the slider says (a soft limit, not a flat clip).
//
// Only scale, translate, rotate and opacity come out of here (compositor properties).

export interface Spring { stiffness: number; damping: number }

export const SPRING = {
  bounciness: 85,                                    // Settings → Look & feel → Bounciness default (0–100)
  pop:   { stiffness: 250, damping: 0.30 },          // dialogs, panels, cards
  item:  { stiffness: 300, damping: 0.32 },          // list rows, chips, chat bubbles, menu contents
  toast: { stiffness: 230, damping: 0.27 },          // toasts bouncing in from the bottom edge
  jelly: { stiffness: 520, damping: 0.20 },          // button release, badge / count punch
  move:  { stiffness: 320, damping: 0.42 },          // list rows gliding to a new place, tab slides
  peak: 1.18,                                        // max scale on any axis
  squash: 0.2,                                       // squash-and-stretch (fraction of size, velocity-coupled)
  windup: 0.13,                                      // anticipation: the squash before an entrance pops
  tilt: 7,                                           // deg: cards and toasts land tilted and wobble upright
  exitGrow: 0.06,                                    // exits grow this much (a little hop) before they suck back
  press: 0.1,                                        // a pressed button squashes this much (wider, shorter)
  punch: 0.2,                                        // a badge / count punch grows this much
  /** Lengths (ms) at the default Bounciness; the slider stretches or shortens them a little (durScale). */
  ms: { pop: 560, item: 460, toast: 560, jelly: 480, move: 420, windup: 90, windupItem: 60, exit: 320, close: 340 },
  /** Juice calm: the same springs scaled way down (no squash, wind-up or tilt; ~1 % overshoot), and shorter. */
  calm: { bounce: 0.1, durScale: 0.6 },
} as const;

// ------------------------------------------------------------------ the slider
let bounce = SPRING.bounciness / 100;
const listeners = new Set<() => void>();
/** Settings → Look & feel → Bounciness (0–100). Applies to the "full" Juice level. */
export function setBounciness(v: number | undefined | null) {
  const n = Number.isFinite(Number(v)) && v != null ? Math.max(0, Math.min(100, Number(v))) / 100 : SPRING.bounciness / 100;
  if (n === bounce) return;
  bounce = n;
  for (const fn of listeners) fn();
}
export function bounciness(): number { return Math.round(bounce * 100); }
export function onBounciness(fn: () => void) { listeners.add(fn); }

/** What one Bounciness value means for the full level: every amount scales with it, length a little too. */
export interface Feel { b: number; squash: number; windup: number; tilt: number; grow: number; durScale: number }
export function feel(b = bounce): Feel {
  const k = Math.max(0, Math.min(1, b));
  // length: 1 at the default, a quarter shorter at 0 (no wobble to wait for), a little longer at 100
  return { b: k, squash: SPRING.squash * k, windup: SPRING.windup * k, tilt: SPRING.tilt * k, grow: SPRING.exitGrow * k,
           durScale: 0.75 + 0.25 * (k / (SPRING.bounciness / 100)) };
}
export const calmFeel = (): Feel => ({ b: SPRING.calm.bounce, squash: 0, windup: 0, tilt: 0, grow: 0, durScale: SPRING.calm.durScale });

// ------------------------------------------------------------------ the solver
/** First overshoot of a spring, as a fraction of its travel. */
export function overshoot(zeta: number): number {
  return zeta >= 1 ? 0 : Math.exp((-Math.PI * zeta) / Math.sqrt(1 - zeta * zeta));
}
/** The damping ratio that gives this overshoot (0 → critically damped). */
export function zetaFor(over: number): number {
  if (over <= 1e-4) return 0.999;
  const l = Math.log(over);
  return Math.min(0.999, -l / Math.sqrt(Math.PI * Math.PI + l * l));
}
/** The spring a Bounciness gives: overshoot scales linearly with it, the speed follows the length. */
export function tuned(s: Spring, f: Feel): { omega: number; zeta: number } {
  const zeta = zetaFor(overshoot(s.damping) * f.b);
  return { omega: Math.sqrt(s.stiffness) / f.durScale, zeta };
}

/** Error of a spring released from 1 at rest (1 → 0, oscillating) and its velocity, at t seconds. */
export function springAt(omega: number, zeta: number, t: number): { x: number; v: number } {
  const z = Math.min(zeta, 0.999);
  const wd = omega * Math.sqrt(1 - z * z);
  const env = Math.exp(-z * omega * t);
  const x = env * (Math.cos(wd * t) + ((z * omega) / wd) * Math.sin(wd * t));
  const v = -env * ((omega * omega) / wd) * Math.sin(wd * t);
  return { x, v };
}

const smooth = (a: number) => (a <= 0 ? 0 : a >= 1 ? 1 : a * a * (3 - 2 * a));
/** A soft limit: up to half-way to `peak` values pass unchanged; above that they approach `peak` but never pass it
 *  (no flat clip, no kink). */
export function soften(v: number, peak: number = SPRING.peak): number {
  const knee = 1 + (peak - 1) / 2;
  if (v <= knee) return v;
  const room = peak - knee;
  return knee + room * Math.tanh((v - knee) / room);
}

/** One sampled moment: scale per axis, translate (px), rotate (deg), at an offset 0..1. */
export interface Sample { o: number; sx: number; sy: number; x: number; y: number; r: number }

export interface BakeIn {
  spring: Spring;
  feel: Feel;
  ms: number;                        // spring phase length (at durScale 1)
  windupMs?: number;                 // anticipation before it (at durScale 1); 0 = none
  scale?: number;                    // start scale (→ 1)
  x?: number; y?: number;            // start offset in px (→ 0)
  rotate?: number;                   // start tilt in deg (→ 0)
  /** Jelly from a squashed start (button release): deformation only, no size change. */
  jelly?: number;
}

/**
 * Bake a spring entrance into samples. Phase 1 (wind-up): it squashes (wider, shorter) where it starts.
 * Phase 2: the spring releases it: size, offset and tilt overshoot and wobble home, stretching taller while it
 * shoots up and squashing as it turns round (squash-and-stretch from the velocity). A short taper at the end lands
 * it exactly on its rest state.
 */
export function bakeSamples(o: BakeIn, stepMs = 1000 / 60): { samples: Sample[]; duration: number } {
  const f = o.feel;
  const { omega, zeta } = tuned(o.spring, f);
  const wu = f.windup > 0 ? Math.round((o.windupMs ?? 0) * f.durScale) : 0;
  const sp = Math.round(o.ms * f.durScale);
  const total = wu + sp;
  const s0 = o.scale ?? 1, x0 = o.x ?? 0, y0 = o.y ?? 0, r0 = o.rotate ?? 0;
  // the speed scale for the stretch: the fastest the spring moves (sampled), so `squash` is the max deformation
  let vmax = 1e-6;
  for (let t = 0; t <= sp / 1000; t += 0.004) vmax = Math.max(vmax, Math.abs(springAt(omega, zeta, t).v));
  const n = Math.max(2, Math.ceil(total / stepMs));
  const out: Sample[] = [];
  for (let i = 0; i <= n; i++) {
    const tm = (i / n) * total;
    let e: number, d: number;                       // e: remaining error (1 → 0); d: stretch (+ taller, − squashed)
    if (tm < wu) {
      e = 1;
      d = -f.windup * smooth(tm / Math.max(1, wu));
    } else {
      const t = (tm - wu) / 1000;
      const s = springAt(omega, zeta, t);
      const taper = 1 - smooth((tm - wu - sp * 0.72) / (sp * 0.28));
      e = s.x * taper;
      const release = wu ? f.windup * Math.exp(-t / 0.045) : 0;  // the wind-up lets go quickly
      d = (f.squash * (-s.v / vmax) - release) * taper;
      if (o.jelly) d = -o.jelly * s.x * taper;
    }
    const size = o.jelly ? 1 : 1 - (1 - s0) * e;
    out.push({
      o: total ? tm / total : 1,
      sx: soften(size * (1 - d)), sy: soften(size * (1 + d)),
      x: x0 * e, y: y0 * e, r: r0 * e,
    });
  }
  const last = out[out.length - 1];
  Object.assign(last, { o: 1, sx: 1, sy: 1, x: 0, y: 0, r: 0 });
  return { samples: thin(out), duration: total };
}

/** Drop samples that a straight line between their neighbours already draws (fewer keyframes, same motion). */
function thin(s: Sample[]): Sample[] {
  if (s.length <= 3) return s;
  const keep: Sample[] = [s[0]];
  for (let i = 1; i < s.length - 1; i++) {
    const a = keep[keep.length - 1], b = s[i + 1], c = s[i];
    const k = (c.o - a.o) / (b.o - a.o || 1);
    const lerp = (p: keyof Sample) => a[p] + (b[p] - a[p]) * k;
    const off = Math.max(Math.abs(c.sx - lerp("sx")) / 0.004, Math.abs(c.sy - lerp("sy")) / 0.004,
                         Math.abs(c.x - lerp("x")) / 0.4, Math.abs(c.y - lerp("y")) / 0.4, Math.abs(c.r - lerp("r")) / 0.2);
    if (off > 1) keep.push(c);
  }
  keep.push(s[s.length - 1]);
  return keep;
}

const n4 = (v: number) => String(Math.round(v * 10000) / 10000);
const n2 = (v: number) => String(Math.round(v * 100) / 100);

/** Samples → WAAPI keyframes (linear between them: the spring is in the samples). */
export function toKeyframes(samples: Sample[], with_: { translate?: boolean; rotate?: boolean } = {}): Keyframe[] {
  const tr = with_.translate ?? samples.some((s) => s.x || s.y);
  const ro = with_.rotate ?? samples.some((s) => s.r);
  return samples.map((s) => {
    const k: Keyframe = { offset: Math.round(s.o * 10000) / 10000, scale: `${n4(s.sx)} ${n4(s.sy)}` };
    if (tr) k.translate = `${n2(s.x)}px ${n2(s.y)}px`;
    if (ro) k.rotate = `${n2(s.r)}deg`;
    return k;
  });
}

/** Samples → a CSS @keyframes block. `yBase` is added to translate-y (a toast's stack offset). */
export function toCss(name: string, samples: Sample[], yBase = ""): string {
  const tr = samples.some((s) => s.x || s.y) || !!yBase;
  const ro = samples.some((s) => s.r);
  const lines = samples.map((s) => {
    const y = yBase ? `calc(${yBase} + ${n2(s.y)}px)` : `${n2(s.y)}px`;
    return `${n2(s.o * 100)}%{scale:${n4(s.sx)} ${n4(s.sy)}${tr ? `;translate:${n2(s.x)}px ${y}` : ""}${ro ? `;rotate:${n2(s.r)}deg` : ""}}`;
  });
  return `@keyframes ${name}{${lines.join("")}}`;
}

/** A punch (a badge or count that changed, a confirm): it jumps bigger and jiggles back, stretching as it goes. */
export function punchSamples(strength: number, f: Feel, stepMs = 1000 / 60): { samples: Sample[]; duration: number } {
  const { omega, zeta } = tuned(SPRING.jelly, { ...f, b: Math.max(f.b, 0.05) });
  const total = Math.round(SPRING.ms.jelly * f.durScale);
  const z = Math.min(zeta, 0.999), wd = omega * Math.sqrt(1 - z * z);
  const imp = (t: number) => Math.exp(-z * omega * t) * Math.sin(wd * t);
  let m = 1e-6;
  for (let t = 0; t <= total / 1000; t += 0.002) m = Math.max(m, Math.abs(imp(t)));
  const n = Math.max(2, Math.ceil(total / stepMs));
  const P = SPRING.punch * strength * f.b;
  const out: Sample[] = [];
  for (let i = 0; i <= n; i++) {
    const t = (i / n) * total / 1000;
    const taper = 1 - smooth((i / n - 0.7) / 0.3);
    const u = (imp(t) / m) * taper;
    const du = (imp(t + 0.004) - imp(t)) / m;                      // growing → taller (stretch), shrinking → wider
    const d = Math.max(-1, Math.min(1, du * 8)) * f.squash * 0.5 * taper;
    const size = 1 + P * u;
    out.push({ o: i / n, sx: soften(size * (1 - d)), sy: soften(size * (1 + d)), x: 0, y: 0, r: 0 });
  }
  Object.assign(out[out.length - 1], { o: 1, sx: 1, sy: 1 });
  return { samples: thin(out), duration: total };
}

// ------------------------------------------------------------------ exits: hop, then suck back
export interface ExitIn {
  feel: Feel;
  ms: number;
  to?: number;                       // end scale (→ the button it came from, or just small)
  x?: number; y?: number;            // end offset in px (a drop, or out to the side)
  rotate?: number;                   // end tilt
  fadeFrom?: number;                 // offset where the fade starts (0..1)
  baseY?: number;                    // px added to every translate-y (a toast's place in the stack)
  noScale?: boolean;                 // big panes: translate only (scaling them is costly on software rendering)
}
/** A quick, dramatic exit: a squat, a little hop that grows it (pre-bounce), then it sucks back small and drops,
 *  squashing as it goes. Faster than the entrance. */
export function exitKeyframes(o: ExitIn): { move: Keyframe[]; fade: Keyframe[]; duration: number } {
  const g = o.feel.grow, sq = o.feel.squash;
  const to = o.to ?? 0.3, x = o.x ?? 0, y = o.y ?? 0, r = o.rotate ?? 0;
  const out = "cubic-bezier(.2,.8,.3,1)", inn = "cubic-bezier(.55,0,.85,.25)";
  const hop = -150 * g;                                           // a few px up (9 px at Bounciness 100)
  const by = o.baseY ?? 0;
  const tr = (px: number, py: number) => `${n2(px)}px ${n2(py + by)}px`;
  const move: Keyframe[] = [
    { offset: 0, scale: "1 1", translate: tr(0, 0), rotate: "0deg", easing: out },
    { offset: 0.16, scale: `${n4(1 + g)} ${n4(1 - g * 0.9)}`, translate: tr(0, 0), rotate: "0deg", easing: out },
    { offset: 0.38, scale: `${n4(1 + g * 0.6)} ${n4(1 + g * 1.3)}`, translate: tr(-x * 0.06, hop), rotate: `${n2(-r * 0.25)}deg`, easing: inn },
    { offset: 1, scale: `${n4(to * (1 + sq * 0.6))} ${n4(to * (1 - sq * 0.6))}`, translate: tr(x, y), rotate: `${n2(r)}deg` },
  ];
  if (o.noScale) for (const k of move) delete k.scale;
  const ff = o.fadeFrom ?? 0.42;
  const fade: Keyframe[] = [{ offset: 0, opacity: 1 }, { offset: ff, opacity: 1, easing: "cubic-bezier(.5,0,.75,0)" }, { offset: 1, opacity: 0 }];
  return { move, fade, duration: Math.round(o.ms * o.feel.durScale) };
}

// ------------------------------------------------------------------ CSS for motion.css (entrances that need no JS)
/** The @keyframes and the per-level animation tokens motion.css uses (`--m-a-*`). Regenerated when the slider moves. */
export function springCss(f: Feel = feel()): string {
  const S = SPRING;
  const items = { spring: S.item, feel: f, ms: S.ms.item, windupMs: S.ms.windupItem };
  const kf: [string, BakeIn, string?][] = [
    ["ms-pop", { spring: S.pop, feel: f, ms: S.ms.pop, windupMs: S.ms.windup, scale: 0.5, y: 10 }],
    ["ms-card", { spring: S.pop, feel: f, ms: S.ms.pop, windupMs: S.ms.windup, scale: 0.55, y: 14, rotate: -f.tilt }],
    ["ms-rise", { ...items, scale: 0.7, y: 16 }],
    ["ms-rise-t", { ...items, feel: { ...f, squash: 0, windup: 0 }, y: 22 }],   // big panes: translate only (scaling is costly)
    ["ms-drop", { ...items, scale: 0.8, y: -16 }],
    ["ms-left", { ...items, scale: 0.75, x: -30, rotate: -f.tilt * 0.4 }],
    ["ms-right", { ...items, scale: 0.75, x: 30, rotate: f.tilt * 0.4 }],
    ["ms-chip", { ...items, scale: 0.4 }],
    ["ms-toast", { spring: S.toast, feel: f, ms: S.ms.toast, windupMs: S.ms.windupItem, scale: 0.6, y: 90, rotate: -f.tilt * 1.1 }, "var(--m-stack, 0px)"],
  ];
  const css: string[] = [];
  const dur: Record<string, number> = {};
  for (const [name, o, base] of kf) {
    const { samples, duration } = bakeSamples(o);
    css.push(toCss(name, samples, base ?? ""));
    dur[name] = duration;
  }
  const a = (k: string) => `${k} ${dur[k]}ms linear`;
  css.push(`:root[data-motion="full"]{--m-a-pop:${a("ms-pop")};--m-a-card:${a("ms-card")};--m-a-rise:${a("ms-rise")};` +
           `--m-a-rise-t:${a("ms-rise-t")};--m-a-drop:${a("ms-drop")};--m-a-left:${a("ms-left")};--m-a-right:${a("ms-right")};` +
           `--m-a-chip:${a("ms-chip")};--m-a-toast:${a("ms-toast")};--m-stagger:${Math.round(45 * f.durScale)}ms}`);
  return css.join("\n");
}

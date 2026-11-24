import { afterEach, describe, expect, it, vi } from "vitest";
import { enterPlan, exitPlan, hoverPlan, popPlan, pressPlan, releasePlan, setJuice, T, type Level, type Step } from "../src/motion";
import { closePlan, contentPlan, openPlan, slidePlan } from "../src/menu-motion";
import {
  bakeSamples, bounciness, calmFeel, exitKeyframes, feel, onBounciness, overshoot, setBounciness, soften, SPRING, springAt,
  springCss, zetaFor,
} from "../src/spring";

const GPU = new Set(["opacity", "translate", "scale", "rotate"]);

/** The value of one property at `ms` into a plan (linear between keyframes, as the baked springs play). */
function at(steps: Step[], prop: "opacity" | "scale" | "translate", ms: number): number[] | null {
  for (const s of steps) {
    if (!s.frames.some((f) => prop in f)) continue;
    const dur = Number(s.opts.duration), t = (ms - Number(s.opts.delay ?? 0)) / dur;
    const fr = s.frames.map((f, i) => ({ o: f.offset ?? i / (s.frames.length - 1), v: String(f[prop]).split(" ").map((x) => parseFloat(x)) }));
    if (t <= 0) return fr[0].v;
    if (t >= 1) return fr[fr.length - 1].v;
    const j = fr.findIndex((f) => f.o >= t);
    const a = fr[j - 1], b = fr[j], k = (t - a.o) / (b.o - a.o || 1);
    return a.v.map((v, i) => v + ((b.v[i] ?? b.v[0]) - v) * k);
  }
  return null;
}
const axes = (steps: Step[]) => steps.flatMap((s) => s.frames.flatMap((f) => (f.scale == null ? [] : String(f.scale).split(" ").map(Number))));
const longest = (steps: Step[]) => Math.max(0, ...steps.map((s) => Number(s.opts.duration ?? 0) + Number(s.opts.delay ?? 0)));
const props = (steps: Step[]) => new Set(steps.flatMap((s) => s.frames.flatMap((f) => Object.keys(f).filter((k) => k !== "offset" && k !== "easing"))));

/** Every full-level entrance the UI plays from JS. */
const entrances = (lv: Level): [string, Step[]][] => [
  ...(["pop", "rise", "drop", "left", "right"] as const).map((k) => [`enter ${k}`, enterPlan(k, lv)] as [string, Step[]]),
  ...(["origin", "left", "right", "below"] as const).map((k) => [`menu ${k}`, openPlan(lv, k)] as [string, Step[]]),
  ["content", contentPlan(lv, 0)], ["slide", slidePlan(lv, "right")],
];

afterEach(() => { setBounciness(SPRING.bounciness); setJuice("auto"); vi.unstubAllGlobals(); });

describe("the spring solver", () => {
  it("starts at 1 at rest and decays to 0; the first overshoot matches e^(−πζ/√(1−ζ²))", () => {
    const w = 16, z = 0.35;
    expect(springAt(w, z, 0)).toEqual({ x: 1, v: -0 });
    expect(Math.abs(springAt(w, z, 2).x)).toBeLessThan(1e-4);
    const wd = w * Math.sqrt(1 - z * z);
    expect(-springAt(w, z, Math.PI / wd).x).toBeCloseTo(overshoot(z), 6);   // the trough is the first overshoot
  });
  it("zetaFor inverts overshoot; 0 overshoot is (almost) critically damped", () => {
    for (const z of [0.2, 0.3, 0.5, 0.8]) expect(zetaFor(overshoot(z))).toBeCloseTo(z, 6);
    expect(zetaFor(0)).toBeGreaterThan(0.99);
  });
  it("soften never passes the peak and leaves values ≤ 1 alone", () => {
    expect(soften(0.7)).toBe(0.7);
    expect(soften(1.1)).toBeLessThan(1.1);
    expect(soften(1.05)).toBe(1.05);                              // small overshoots pass unchanged
    for (const v of [1.2, 1.5, 3, 100]) expect(soften(v)).toBeLessThanOrEqual(SPRING.peak);
  });
});

describe("full: cartoon entrances", () => {
  it("only animate compositor properties", () => {
    for (const [name, p] of entrances("full")) for (const k of props(p)) expect(GPU.has(k), `${name}: ${k}`).toBe(true);
    for (const p of [exitPlan("drop", "full"), closePlan("full"), popPlan("full"), pressPlan(), releasePlan(), hoverPlan()]) {
      for (const k of props(p)) expect(GPU.has(k), k).toBe(true);
    }
  });
  it("readable: opacity ≥ 0.9 by 110 ms (the wind-up is seen), and settled enough to read by 400 ms", () => {
    for (const [name, p] of entrances("full")) {
      expect(at(p, "opacity", 110)![0], name).toBeGreaterThanOrEqual(0.9);
      const s = at(p, "scale", 400);
      if (s) for (const v of s) { expect(v, `${name} scale@400`).toBeGreaterThan(0.88); expect(v, `${name} scale@400`).toBeLessThan(1.12); }
      const tr = at(p, "translate", 400);
      if (tr) for (const v of tr) expect(Math.abs(v), `${name} translate@400`).toBeLessThan(10);
    }
  });
  it("menus take ~0.5–0.7 s to land, list items a bit less; exits ~0.3–0.4 s", () => {
    const menu = longest(openPlan("full"));
    expect(menu).toBeGreaterThanOrEqual(500);
    expect(menu).toBeLessThanOrEqual(750);
    expect(longest(enterPlan("rise", "full"))).toBeGreaterThanOrEqual(400);
    expect(longest(enterPlan("rise", "full"))).toBeLessThan(menu);
    for (const p of [closePlan("full"), exitPlan("drop", "full")]) {
      expect(longest(p)).toBeGreaterThanOrEqual(280);
      expect(longest(p)).toBeLessThanOrEqual(400);
    }
  });
  it("overshoot is big (≈1.12–1.18 for a menu) but bounded, at every Bounciness", () => {
    expect(Math.max(...axes(openPlan("full")))).toBeGreaterThanOrEqual(1.12);
    for (const b of [0, 25, 50, 85, 100]) {
      setBounciness(b);
      for (const [name, p] of entrances("full")) expect(Math.max(...axes(p)), name).toBeLessThanOrEqual(SPRING.peak);
      expect(Math.max(...axes(popPlan("full", 2)))).toBeLessThanOrEqual(SPRING.peak);
    }
  });
  it("winds up first (squashed: wider than tall), then stretches (taller than wide) as it pops", () => {
    const f = openPlan("full")[1].frames.map((k) => ({ o: Number(k.offset), s: String(k.scale).split(" ").map(Number) }));
    const dur = Number(openPlan("full")[1].opts.duration);
    const windup = f.filter((k) => k.o * dur <= SPRING.ms.windup);
    expect(windup.some((k) => k.s[0] - k.s[1] > 0.03)).toBe(true);
    expect(f.some((k) => k.s[1] - k.s[0] > 0.05)).toBe(true);
    expect(f.at(-1)!.s).toEqual([1, 1]);
  });
  it("cards and toasts tilt and wobble upright (CSS springs)", () => {
    const css = springCss();
    for (const name of ["ms-pop", "ms-card", "ms-rise", "ms-left", "ms-right", "ms-drop", "ms-chip", "ms-toast", "ms-rise-t"]) {
      expect(css).toContain(`@keyframes ${name}{`);
    }
    const card = css.match(/@keyframes ms-card\{(.*?)\}\}/)![1];
    expect(card).toMatch(/rotate:-\d/);                           // lands tilted
    expect(card).toMatch(/rotate:\d/);                            // and wobbles past upright
    expect(css).toMatch(/@keyframes ms-toast\{0%\{[^}]*translate:0px calc\(var\(--m-stack, 0px\) \+ \d+/);   // from the edge
    expect(css).not.toMatch(/@keyframes ms-rise-t\{[^@]*scale:(?!1 1)/);   // the big-pane rise never scales
    for (const p of css.matchAll(/\{([a-z-]+):/g)) expect(["scale", "translate", "rotate", "--m-a-pop"].includes(p[1]), p[1]).toBe(true);
  });
  it("buttons: a press squashes, the release jellies past its shape and settles at rest; hover is one bob", () => {
    const [pr] = pressPlan()[0].frames.slice(-1).map((k) => String(k.scale).split(" ").map(Number));
    expect(pr[0]).toBeGreaterThan(1); expect(pr[1]).toBeLessThan(1);
    const rel = releasePlan(1)[0].frames.map((k) => String(k.scale).split(" ").map(Number));
    expect(rel[0][0]).toBeCloseTo(pr[0], 2);                      // starts where the squash left it
    expect(rel.some(([x, y]) => y > 1.02 && x < 1)).toBe(true);   // springs past: taller and narrower
    expect(rel.at(-1)).toEqual([1, 1]);
    expect(releasePlan(0)).toEqual([]);
    expect(hoverPlan()[0].opts.iterations ?? 1).toBe(1);
  });
});

describe("exits", () => {
  it("grow ~5 % before they shrink and drop, and fade only after the hop", () => {
    const k = exitKeyframes({ feel: feel(), ms: SPRING.ms.exit, to: 0.4, y: 20 });
    const grow = Math.max(...k.move.slice(1, -1).flatMap((f) => String(f.scale).split(" ").map(Number)));
    expect(grow).toBeGreaterThan(1.04);
    expect(grow).toBeLessThan(1.1);
    expect(k.fade.find((f) => Number(f.offset) >= 0.3)!.opacity).toBe(1);
    expect(k.move.at(-1)!.translate).toBe("0px 20px");
  });
});

describe("calm and minimal", () => {
  it("calm: the same springs scaled way down: ≤ 1 % overshoot, no squash, tilt or wind-up, shorter", () => {
    for (const [name, p] of entrances("calm")) {
      expect(Math.max(...axes(p)), name).toBeLessThanOrEqual(1.01);
      for (const s of p) for (const f of s.frames) {
        if (f.scale) { const [x, y] = String(f.scale).split(" ").map(Number); expect(Math.abs(x - (y ?? x)), name).toBeLessThan(1e-3); }
        if (f.rotate) expect(parseFloat(String(f.rotate)), name).toBe(0);
      }
      expect(longest(p), name).toBeLessThanOrEqual(400);
    }
    expect(calmFeel()).toMatchObject({ squash: 0, windup: 0, tilt: 0 });
    setBounciness(100);                                           // the slider is for full only
    expect(Math.max(...axes(openPlan("calm")))).toBeLessThanOrEqual(1.01);
  });
  it("minimal / reduce motion: quick fades only", () => {
    for (const [name, p] of entrances("min")) {
      if (!p.length) continue;
      expect([...props(p)], name).toEqual(["opacity"]);
      expect(longest(p), name).toBeLessThanOrEqual(T.fade + 10);
    }
    for (const p of [exitPlan("drop", "min"), closePlan("min")]) { expect([...props(p)]).toEqual(["opacity"]); expect(longest(p)).toBeLessThanOrEqual(T.fade); }
    expect(popPlan("min")).toEqual([]);
  });
});

describe("the Bounciness slider", () => {
  it("defaults high, clamps to 0–100 and falls back to the default for junk", () => {
    expect(bounciness()).toBe(SPRING.bounciness);
    expect(SPRING.bounciness).toBeGreaterThanOrEqual(70);
    setBounciness(150); expect(bounciness()).toBe(100);
    setBounciness(-5); expect(bounciness()).toBe(0);
    setBounciness(undefined); expect(bounciness()).toBe(SPRING.bounciness);
    setBounciness("40" as unknown as number); expect(bounciness()).toBe(40);
  });
  it("scales the overshoot: more bounciness, a bigger pop; 0 = no overshoot at all", () => {
    const peaks = [0, 30, 60, 85, 100].map((b) => { setBounciness(b); return Math.max(...axes(openPlan("full"))); });
    for (let i = 1; i < peaks.length; i++) expect(peaks[i]).toBeGreaterThan(peaks[i - 1]);
    expect(peaks[0]).toBeLessThanOrEqual(1.001);
    setBounciness(0);
    expect(Math.max(...axes(popPlan("full")))).toBeLessThanOrEqual(1.001);
    expect(releasePlan(1)).toEqual([]);                           // nothing to jelly
    expect(Math.max(...axes(exitPlan("drop", "full")))).toBeLessThanOrEqual(1);   // no pre-bounce
  });
  it("scales the length too (a little): no bounce is quicker, the default is the token lengths", () => {
    setBounciness(0);
    const calmish = longest(openPlan("full"));
    setBounciness(SPRING.bounciness);
    expect(feel().durScale).toBeCloseTo(1, 6);
    expect(longest(closePlan("full"))).toBe(SPRING.ms.close);
    expect(calmish).toBeLessThan(longest(openPlan("full")));
  });
  it("tells listeners (motion.ts rebuilds the CSS springs and drops its cache) only on a real change", () => {
    const fn = vi.fn();
    onBounciness(fn);
    setBounciness(SPRING.bounciness);
    expect(fn).not.toHaveBeenCalled();
    const before = springCss();
    setBounciness(30);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(springCss()).not.toBe(before);
    const peakLow = Math.max(...axes(enterPlan("pop", "full")));
    setBounciness(100);
    expect(Math.max(...axes(enterPlan("pop", "full")))).toBeGreaterThan(peakLow);   // the plan cache was dropped
  });
  it("a baked spring stays small: a few dozen keyframes at most", () => {
    const { samples } = bakeSamples({ spring: SPRING.pop, feel: feel(1), ms: SPRING.ms.pop, windupMs: SPRING.ms.windup, scale: 0.4, rotate: 6 });
    expect(samples.length).toBeLessThanOrEqual(45);
    expect(springCss().length).toBeLessThan(20_000);
  });
});

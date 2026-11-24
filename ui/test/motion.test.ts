import { afterEach, describe, expect, it, vi } from "vitest";
import {
  attentionPlan, confettiCount, countFrames, countUp, EASE, enter, enterPlan, exitPlan, leave, level, pop, popPlan,
  resolveLevel, setJuice, shake, shakePlan, stagger, staggerDelay, STAGGER_FULL, T, type Level, type Step,
} from "../src/motion";

/** Every scale axis a plan reaches ("1.1 0.9" → 1.1, 0.9). */
const axes = (steps: Step[]) => steps.flatMap((s) => s.frames.flatMap((f) => (f.scale == null ? [] : String(f.scale).split(" ").map(Number))));

const props = (steps: Step[]) => new Set(steps.flatMap((s) => s.frames.flatMap((f) => Object.keys(f).filter((k) => k !== "offset" && k !== "easing"))));
const longest = (steps: Step[]) => Math.max(0, ...steps.map((s) => Number(s.opts.duration ?? 0) + Number(s.opts.delay ?? 0)));
const GPU = new Set(["opacity", "translate", "scale", "rotate"]);
const LEVELS: Level[] = ["full", "calm", "min"];

/** A stand-in element: records what was animated. */
function fakeEl(connected = true) {
  const calls: { frames: Keyframe[]; opts: KeyframeAnimationOptions }[] = [];
  const el: any = {
    isConnected: connected, dataset: {}, style: {}, inert: false, textContent: "", attrs: {} as Record<string, string>,
    setAttribute(k: string, v: string) { this.attrs[k] = v; },
    remove: vi.fn(),
    animate(frames: Keyframe[], opts: KeyframeAnimationOptions) { calls.push({ frames, opts }); return { finished: Promise.resolve() }; },
  };
  return { el, calls };
}

afterEach(() => setJuice("auto"));

describe("motion level", () => {
  it("follows the Juice setting and the OS reduce-motion setting", () => {
    expect(resolveLevel("auto", false)).toBe("full");
    expect(resolveLevel(undefined, false)).toBe("full");
    expect(resolveLevel("full", false)).toBe("full");
    expect(resolveLevel("calm", false)).toBe("calm");
    expect(resolveLevel("minimal", false)).toBe("min");
    // reduce motion wins over any Juice choice
    for (const j of ["auto", "full", "calm", "minimal"]) expect(resolveLevel(j, true)).toBe("min");
  });
  it("a ?motion= flag overrides both (recordings, tests); junk is ignored", () => {
    expect(resolveLevel("minimal", true, "full")).toBe("full");
    expect(resolveLevel("full", false, "min")).toBe("min");
    expect(resolveLevel("calm", false, "wild")).toBe("calm");
  });
  it("setJuice switches the live level", () => {
    setJuice("minimal"); expect(level()).toBe("min");
    setJuice("calm"); expect(level()).toBe("calm");
    setJuice("auto"); expect(level()).toBe("full");
  });
});

describe("plans only animate GPU-friendly properties", () => {
  it.each(LEVELS)("%s", (lv) => {
    const all = [
      ...(["pop", "rise", "drop", "left", "right", "fade"] as const).map((k) => enterPlan(k, lv)),
      ...(["drop", "shrink", "fade", "left", "right"] as const).map((k) => exitPlan(k, lv)),
      popPlan(lv), shakePlan(lv), attentionPlan(lv),
    ];
    for (const p of all) for (const k of props(p)) expect(GPU.has(k), k).toBe(true);
  });
});

describe("readability", () => {
  it("entering text is fully opaque within T.read (about 110 ms) at every level", () => {
    for (const lv of LEVELS) for (const k of ["pop", "rise", "drop", "left", "right", "fade"] as const) {
      const fade = enterPlan(k, lv).find((s) => s.frames.some((f) => "opacity" in f))!;
      expect(Number(fade.opts.duration)).toBeLessThanOrEqual(T.read);
      expect(fade.frames.at(-1)!.opacity).toBe(1);
    }
  });
  it("a cascade never delays the last item by more than its cap (full: the last one still readable by 0.4 s)", () => {
    expect(staggerDelay(0, "full")).toBe(0);
    expect(staggerDelay(1, "full")).toBe(STAGGER_FULL.step);
    expect(staggerDelay(100, "full")).toBe(STAGGER_FULL.cap);
    expect(STAGGER_FULL.cap + T.read).toBeLessThanOrEqual(400);
    expect(staggerDelay(100, "calm")).toBe(T.staggerCap);
    expect(T.staggerCap + T.read).toBeLessThanOrEqual(250);
  });
});

describe("Juice minimal / reduced motion: quick fades only", () => {
  it("entrances and exits are a single short opacity fade, with no stagger", () => {
    for (const k of ["pop", "rise", "drop", "left", "right"] as const) {
      const p = enterPlan(k, "min", 200);
      expect([...props(p)]).toEqual(["opacity"]);
      expect(longest(p)).toBeLessThanOrEqual(120);                  // delay dropped too
    }
    for (const k of ["drop", "shrink", "left", "right"] as const) {
      const p = exitPlan(k, "min");
      expect([...props(p)]).toEqual(["opacity"]);
      expect(longest(p)).toBeLessThanOrEqual(120);
    }
    expect(staggerDelay(5, "min")).toBe(0);
  });
  it("punches, shakes, wobbles and confetti are off", () => {
    expect(popPlan("min")).toEqual([]);
    expect(shakePlan("min")).toEqual([]);
    expect(attentionPlan("min")).toEqual([]);
    expect(confettiCount("min")).toBe(0);
  });
  it("the runtime helpers follow it", () => {
    setJuice("minimal");
    const { el, calls } = fakeEl();
    enter(el, "pop");
    expect(calls).toHaveLength(1);
    expect(Object.keys(calls[0].frames[0])).toEqual(["opacity"]);
    pop(el); shake(el);
    expect(calls).toHaveLength(1);                                    // nothing more
    const { el: b, calls: bc } = fakeEl();
    stagger([b, b, b], "rise");
    expect(bc.every((c) => !c.opts.delay)).toBe(true);
  });
  it("a count-up jumps straight to the final number", () => {
    setJuice("minimal");
    const { el, calls } = fakeEl();
    countUp(el, 1, 9.5, (n) => `$${n.toFixed(2)}`);
    expect(el.textContent).toBe("$9.50");
    expect(calls).toHaveLength(0);
  });
});

describe("calm", () => {
  it("travels half as far, barely overshoots, doesn't squash or tilt, and is shorter than full", () => {
    const full = enterPlan("rise", "full")[1].frames[0].translate as string;
    const calm = enterPlan("rise", "calm")[1].frames[0].translate as string;
    expect(parseFloat(calm.split(" ")[1])).toBe(parseFloat(full.split(" ")[1]) / 2);
    for (const k of ["pop", "rise", "drop", "left", "right"] as const) {
      const p = enterPlan(k, "calm");
      expect(Math.max(...axes(p))).toBeLessThanOrEqual(1.01);
      for (const f of p[1].frames) { const [x, y] = String(f.scale).split(" ").map(Number); expect(Math.abs(x - y)).toBeLessThan(1e-3); }
      expect(p[1].frames.every((f) => f.rotate == null || parseFloat(String(f.rotate)) === 0)).toBe(true);
      expect(longest(p)).toBeLessThan(longest(enterPlan(k, "full")));
    }
    const peak = Math.max(...axes(popPlan("calm")));
    expect(peak).toBeLessThan(1.1);
    expect(longest(exitPlan("drop", "calm"))).toBeLessThan(longest(exitPlan("drop", "full")));
    expect(confettiCount("calm", 16)).toBe(8);
  });
});

describe("full", () => {
  it("entrances overshoot (a baked spring, not one cubic-bezier) and land exactly at rest", () => {
    const p = enterPlan("pop", "full");
    expect(p[1].opts.easing).toBe(EASE.linear);                    // the spring is in the keyframes
    expect(p[1].frames.length).toBeGreaterThan(8);
    expect(Math.max(...axes(p))).toBeGreaterThan(1.1);
    expect(p[1].frames.at(-1)).toMatchObject({ offset: 1, scale: "1 1", translate: "0px 0px" });
  });
  it("exits hop first (grow), then suck back small, faster than the entrance", () => {
    const exit = exitPlan("drop", "full");
    expect(longest(exit)).toBeLessThan(longest(enterPlan("pop", "full")));
    expect(longest(exit)).toBeGreaterThanOrEqual(280);             // dramatic, not a blink
    const move = exit.find((s) => s.frames.some((f) => f.scale))!;
    const first = move.frames.slice(0, -1).flatMap((f) => String(f.scale).split(" ").map(Number));
    expect(Math.max(...first)).toBeGreaterThan(1.03);              // the pre-bounce
    expect(Math.max(...String(move.frames.at(-1)!.scale).split(" ").map(Number))).toBeLessThan(0.6);
    expect(exit.find((s) => s.frames.some((f) => "opacity" in f))!.frames.at(-1)!.opacity).toBe(0);
  });
  it("a toast leaves from its place in the stack", () => {
    const move = exitPlan("drop", "full", 50).find((s) => s.frames.some((f) => f.translate))!;
    expect(move.frames[0].translate).toBe("0px 50px");
    expect(exitPlan("drop", "calm", 50)[1].frames[0].translate).toBe("0px 50px");
  });
  it("a punch rises above 1.1, jiggles, and settles back at exactly 1", () => {
    const p = popPlan("full");
    expect(Math.max(...axes(p))).toBeGreaterThan(1.1);
    expect(Math.min(...axes(p))).toBeLessThan(1);                  // the jiggle back
    expect(p[0].frames.at(-1)!.scale).toBe("1 1");
  });
});

describe("countFrames", () => {
  it("throttles to about 15 updates a second and always ends exactly on the target", () => {
    const f = countFrames(0, 7.31, 450);
    expect(f.length).toBe(7);
    expect(f.at(-1)).toBe(7.31);
    for (let i = 1; i < f.length; i++) expect(f[i]).toBeGreaterThanOrEqual(f[i - 1]);   // monotonic
  });
  it("counts down too", () => {
    const f = countFrames(10, 2, 300);
    expect(f.at(-1)).toBe(2);
    expect(f[0]).toBeLessThan(10);
  });
});

describe("leave", () => {
  it("stops taking clicks at once and removes the element after its exit", async () => {
    const { el, calls } = fakeEl();
    leave(el, "drop");
    expect(el.inert).toBe(true);
    expect(el.attrs["aria-hidden"]).toBe("true");
    expect(el.style.pointerEvents).toBe("none");
    expect(calls.length).toBeGreaterThan(0);
    await Promise.resolve(); await Promise.resolve();
    expect(el.remove).toHaveBeenCalledTimes(1);
    leave(el);                                                        // a second call is a no-op
    expect(el.remove).toHaveBeenCalledTimes(1);
  });
  it("an element that's already gone is just removed, with no animation", () => {
    const { el, calls } = fakeEl(false);
    leave(el);
    expect(calls).toHaveLength(0);
    expect(el.remove).toHaveBeenCalledTimes(1);
  });
});

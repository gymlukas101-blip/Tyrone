import { describe, expect, it } from "vitest";
import { POP_DUR, onAvatar, popAt } from "../src/avatar/hearingpop";

const sample = (kind: "on" | "off", strength = 1) => {
  const out = [];
  for (let t = 0; t <= POP_DUR[kind]; t += 1 / 60) out.push(popAt(kind, t, strength));
  return out;
};

describe("hearing pop (click Monkey)", () => {
  it("'on' crouches, stretches up with a hop, lands, settles back to rest", () => {
    const f = sample("on");
    expect(Math.min(...f.map((x) => x.sy))).toBeLessThan(0.9);          // anticipation squash / landing
    expect(Math.max(...f.map((x) => x.sy))).toBeGreaterThan(1.12);       // big stretch
    expect(Math.max(...f.map((x) => x.lift))).toBeGreaterThan(0.05);     // a hop
    const end = popAt("on", POP_DUR.on + 0.01);
    expect(end).toEqual({ sy: 1, sxz: 1, lift: 0, done: true });
  });

  it("'off' deflates low and wide, never hops, and recovers", () => {
    const f = sample("off");
    expect(Math.min(...f.map((x) => x.sy))).toBeLessThan(0.86);
    expect(Math.max(...f.map((x) => x.sxz))).toBeGreaterThan(1.07);
    expect(Math.max(...f.map((x) => x.lift))).toBeLessThanOrEqual(0);
    expect(popAt("off", POP_DUR.off).done).toBe(true);
  });

  it("keeps volume (sxz = 1/sqrt(sy)), halves for Juice calm, and is off for minimal / reduced motion", () => {
    for (const x of sample("on")) expect(x.sxz).toBeCloseTo(1 / Math.sqrt(x.sy), 6);
    const full = Math.max(...sample("on").map((x) => x.sy - 1));
    const calm = Math.max(...sample("on", 0.5).map((x) => x.sy - 1));
    expect(calm).toBeCloseTo(full / 2, 6);
    expect(popAt("on", 0.2, 0)).toEqual({ sy: 1, sxz: 1, lift: 0, done: true });
  });

  it("hit-tests an ellipse inside his on-screen box", () => {
    const box = { left: 100, top: 100, right: 300, bottom: 500 };
    expect(onAvatar(200, 300, box)).toBe(true);       // belly
    expect(onAvatar(105, 105, box)).toBe(false);      // the box corner is jungle, not monkey
    expect(onAvatar(50, 300, box)).toBe(false);
  });
});

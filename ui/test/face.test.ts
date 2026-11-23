import { describe, expect, it } from "vitest";
import { PerformanceDirector, cueFor } from "../src/avatar/acting";
import { FaceMixer, approach } from "../src/avatar/face";

const run = (m: FaceMixer, input: any, seconds: number, fps: number) => {
  let out: Record<string, number> = {};
  for (let i = 0; i < Math.round(seconds * fps); i++) out = m.update(input, 1 / fps);
  return out;
};
const base = { talking: false, visemes: {}, level: 0, acting: {}, emote: {}, override: {} };

describe("face mixer", () => {
  it("eases the same at 15, 30, 60 and 144 fps (time-based, not per-frame)", () => {
    const at = (fps: number) => run(new FaceMixer(), { ...base, talking: true, visemes: { viseme_aa: 1 }, level: 0.6 }, 1 / 15, fps).viseme_aa;
    const vals = [15, 30, 60, 120].map(at);                        // the same 67 ms at every frame rate
    for (const v of vals) expect(Math.abs(v - vals[3])).toBeLessThan(1e-9);
    // the old per-frame factors gave 0.6 after one 15 fps frame but 0.97 after four 60 fps frames
    const legacy = (frames: number) => 1 - Math.pow(0.4, frames);
    expect(legacy(4) - legacy(1)).toBeGreaterThan(0.3);
  });

  it("lips meet on M/B/P even while smiling", () => {
    const m = new FaceMixer();
    const out = run(m, { ...base, talking: true, visemes: { viseme_PP: 1 }, level: 0.5, emote: { smile: 0.9 } }, 0.3, 60);
    expect(out.viseme_PP).toBeGreaterThan(0.95);
    expect(out.smile).toBeLessThan(0.45);           // a closed-mouth smile curve may stay (warmth)…
    const grin = run(new FaceMixer(), { ...base, talking: true, visemes: { viseme_PP: 1 }, level: 0.5, emote: { bigGrin: 0.9 } }, 0.3, 60);
    expect(grin.bigGrin).toBeLessThan(0.05);        // …but a lip-parting grin lets go so the lips meet
    expect(out.jawOpen).toBeLessThan(0.05);
  });

  it("a smile tints speech instead of fighting it", () => {
    const talk = run(new FaceMixer(), { ...base, talking: true, visemes: { viseme_aa: 1 }, level: 0.7, emote: { smile: 0.9 } }, 0.4, 60);
    const quiet = run(new FaceMixer(), { ...base, emote: { smile: 0.9 } }, 0.6, 60);
    expect(quiet.smile).toBeGreaterThan(0.85);
    expect(talk.smile).toBeGreaterThan(0.2);
    expect(talk.smile).toBeLessThan(quiet.smile * 0.7);
  });

  it("vowel shape and jaw don't double-count", () => {
    const aa = run(new FaceMixer(), { ...base, talking: true, visemes: { viseme_aa: 1 }, level: 0.75 }, 0.4, 60);
    const ss = run(new FaceMixer(), { ...base, talking: true, visemes: { viseme_SS: 1 }, level: 0.75 }, 0.4, 60);
    expect(aa.jawOpen).toBeLessThan(ss.jawOpen);   // the AA shape already opens the mouth
  });

  it("asymmetric brows survive speech", () => {
    const out = run(new FaceMixer(), { ...base, talking: true, visemes: { viseme_E: 1 }, level: 0.6, acting: { browUp_L: 0.7 } }, 0.5, 60);
    expect(out.browUp_L).toBeGreaterThan(0.6);
    expect(out.browUp_R ?? 0).toBe(0);
  });

  it("an interrupt clears the mouth at once; overrides (blink, yawn) win", () => {
    const m = new FaceMixer();
    run(m, { ...base, talking: true, visemes: { viseme_O: 1 }, level: 0.7 }, 0.3, 60);
    m.resetSpeech();
    const out = m.update({ ...base, override: { blink_L: 1, blink_R: 1 } }, 1 / 60);
    expect(out.viseme_O).toBe(0);
    expect(out.jawOpen).toBe(0);
    expect(out.blink_L).toBe(1);
  });

  it("silence while idle leaves no jitter", () => {
    const out = run(new FaceMixer(), base, 1, 60);
    for (const v of Object.values(out)) expect(v).toBe(0);
  });

  it("approach is exact at dt=0 and converges", () => {
    expect(approach(0.2, 1, 0, 0.1)).toBe(0.2);
    expect(approach(0, 1, 1, 0.05)).toBeGreaterThan(0.99);
  });
});

describe("performance director", () => {
  it("reads intent from the words, not loudness", () => {
    expect(cueFor("Well, actually that's due Friday.")).toBe("skeptical");
    expect(cueFor("Whoa, that's a lot of homework.")).toBe("surprised");
    expect(cueFor("Nice, you nailed it!")).toBe("excited");
    expect(cueFor("Sorry, I couldn't find it.")).toBe("sympathetic");
    expect(cueFor("Want me to open it?")).toBe("curious");
    expect(cueFor("It's due Friday.")).toBeNull();          // most sentences: no reaction (restraint)
  });

  it("anticipates, hits, holds, then settles; one reaction at a time with a cooldown", () => {
    const d = new PerformanceDirector();
    d.setState("speaking");
    expect(d.sentence("Well, actually it moved.")).toBe("skeptical");
    const ant = d.update(0.05);
    const hit = d.update(0.15);
    expect(hit.browUp_L).toBeGreaterThan(ant.browUp_L ?? 0);      // anticipation is smaller than the hit
    for (let i = 0; i < 20; i++) d.update(0.05);
    expect(d.update(0.05).browUp_L ?? 0).toBeGreaterThan(0.4);    // a readable hold
    expect(d.sentence("Whoa, really?")).toBeNull();               // cooldown: no stacked reactions
    for (let i = 0; i < 40; i++) d.update(0.05);
    expect(d.cue).toBeNull();
    expect(d.update(0.05).browUp_L ?? 0).toBe(0);                 // settled back to calm
  });

  it("states have a resting attitude and a new state drops a stale reaction", () => {
    const d = new PerformanceDirector();
    d.setState("listening");
    expect(d.update(0.05).browsUp).toBeGreaterThan(0);
    d.play("excited");
    d.setState("thinking");
    expect(d.cue).toBeNull();
    expect(d.update(0.05).browUp_L).toBeGreaterThan(0);
  });
});

describe("brows (V2 per-side morphs)", () => {
  it("a loud onset while talking lifts the brows briefly, rate-limited, never while silent", () => {
    const m = new FaceMixer();
    let out = run(m, { ...base, talking: true, level: 0.05 }, 1.0, 60);   // settle the slow follower
    expect(out.browsUp ?? 0).toBeLessThan(0.01);
    out = m.update({ ...base, talking: true, level: 0.7 }, 1 / 60);       // a stressed syllable
    expect(out.browsUp).toBeGreaterThan(0.15);
    expect((out.browInnerUp_L ?? 0) + (out.browOuterUp_L ?? 0) + (out.browInnerUp_R ?? 0)).toBeGreaterThan(0.2);
    const n = m.beat.n;
    run(m, { ...base, talking: true, level: 0.05 }, 0.1, 60);
    m.update({ ...base, talking: true, level: 0.8 }, 1 / 60);              // too soon: no second beat
    expect(m.beat.n).toBe(n);
    out = run(m, { ...base, talking: false, level: 0.9 }, 0.05, 60);       // stops with speech
    expect(out.browsUp ?? 0).toBe(0);
  });

  it("new cues use the per-side brows and keep the shared keys for older models", () => {
    expect(cueFor("Uh-oh, that essay is due tomorrow.")).toBe("worried");
    expect(cueFor("Okay, let's do this.")).toBe("focused");
    const d = new PerformanceDirector();
    d.setState("speaking");
    d.play("skeptical");
    let s: Record<string, number> = {};
    for (let i = 0; i < 30; i++) s = d.update(1 / 60);
    expect(s.browUp_L).toBeGreaterThan(0.5);                                // V1 key still there
    expect(s.browDown_R).toBeGreaterThan(0.3);                              // V2: the other brow drops (asymmetry)
    d.play("worried");
    for (let i = 0; i < 30; i++) s = d.update(1 / 60);
    expect(s.browInnerUp_L).toBeGreaterThan(0.4);
    expect(s.browSqueeze).toBeGreaterThan(0.3);
  });
});

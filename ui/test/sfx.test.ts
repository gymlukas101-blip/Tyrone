import { beforeEach, describe, expect, it, vi } from "vitest";
import { peakRmsDb, Sfx, shuffle } from "../src/avatar/sfx";

// ---- a small fake Web Audio graph: records what was started, stopped, connected and how loud
class Param {
  value: number;
  events: [string, number, number][] = [];
  constructor(v = 1) { this.value = v; }
  setValueAtTime(v: number, t: number) { this.value = v; this.events.push(["set", v, t]); }
  linearRampToValueAtTime(v: number, t: number) { this.value = v; this.events.push(["ramp", v, t]); }
  exponentialRampToValueAtTime(v: number, t: number) { this.value = v; this.events.push(["exp", v, t]); }
  setTargetAtTime(v: number, t: number) { this.value = v; this.events.push(["target", v, t]); }
  cancelScheduledValues() { /* fake */ }
}
class Node {
  out: Node[] = [];
  connect(n: Node) { this.out.push(n); return n; }
  disconnect() { this.out = []; }
}
class Gain extends Node { gain = new Param(1); }
class Source extends Node {
  buffer: FakeBuffer | null = null;
  loop = false;
  playbackRate = new Param(1);
  started = false;
  stoppedAt: number | null = null;
  onended: (() => void) | null = null;
  start() { this.started = true; }
  stop(t = 0) { this.stoppedAt = t; }
}
class FakeBuffer {
  numberOfChannels = 1;
  sampleRate = 48000;
  data: Float32Array;
  constructor(public length: number, amp: number) { this.data = new Float32Array(length).fill(amp); }
  get duration() { return this.length / this.sampleRate; }
  getChannelData() { return this.data; }
}
class FakeCtx {
  currentTime = 0;
  state = "running";
  sampleRate = 48000;
  destination = new Node();
  sources: Source[] = [];
  limiter: any = null;
  createGain() { return new Gain(); }
  createBufferSource() { const s = new Source(); this.sources.push(s); return s; }
  createDynamicsCompressor() {
    const n: any = new Node();
    for (const k of ["threshold", "knee", "ratio", "attack", "release"]) n[k] = new Param(0);
    this.limiter = n;
    return n;
  }
  createOscillator() { const o: any = new Source(); o.frequency = new Param(440); o.type = "sine"; return o; }
  createBiquadFilter() { const f: any = new Node(); f.frequency = new Param(1000); f.Q = new Param(1); f.type = "bandpass"; return f; }
  createBuffer(_c: number, len: number) { return new FakeBuffer(len, 0); }
  async decodeAudioData(data: ArrayBuffer) {
    const [len, amp] = new Float32Array(data);              // test files encode (length, amplitude)
    return new FakeBuffer(len, amp) as unknown as AudioBuffer;
  }
  async resume() { this.state = "running"; }
}
const file = (len: number, amp: number) => new Float32Array([len, amp]).buffer;

async function rig(kit: Record<string, [number, number][]>) {
  const ctx = new FakeCtx();
  const files: Record<string, ArrayBuffer> = {};
  const cues: Record<string, string[]> = {};
  for (const [cue, takes] of Object.entries(kit)) {
    cues[cue] = takes.map((_, i) => `sfx/${cue}_${i + 1}.ogg`);
    takes.forEach(([len, amp], i) => { files[`sfx/${cue}_${i + 1}.ogg`] = file(len, amp); });
  }
  const sfx = new Sfx({ makeContext: () => ctx as unknown as AudioContext, fetch: async (s) => {
    if (!(s in files)) throw new Error("404");
    return files[s];
  } });
  await sfx.attach({ bundled: async () => cues, user: async () => ({}), userData: async () => null });
  await sfx.warming;
  return { sfx, ctx };
}
const gainOf = (ctx: FakeCtx, s: Source) => (s.out[0] as Gain).gain.value;

beforeEach(() => { vi.useFakeTimers(); vi.spyOn(performance, "now").mockReturnValue(0); });

describe("shuffle bag", () => {
  it("Fisher-Yates is unbiased: every take leads equally often", () => {
    let seed = 1;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const first = [0, 0, 0, 0];
    for (let i = 0; i < 40000; i++) first[shuffle([0, 1, 2, 3], rnd)[0]]++;
    for (const n of first) expect(Math.abs(n / 40000 - 0.25)).toBeLessThan(0.01);
  });

  it("plays every take once before repeating, never the same take twice in a row", async () => {
    const { sfx, ctx } = await rig({ boing: [[4800, 0.5], [4800, 0.51], [4800, 0.52], [4800, 0.53]] });
    const order: (FakeBuffer | null)[] = [];
    for (let i = 0; i < 12; i++) {
      vi.spyOn(performance, "now").mockReturnValue(1000 * (i + 1));
      sfx.play("boing");
      order.push(ctx.sources.at(-1)!.buffer);
      vi.advanceTimersByTime(1000);                          // each take ends before the next play
    }
    expect(ctx.sources.length).toBe(12);
    for (let r = 0; r < 3; r++) expect(new Set(order.slice(r * 4, r * 4 + 4)).size).toBe(4);
    for (let i = 1; i < order.length; i++) expect(order[i]).not.toBe(order[i - 1]);
  });

  it("a rejected take (Sound Lab) never plays", async () => {
    const { sfx, ctx } = await rig({ tap: [[4800, 0.5], [4800, 0.2]] });
    sfx.rejects = new Set(["tap_2"]);
    for (let i = 0; i < 6; i++) { vi.spyOn(performance, "now").mockReturnValue(1000 * (i + 1)); sfx.play("tap"); vi.advanceTimersByTime(1000); }
    expect(new Set(ctx.sources.map((s) => s.buffer!.data[0]))).toEqual(new Set([0.5]));
  });
});

describe("levels", () => {
  it("takes are leveled to their cue's median (a quiet or hot take doesn't jump out), within ±6 dB", async () => {
    const { sfx, ctx } = await rig({ check: [[4800, 0.12], [4800, 0.2], [4800, 0.33]] });
    const heard: number[] = [];
    vi.spyOn(Math, "random").mockReturnValue(0.5);          // no ±2 dB jitter, no pitch jitter
    for (let i = 0; i < 3; i++) {
      vi.spyOn(performance, "now").mockReturnValue(1000 * (i + 1));
      sfx.play("check");
      const s = ctx.sources.at(-1)!;
      heard.push(20 * Math.log10(s.buffer!.data[0] * gainOf(ctx, s)));
    }
    expect(Math.max(...heard) - Math.min(...heard)).toBeLessThan(0.01);   // raw spread was 8.8 dB
    vi.restoreAllMocks();
  });

  it("peakRmsDb measures the loudest 10 ms", () => {
    const b = new FakeBuffer(4800, 0.5);
    expect(peakRmsDb(b)).toBeCloseTo(20 * Math.log10(0.5), 1);
  });

  it("a safety limiter sits on the master and volume/ducking still apply", async () => {
    const { sfx, ctx } = await rig({ pop: [[2400, 0.5]] });
    expect(ctx.limiter.threshold.value).toBe(-6);
    expect(ctx.limiter.ratio.value).toBe(20);
    sfx.setVolume(0.3);
    sfx.duck(true);
    sfx.play("pop");
    expect(ctx.sources.length).toBe(1);
  });
});

describe("interface sounds", () => {
  it("a new UI sound cuts the ringing click short; one interface sound at a time", async () => {
    const { sfx, ctx } = await rig({ ui_click: [[9600, 0.5]], ui_open: [[9600, 0.5]] });
    sfx.play("ui_click");
    const click = ctx.sources.at(-1)!;
    vi.spyOn(performance, "now").mockReturnValue(10);
    sfx.play("ui_open");
    expect(click.stoppedAt).not.toBeNull();
    expect(ctx.sources.at(-1)!.stoppedAt).toBeNull();
  });

  it("a lower-rank UI sound doesn't cut off a notification", async () => {
    const { sfx, ctx } = await rig({ notify: [[24000, 0.5]], ui_open: [[9600, 0.5]] });
    sfx.play("notify");
    const chime = ctx.sources.at(-1)!;
    vi.spyOn(performance, "now").mockReturnValue(20);
    sfx.play("ui_open");
    expect(chime.stoppedAt).toBeNull();
    expect(ctx.sources.length).toBe(1);
  });

  it("30 rapid clicks: the cooldown keeps it to a handful, never more than one ringing", async () => {
    const { sfx, ctx } = await rig({ ui_click: [[9600, 0.5], [9600, 0.4]] });
    for (let i = 0; i < 30; i++) { vi.spyOn(performance, "now").mockReturnValue(i * 10); sfx.play("ui_click"); }
    expect(ctx.sources.length).toBeLessThanOrEqual(8);       // 300 ms / 40 ms cooldown
    expect(ctx.sources.filter((s) => s.stoppedAt === null).length).toBe(1);
  });
});

describe("polyphony and stopping", () => {
  it("caps simultaneous character sounds at 8; UI still answers", async () => {
    const kit: Record<string, [number, number][]> = { ui_click: [[4800, 0.5]] };
    for (let i = 0; i < 10; i++) kit[`fx${i}`] = [[48000, 0.3]];
    const { sfx, ctx } = await rig(kit);
    for (let i = 0; i < 10; i++) sfx.play(`fx${i}`);
    expect(ctx.sources.length).toBe(8);
    sfx.play("ui_click");
    expect(ctx.sources.length).toBe(9);
    expect(sfx.liveVoices).toBe(9);
    vi.advanceTimersByTime(2000);
    expect(sfx.liveVoices).toBe(0);                            // voices are released when they end
  });

  it("stopAll silences everything that's ringing", async () => {
    const { sfx, ctx } = await rig({ slam: [[80000, 0.5]], boing: [[48000, 0.5]] });
    sfx.play("slam"); sfx.play("boing");
    sfx.stopAll();
    expect(ctx.sources.every((s) => s.stoppedAt !== null)).toBe(true);
  });
});

describe("loops", () => {
  it("loop() is a real loop, deduplicated, and stop() fades it out and frees it", async () => {
    const { sfx, ctx } = await rig({ ticktock_loop: [[96000, 0.3]] });
    expect(ctx.sources.length).toBe(0);                       // loops aren't decoded or started up front
    const a = await sfx.loop("ticktock_loop");
    const b = await sfx.loop("ticktock_loop");
    expect(a).toBe(b);
    expect(ctx.sources.length).toBe(1);
    expect(ctx.sources[0].loop).toBe(true);
    expect(sfx.activeLoops).toEqual(["ticktock_loop"]);
    a!.stop(0.3);
    a!.stop(0.3);                                              // harmless twice
    expect(ctx.sources[0].stoppedAt).toBeCloseTo(0.32, 5);
    expect(sfx.activeLoops).toEqual([]);
    expect(a!.playing).toBe(false);
  });

  it("stopAll stops loops too; a missing loop cue returns null", async () => {
    const { sfx, ctx } = await rig({ jungle_loop: [[96000, 0.1]] });
    await sfx.loop("jungle_loop");
    sfx.stopAll();
    expect(ctx.sources[0].stoppedAt).not.toBeNull();
    expect(await sfx.loop("nope_loop")).toBeNull();
  });
});

describe("loading", () => {
  it("hot cues are ready before attach() returns, so the first click is never silent; the rest load after", async () => {
    const ctx = new FakeCtx();
    let releaseRest!: () => void;
    const gate = new Promise<void>((r) => { releaseRest = r; });
    const sfx = new Sfx({ makeContext: () => ctx as unknown as AudioContext, fetch: async (s) => {
      if (!s.includes("ui_click")) await gate;               // everything but the hot cue is slow
      return file(4800, 0.5);
    } });
    await sfx.attach({ bundled: async () => ({ ui_click: ["sfx/ui_click_1.ogg"], slam: ["sfx/slam_1.ogg"] }),
      user: async () => ({}), userData: async () => null });  // returns although slam is still loading
    sfx.play("ui_click");
    expect(ctx.sources.length).toBe(1);
    releaseRest();
    await sfx.warming;
    sfx.play("slam");
    expect(ctx.sources.length).toBe(2);
  });

  it("a missing file fails quietly and the other takes still play", async () => {
    const ctx = new FakeCtx();
    const sfx = new Sfx({ makeContext: () => ctx as unknown as AudioContext, fetch: async (s) => {
      if (s.endsWith("_2.ogg")) throw new Error("404");
      return file(4800, 0.5);
    } });
    await sfx.attach({ bundled: async () => ({ tap: ["sfx/tap_1.ogg", "sfx/tap_2.ogg"] }), user: async () => ({}),
      userData: async () => null });
    await sfx.warming;
    for (let i = 0; i < 4; i++) { vi.spyOn(performance, "now").mockReturnValue(1000 * (i + 1)); sfx.play("tap"); }
    expect(ctx.sources.length).toBe(4);
  });

  it("a cue with no takes falls back to its synth recipe; an unknown cue is silent", async () => {
    const { sfx, ctx } = await rig({});
    sfx.play("nothing_here");
    expect(ctx.sources.length).toBe(0);
    expect(() => sfx.play("pop")).not.toThrow();               // synth fallback (oscillators, not buffer sources)
  });

  it("Sound Lab preview: a new preview stops the previous one", async () => {
    const { sfx, ctx } = await rig({ boing: [[48000, 0.5], [48000, 0.4]] });
    await sfx.preview("sfx/boing_1.ogg");
    await sfx.preview("sfx/boing_2.ogg");
    const [a, b] = ctx.sources.slice(-2);
    expect(a.stoppedAt).not.toBeNull();
    expect(b.stoppedAt).toBeNull();
  });
});

describe("Sound Lab variants", () => {
  it("useVariant swaps a cue's takes and switching back restores the shipped ones", async () => {
    const ctx = new FakeCtx();
    const files: Record<string, ArrayBuffer> = { "sfx/check_1.ogg": file(4800, 0.5), "sfx/candidates/check-B_1.ogg": file(4800, 0.25) };
    const sfx = new Sfx({ makeContext: () => ctx as unknown as AudioContext, fetch: async (s) => files[s] });
    await sfx.attach({ bundled: async () => ({ check: ["sfx/check_1.ogg"] }), user: async () => ({}), userData: async () => null });
    await sfx.useVariant("check", ["sfx/candidates/check-B_1.ogg"]);
    expect(sfx.cues().check).toEqual(["sfx/candidates/check-B_1.ogg"]);
    sfx.play("check");
    expect(ctx.sources.at(-1)!.buffer!.data[0]).toBe(0.25);
    await sfx.useVariant("check", null);
    expect(sfx.cues().check).toEqual(["sfx/check_1.ogg"]);
  });
});

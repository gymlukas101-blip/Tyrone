// Monkey's little sound engine (Web Audio): buses, ducking under his voice, variation, cooldowns.
// Until the recorded/ElevenLabs sound kit lands, cues are synthesized (tiny, zero asset bytes).
// Rules from docs/ANIMATION-UI-DIRECTION.md: frequent sounds are short and quiet, every play is slightly
// different (pitch ±5%, volume ±2 dB), each cue has a cooldown, and SFX duck ~10 dB while Monkey talks.

export type Juice = "full" | "calm" | "minimal";
export type SynthCue =
  | "pop" | "zPop" | "snore" | "startle" | "boing" | "sparkle" | "whoosh" | "yawn" | "thump" | "tick" | "sweat";
/** Any cue name from the sound kit (ui/public/sfx/index.json or sounds made on this PC); synth cues are fallbacks. */
export type Cue = SynthCue | (string & {});

/** Loads the recorded kit lazily. Bundled files come over HTTP; sounds made on this PC come via the bridge. */
export interface SoundSource {
  bundled(): Promise<Record<string, string[]>>;
  user(): Promise<Record<string, string[]>>;
  userData(rel: string): Promise<ArrayBuffer | null>;
}

const COOLDOWN_MS: Record<string, number> = {
  "vocal/laugh": 4000, "vocal/yawn": 8000, "vocal/hmm": 15000, "vocal/woohoo": 6000, "vocal/hoohoo": 5000,
  "vocal/gasp": 3000, "vocal/snort_wake": 3000, "vocal/oh_banana": 600000, chest_thump: 90, footstep: 120,
  reward: 3000, confetti: 1500, ui_click: 40, check: 60,
  pop: 80, zPop: 300, snore: 2500, startle: 3000, boing: 400, sparkle: 1500, whoosh: 150, yawn: 8000,
  thump: 120, tick: 70, sweat: 900,
};
// Per-cue loudness (dB) relative to the SFX bus: common cues sit low.
const LEVEL_DB: Record<string, number> = {
  pop: -14, zPop: -20, snore: -16, startle: -8, boing: -12, sparkle: -12, whoosh: -16, yawn: -14,
  thump: -10, tick: -22, sweat: -18,
};
// Cues allowed at each juice level.
const ALLOWED: Record<Juice, Set<string> | "all"> = {
  full: "all",
  calm: new Set<string>(["zPop", "snore", "startle", "sparkle", "thump", "tick", "check", "ui_click", "notify", "reward",
    "vocal/yawn", "vocal/snort_wake", "vocal/laugh", "vocal/woohoo"]),
  minimal: new Set<string>(),
};
// Recorded samples are loudness-normalized offline, so they play near unity (per-cue trims only).
const SAMPLE_DB: Record<string, number> = { snore: -6, zPop: -4, tick: -6, jungle_loop: -8, ui_click: -6, footstep: -4 };

const db = (v: number) => Math.pow(10, v / 20);
const jitter = (amt: number) => 1 + (Math.random() * 2 - 1) * amt;

export class Sfx {
  private ctx: AudioContext | null = null;
  private master!: GainNode;
  private bus!: GainNode;
  private last = new Map<Cue, number>();
  private noise: AudioBuffer | null = null;
  private live = 0;
  juice: Juice = "full";
  volume = 0.7;          // 0..1 from Settings
  private ducked = false;
  private speaking = false;
  private kit = new Map<string, string[]>();          // cue -> sources ("sfx/x_1.ogg" or "user:vocal/x_1.wav")
  private buffers = new Map<string, AudioBuffer | "loading" | "failed">();
  private bags = new Map<string, string[]>();
  private lastTake = new Map<string, string>();
  rejects = new Set<string>();                          // takes turned off in the Sound Lab ("laugh_2")
  private source: SoundSource | null = null;

  /** Plug in the recorded kit (called once the bridge is ready). */
  async attach(src: SoundSource) {
    this.source = src;
    const add = (m: Record<string, string[]>, prefix = "") => {
      for (const [cue, files] of Object.entries(m)) this.kit.set(cue, [...(this.kit.get(cue) ?? []), ...files.map((f) => prefix + f)]);
    };
    try { add(await src.bundled()); } catch { /* no bundled kit */ }
    try { add(await src.user(), "user:"); } catch { /* none made yet */ }
    this.prefetch();
  }

  cues(): Record<string, string[]> { return Object.fromEntries(this.kit); }

  /** Re-read sounds made on this PC (after "Make Monkey's voice set" finishes). */
  async reloadUser() {
    if (!this.source) return;
    for (const [cue, files] of this.kit) {
      const kept = files.filter((f) => !f.startsWith("user:"));
      if (kept.length) this.kit.set(cue, kept); else this.kit.delete(cue);
    }
    for (const k of [...this.buffers.keys()]) if (k.startsWith("user:")) this.buffers.delete(k);
    this.bags.clear();
    try {
      for (const [cue, files] of Object.entries(await this.source.user()))
        this.kit.set(cue, [...(this.kit.get(cue) ?? []), ...files.map((f) => "user:" + f)]);
    } catch { /* none */ }
    this.prefetch();
  }

  /** Sound Lab: play one exact take, ignoring juice level and cooldowns. */
  async preview(src: string) {
    const ctx = this.ensure();
    if (!ctx) return;
    await ctx.resume().catch(() => {});
    const buf = await this.load(src);
    if (!buf) return;
    const s = ctx.createBufferSource();
    s.buffer = buf;
    s.connect(this.master);
    s.start();
  }

  takeOf(src: string) { return this.takeName(src); }

  private takeName(src: string) { return src.split("/").pop()!.replace(/\.(ogg|wav)$/, ""); }

  private async prefetch() {
    const ctx = this.ensure();
    if (!ctx) return;
    for (const files of this.kit.values()) for (const f of files) void this.load(f);
  }

  private async load(src: string): Promise<AudioBuffer | null> {
    const have = this.buffers.get(src);
    if (have && have !== "loading" && have !== "failed") return have;
    if (have) return null;
    const ctx = this.ensure();
    if (!ctx) return null;
    this.buffers.set(src, "loading");
    try {
      let data: ArrayBuffer | null;
      if (src.startsWith("user:")) data = (await this.source?.userData(src.slice(5))) ?? null;
      else data = await (await fetch(src)).arrayBuffer();
      if (!data) throw new Error("missing");
      const buf = await ctx.decodeAudioData(data);
      this.buffers.set(src, buf);
      return buf;
    } catch {
      this.buffers.set(src, "failed");
      return null;
    }
  }

  /** Shuffle bag: every take plays once before any repeats, and never the same take twice in a row. */
  private pick(cue: string): AudioBuffer | null {
    const files = (this.kit.get(cue) ?? []).filter((f) => !this.rejects.has(this.takeName(f)));
    const ready = files.filter((f) => { const b = this.buffers.get(f); return b && b !== "loading" && b !== "failed"; });
    if (!ready.length) { files.forEach((f) => void this.load(f)); return null; }
    let bag = (this.bags.get(cue) ?? []).filter((f) => ready.includes(f));
    if (!bag.length) {
      bag = [...ready].sort(() => Math.random() - 0.5);
      if (bag.length > 1 && bag[0] === this.lastTake.get(cue)) bag.push(bag.shift()!);
    }
    const f = bag.shift()!;
    this.bags.set(cue, bag);
    this.lastTake.set(cue, f);
    return this.buffers.get(f) as AudioBuffer;
  }

  has(cue: string) { return this.kit.has(cue); }

  constructor() {
    const unlock = () => { this.ensure(); this.ctx?.resume().catch(() => {}); };
    window.addEventListener("pointerdown", unlock, { capture: true });
    window.addEventListener("keydown", unlock, { capture: true });
  }

  private ensure(): AudioContext | null {
    if (this.ctx) return this.ctx;
    try {
      this.ctx = new AudioContext();
    } catch {
      return null;
    }
    this.master = this.ctx.createGain();
    this.bus = this.ctx.createGain();
    this.bus.connect(this.master).connect(this.ctx.destination);
    this.applyVolume();
    const len = this.ctx.sampleRate;
    this.noise = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = this.noise.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    return this.ctx;
  }

  private applyVolume() {
    if (!this.ctx) return;
    this.master.gain.setTargetAtTime(this.volume, this.ctx.currentTime, 0.05);
  }

  setVolume(v: number) { this.volume = Math.max(0, Math.min(1, v)); this.applyVolume(); }

  /** Speech always wins: duck SFX while Monkey talks (fast attack, slow release). */
  duck(on: boolean, speaking = on) {
    this.speaking = speaking;
    if (on === this.ducked) return;
    this.ducked = on;
    if (!this.ctx) return;
    this.bus.gain.setTargetAtTime(on ? db(-10) : 1, this.ctx.currentTime, on ? 0.05 : 0.3);
  }

  play(cue: Cue, intensity = 1) {
    const vocal = cue.startsWith("vocal/");
    const allowed = ALLOWED[this.juice];
    if (allowed !== "all" && !allowed.has(cue)) return;
    if (vocal && this.speaking) return;                // his grunts never talk over his own voice
    const now = performance.now();
    if (now - (this.last.get(cue) ?? -1e9) < (COOLDOWN_MS[cue] ?? 120)) return;
    if (this.live >= 8) return;                       // polyphony cap
    const ctx = this.ensure();
    if (!ctx || ctx.state !== "running") return;
    const buf = this.pick(cue);
    if (!buf && !(cue in LEVEL_DB)) return;            // no recording and no synth recipe for this cue
    this.last.set(cue, now);
    const out = ctx.createGain();
    const calm = this.juice === "calm" ? 0.5 : 1;
    out.connect(this.bus);
    this.live++;
    let end: number;
    if (buf) {
      out.gain.value = db((SAMPLE_DB[cue] ?? 0) + (Math.random() * 4 - 2)) * calm * intensity;
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.playbackRate.value = vocal ? jitter(0.03) : jitter(0.05);   // ±5% pitch (vocals ±3%)
      src.connect(out);
      src.start();
      end = buf.duration / src.playbackRate.value;
    } else {
      out.gain.value = db(LEVEL_DB[cue] + (Math.random() * 4 - 2)) * calm * intensity;
      end = this.synth(ctx, cue as SynthCue, out, jitter(0.05));
    }
    setTimeout(() => { this.live--; out.disconnect(); }, end * 1000 + 100);
  }

  // ------------------------------------------------------------ synth recipes (returns duration in s)
  private tone(ctx: AudioContext, out: AudioNode, type: OscillatorType, f0: number, f1: number, dur: number,
               attack = 0.005, at = 0) {
    const t = ctx.currentTime + at;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(f0, t);
    o.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(1, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(out);
    o.start(t);
    o.stop(t + dur + 0.02);
  }

  private noiseBurst(ctx: AudioContext, out: AudioNode, dur: number, f0: number, f1: number, q = 1, at = 0,
                     peak = 1) {
    if (!this.noise) return;
    const t = ctx.currentTime + at;
    const src = ctx.createBufferSource();
    src.buffer = this.noise;
    src.loop = true;
    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.Q.value = q;
    bp.frequency.setValueAtTime(f0, t);
    bp.frequency.exponentialRampToValueAtTime(Math.max(40, f1), t + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + dur * 0.3);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(bp).connect(g).connect(out);
    src.start(t, Math.random());
    src.stop(t + dur + 0.02);
  }

  private synth(ctx: AudioContext, cue: SynthCue, out: AudioNode, p: number): number {
    switch (cue) {
      case "pop": this.tone(ctx, out, "sine", 520 * p, 1250 * p, 0.07); return 0.08;
      case "zPop": this.tone(ctx, out, "sine", 900 * p, 1500 * p, 0.05); return 0.06;
      case "tick": this.tone(ctx, out, "triangle", 1800 * p, 1700 * p, 0.03); return 0.04;
      case "sweat": this.tone(ctx, out, "sine", 1600 * p, 700 * p, 0.09); return 0.1;
      case "boing": {
        this.tone(ctx, out, "sine", 180 * p, 520 * p, 0.12);
        this.tone(ctx, out, "sine", 520 * p, 260 * p, 0.25, 0.005, 0.12);
        return 0.4;
      }
      case "startle": {   // slide whistle up + bright ping
        this.tone(ctx, out, "triangle", 380 * p, 1600 * p, 0.22, 0.01);
        this.tone(ctx, out, "square", 1900 * p, 1850 * p, 0.12, 0.003, 0.2);
        return 0.35;
      }
      case "sparkle": {
        const notes = [1318, 1568, 1976, 2637];
        notes.forEach((f, i) => this.tone(ctx, out, "triangle", f * p, f * p * 1.01, 0.18, 0.003, i * 0.07));
        return 0.5;
      }
      case "whoosh": this.noiseBurst(ctx, out, 0.25, 600 * p, 2400 * p, 0.8); return 0.3;
      case "thump": {
        this.tone(ctx, out, "sine", 120 * p, 45, 0.18, 0.003);
        this.noiseBurst(ctx, out, 0.08, 300, 120, 0.7, 0, 0.5);
        return 0.22;
      }
      case "yawn": {      // soft rising-falling breathy vowel
        this.noiseBurst(ctx, out, 1.4, 500 * p, 260 * p, 3, 0, 0.8);
        this.tone(ctx, out, "sine", 210 * p, 140 * p, 1.2, 0.3);
        return 1.5;
      }
      case "snore": {     // rumbly inhale, whistly exhale
        this.noiseBurst(ctx, out, 1.1, 140 * p, 220 * p, 2.5, 0, 0.9);
        this.tone(ctx, out, "sawtooth", 70 * p, 60 * p, 1.0, 0.25);
        this.tone(ctx, out, "sine", 1100 * p, 1500 * p, 0.6, 0.15, 1.2);
        return 1.9;
      }
    }
    return 0.1;
  }
}

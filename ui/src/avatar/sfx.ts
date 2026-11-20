// Monkey's little sound engine (Web Audio): buses, ducking under his voice, variation, cooldowns.
// Recorded kit (ui/public/sfx) first; a few tiny synth recipes are the fallback when a cue has no takes.
// Rules from docs/ANIMATION-UI-DIRECTION.md: frequent sounds are short and quiet, every play is slightly
// different (pitch ±5%, volume ±2 dB), each cue has a cooldown, and SFX duck ~10 dB while Monkey talks.
// Mix safety (docs/audio/SFX_AUDIT.md): takes are leveled to their cue on decode, interface sounds choke each
// other (one UI sound at a time), a soft limiter on the master keeps stacked beats from clipping, and loops are
// explicit handles that always stop.

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
  reward: 3000, confetti: 1500, ui_click: 40, check: 60, ui_open: 120, ui_close: 120, ui_error: 400, notify: 2000,
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
// UI trims come from the measured median short-term loudness (tools/sfx/inventory.py) so the interface has a
// hierarchy: click (-15) < open/close (-15) < confirm (-14) < error (-13) < notification (-11), all under speech.
const SAMPLE_DB: Record<string, number> = { snore: -6, zPop: -4, tick: -6, jungle_loop: -8, ui_click: -6, footstep: -4,
  ui_open: -4.5, ui_close: -8, check: -4.5, ui_error: -5, notify: 2.5 };
/** Interface sounds and their rank. One UI sound at a time: a new one cuts a ringing one of equal or lower rank
 *  short (the click that opened Settings gives way to "open"); a lower one waits its turn (a dialog opening right
 *  after the "needs you" chime doesn't cut the chime off, it's simply skipped). */
const UI_RANK: Record<string, number> = { ui_click: 0, tick: 0, ui_open: 1, ui_close: 1, check: 2, ui_error: 3, notify: 4 };
export const UI_GROUP = new Set(Object.keys(UI_RANK));
/** Decoded first (the first click must not be silent); everything else loads a moment later; loops on demand. */
const HOT = ["ui_click", "pop", "check", "ui_open", "ui_close", "ui_error", "notify"];
const MAX_VOICES = 8;
export const LIMITER_MAKEUP_DB = 2.91;
const LEVEL_CLAMP_DB = 6;

/** Unbiased shuffle (Fisher–Yates). `sort(() => Math.random() - 0.5)` favors keeping items near their start. */
export function shuffle<T>(xs: T[], rnd: () => number = Math.random): T[] {
  const a = [...xs];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/** Loudest 10 ms RMS of a buffer in dB (what a short sound "hits" at). */
export function peakRmsDb(buf: { numberOfChannels: number; length: number; sampleRate: number; getChannelData(c: number): Float32Array }): number {
  const w = Math.max(1, Math.round(buf.sampleRate * 0.01));
  const n = buf.length;
  const sq = new Float64Array(n);
  for (let c = 0; c < buf.numberOfChannels; c++) {
    const d = buf.getChannelData(c);
    for (let i = 0; i < n; i++) sq[i] += (d[i] * d[i]) / buf.numberOfChannels;
  }
  let sum = 0, best = 0;
  for (let i = 0; i < n; i++) {
    sum += sq[i];
    if (i >= w) sum -= sq[i - w];
    if (sum > best) best = sum;
  }
  return 10 * Math.log10(Math.max(best / Math.min(w, n), 1e-12));
}

/** A running loop (ambience or a state bed). stop() fades it out; calling it twice is harmless. */
export interface LoopHandle { cue: string; stop(fadeS?: number): void; readonly playing: boolean }

const db = (v: number) => Math.pow(10, v / 20);
const jitter = (amt: number) => 1 + (Math.random() * 2 - 1) * amt;

export class Sfx {
  private ctx: AudioContext | null = null;
  private master!: GainNode;
  private bus!: GainNode;
  private last = new Map<Cue, number>();
  private noise: AudioBuffer | null = null;
  private live = 0;
  private voices = new Set<{ src: AudioScheduledSourceNode; out: GainNode; cue: string }>();
  private uiVoice: { src: AudioScheduledSourceNode; out: GainNode; rank: number } | null = null;
  private previewSrc: AudioBufferSourceNode | null = null;
  private loops = new Map<string, LoopHandle>();
  private trim = new Map<string, number>();            // take -> dB that levels it to its cue's median
  private makeContext: () => AudioContext;
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
  private fetcher: (src: string) => Promise<ArrayBuffer>;

  /** Plug in the recorded kit (called once the bridge is ready). */
  async attach(src: SoundSource) {
    this.source = src;
    const add = (m: Record<string, string[]>, prefix = "") => {
      for (const [cue, files] of Object.entries(m)) this.kit.set(cue, [...(this.kit.get(cue) ?? []), ...files.map((f) => prefix + f)]);
    };
    try { add(await src.bundled()); } catch { /* no bundled kit */ }
    try { add(await src.user(), "user:"); } catch { /* none made yet */ }
    await this.prefetch();
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

  /** Sound Lab: play one exact take, ignoring juice level and cooldowns. A new preview stops the previous one, so
   *  auditioning takes quickly never stacks them (and the Sound Lab buttons don't click, see main.ts). */
  async preview(src: string) {
    const ctx = this.ensure();
    if (!ctx) return;
    await ctx.resume().catch(() => {});
    const buf = await this.load(src);
    if (!buf) return;
    try { this.previewSrc?.stop(); } catch { /* already ended */ }
    const s = ctx.createBufferSource();
    s.buffer = buf;
    const g = ctx.createGain();
    g.gain.value = db(this.trim.get(src) ?? 0);       // heard as it plays in the app (leveled), not raw
    s.connect(g).connect(this.master);
    s.start();
    this.previewSrc = s;
    s.onended = () => { if (this.previewSrc === s) this.previewSrc = null; g.disconnect(); };
  }

  takeOf(src: string) { return this.takeName(src); }

  private takeName(src: string) { return src.split("/").pop()!.replace(/\.(ogg|wav)$/, ""); }

  /** Hot cues decode right away; the rest a moment later in small batches; loops only when first played. */
  private async prefetch() {
    const ctx = this.ensure();
    if (!ctx) return;
    const isLoop = (c: string) => c.endsWith("_loop");
    await Promise.all(HOT.flatMap((c) => this.kit.get(c) ?? []).map((f) => this.load(f)));
    const rest = [...this.kit.entries()].filter(([c]) => !HOT.includes(c) && !isLoop(c)).flatMap(([, fs]) => fs);
    this.warming = (async () => {                         // in the background: attach() doesn't wait for these
      for (let i = 0; i < rest.length; i += 6) await Promise.all(rest.slice(i, i + 6).map((f) => this.load(f)));
    })();
  }
  /** Resolves once every non-loop take is decoded (tests, the Sound Lab). */
  warming: Promise<void> = Promise.resolve();

  /** dB that brings each take of a cue to the cue's median loudness (clamped), so no take jumps out. */
  private level(cue: string) {
    const files = this.kit.get(cue) ?? [];
    const loud = files.map((f) => {
      const b = this.buffers.get(f);
      return b && typeof b !== "string" ? [f, peakRmsDb(b)] as const : null;
    }).filter((x): x is readonly [string, number] => x !== null);
    if (!loud.length) return;
    const sorted = loud.map(([, v]) => v).sort((a, b) => a - b);
    const med = sorted[Math.floor((sorted.length - 1) / 2)];
    for (const [f, v] of loud) this.trim.set(f, Math.max(-LEVEL_CLAMP_DB, Math.min(LEVEL_CLAMP_DB, med - v)));
  }

  private cueOf(src: string): string | undefined {
    for (const [cue, files] of this.kit) if (files.includes(src)) return cue;
    return undefined;
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
      else data = await this.fetcher(src);
      if (!data) throw new Error("missing");
      const buf = await ctx.decodeAudioData(data);
      this.buffers.set(src, buf);
      const cue = this.cueOf(src);
      if (cue) this.level(cue);
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
      bag = shuffle(ready);
      if (bag.length > 1 && bag[0] === this.lastTake.get(cue)) bag.push(bag.shift()!);
    }
    const f = bag.shift()!;
    this.bags.set(cue, bag);
    this.lastTake.set(cue, f);
    this.lastPicked = f;
    return this.buffers.get(f) as AudioBuffer;
  }
  private lastPicked = "";

  has(cue: string) { return this.kit.has(cue); }

  private original = new Map<string, string[]>();
  /** Sound Lab review: play a cue from candidate takes instead of the shipped ones (null = back to the shipped
   *  takes). The shipped files are kept, so switching back is instant and nothing is lost. */
  async useVariant(cue: string, files: string[] | null) {
    if (!this.original.has(cue)) this.original.set(cue, this.kit.get(cue) ?? []);
    const next = files ?? this.original.get(cue)!;
    this.kit.set(cue, next);
    this.bags.delete(cue);
    this.lastTake.delete(cue);
    await Promise.all(next.map((f) => this.load(f)));
    this.level(cue);
  }

  constructor(opts: { makeContext?: () => AudioContext; fetch?: (src: string) => Promise<ArrayBuffer> } = {}) {
    this.makeContext = opts.makeContext ?? (() => new AudioContext());
    this.fetcher = opts.fetch ?? (async (src) => (await fetch(src)).arrayBuffer());
    if (typeof window === "undefined") return;
    const unlock = () => { this.ensure(); this.ctx?.resume().catch(() => {}); };
    window.addEventListener("pointerdown", unlock, { capture: true });
    window.addEventListener("keydown", unlock, { capture: true });
  }

  private ensure(): AudioContext | null {
    if (this.ctx) return this.ctx;
    try {
      this.ctx = this.makeContext();
    } catch {
      return null;
    }
    this.master = this.ctx.createGain();
    this.bus = this.ctx.createGain();
    // Safety limiter: transparent for one sound, catches stacked beats (a chest-beat run, wake-up) before they clip.
    const lim = this.ctx.createDynamicsCompressor();
    lim.threshold.value = -6; lim.knee.value = 3; lim.ratio.value = 20; lim.attack.value = 0.002; lim.release.value = 0.12;
    // The Web Audio compressor adds automatic makeup gain (+2.91 dB in Chromium with these settings, measured with
    // an OfflineAudioContext). Take it back out so a single sound plays at exactly the level it had before.
    const makeup = this.ctx.createGain();
    makeup.gain.value = db(-LIMITER_MAKEUP_DB);
    this.bus.connect(this.master).connect(lim).connect(makeup).connect(this.ctx.destination);
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
    const ui = UI_GROUP.has(cue);
    if (this.live >= MAX_VOICES && !ui) return;       // polyphony cap (an interface answer always gets through)
    const ctx = this.ensure();
    if (!ctx || ctx.state !== "running") return;
    if (ui && this.uiVoice && this.uiVoice.rank > UI_RANK[cue]) return;   // a more important UI sound is ringing
    const buf = this.pick(cue);
    if (!buf && !(cue in LEVEL_DB)) return;            // no recording and no synth recipe for this cue
    this.last.set(cue, now);
    if (ui) this.choke(ctx);
    const out = ctx.createGain();
    const calm = this.juice === "calm" ? 0.5 : 1;
    out.connect(this.bus);
    this.live++;
    let end: number;
    let node: AudioScheduledSourceNode | null = null;
    if (buf) {
      const take = this.trim.get(this.lastPicked) ?? 0;
      out.gain.value = db((SAMPLE_DB[cue] ?? 0) + take + (Math.random() * 4 - 2)) * calm * intensity;
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.playbackRate.value = vocal ? jitter(0.03) : jitter(0.05);   // ±5% pitch (vocals ±3%)
      src.connect(out);
      src.start();
      node = src;
      end = buf.duration / src.playbackRate.value;
    } else {
      out.gain.value = db(LEVEL_DB[cue] + (Math.random() * 4 - 2)) * calm * intensity;
      end = this.synth(ctx, cue as SynthCue, out, jitter(0.05));
    }
    const voice = node ? { src: node, out, cue } : null;
    if (voice) this.voices.add(voice);
    if (ui && node) this.uiVoice = { src: node, out, rank: UI_RANK[cue] };
    setTimeout(() => {
      this.live--; out.disconnect();
      if (voice) this.voices.delete(voice);
      if (this.uiVoice?.out === out) this.uiVoice = null;
    }, end * 1000 + 100);
  }

  /** Fade the interface sound that's still ringing (12 ms, no click) so the new one starts clean. */
  private choke(ctx: AudioContext) {
    const v = this.uiVoice;
    if (!v) return;
    this.uiVoice = null;
    const t = ctx.currentTime;
    v.out.gain.cancelScheduledValues(t);
    v.out.gain.setValueAtTime(v.out.gain.value, t);
    v.out.gain.linearRampToValueAtTime(0, t + 0.012);
    try { v.src.stop(t + 0.015); } catch { /* already stopped */ }
  }

  /** Start a looping bed (only when a feature asks for one; nothing loops by default). Deduplicated per cue:
   *  asking again returns the running handle. Fades in, and stop() fades out and frees it. */
  async loop(cue: string, opts: { fadeS?: number; gainDb?: number } = {}): Promise<LoopHandle | null> {
    const running = this.loops.get(cue);
    if (running?.playing) return running;
    const ctx = this.ensure();
    if (!ctx) return null;
    const files = (this.kit.get(cue) ?? []).filter((f) => !this.rejects.has(this.takeName(f)));
    if (!files.length) return null;
    const buf = await this.load(files[0]);
    if (!buf) return null;
    const again = this.loops.get(cue);               // another call may have started it while this one loaded
    if (again?.playing) return again;
    const fade = opts.fadeS ?? 0.6;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.loop = true;
    const g = ctx.createGain();
    const t = ctx.currentTime;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(db((SAMPLE_DB[cue] ?? 0) + (opts.gainDb ?? 0)), t + fade);
    src.connect(g).connect(this.bus);
    src.start();
    let playing = true;
    const handle: LoopHandle = {
      cue,
      get playing() { return playing; },
      stop: (fadeS = 0.4) => {
        if (!playing) return;
        playing = false;
        const t0 = ctx.currentTime;
        g.gain.cancelScheduledValues(t0);
        g.gain.setValueAtTime(g.gain.value, t0);
        g.gain.linearRampToValueAtTime(0, t0 + fadeS);
        try { src.stop(t0 + fadeS + 0.02); } catch { /* stopped */ }
        setTimeout(() => g.disconnect(), (fadeS + 0.1) * 1000);
        if (this.loops.get(cue) === handle) this.loops.delete(cue);
      },
    };
    this.loops.set(cue, handle);
    return handle;
  }

  /** Stop everything now (window hidden, app quitting, barge-in on the whole scene). Loops fade very briefly. */
  stopAll() {
    for (const h of [...this.loops.values()]) h.stop(0.05);
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    for (const v of this.voices) {
      v.out.gain.cancelScheduledValues(t);
      v.out.gain.setValueAtTime(v.out.gain.value, t);
      v.out.gain.linearRampToValueAtTime(0, t + 0.02);
      try { v.src.stop(t + 0.025); } catch { /* ended */ }
    }
    this.voices.clear();
    this.uiVoice = null;
  }

  /** For tests and the Sound Lab: what's playing. */
  get activeLoops() { return [...this.loops.keys()]; }
  get liveVoices() { return this.live; }

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

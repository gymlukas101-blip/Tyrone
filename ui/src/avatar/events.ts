// Frame-timed sound + effect beats for the Blender clips (30 fps), fired as the clip's playhead crosses them.
// Kept beside the clips (tools/blender/clips_tier1.py) so a re-timed clip only needs its numbers changed here.
// Rule of thumb from the DK study: sound on contact frames, never on wind-ups; one accent per beat.

export type Where = "head" | "mouth" | "chest" | "feet" | "handR" | "handL";
export interface Beat {
  f: number;                 // frame (30 fps) in the clip
  sfx?: string;              // sound cue (ui/public/sfx/index.json, or "vocal/..." made on this PC)
  vol?: number;              // 0..1 intensity
  vfx?: "puff" | "bang" | "bulb" | "sparkle" | "star" | "question" | "note";
  at?: Where;
  size?: number;
}

export const FPS = 30;

const every = (from: number, to: number, step: number, b: Omit<Beat, "f">): Beat[] =>
  Array.from({ length: Math.floor((to - from) / step) + 1 }, (_, i) => ({ f: from + i * step, ...b }));

export const EVENTS: Record<string, Beat[]> = {
  idle_knuckle_crack: [{ f: 28, sfx: "crack" }, { f: 40, sfx: "crack", vol: 1.2 }],
  idle_mini_chestbeat: [
    ...[12, 18, 24, 30].map((f, i) => ({ f, sfx: "chest_thump", vol: 0.8 + i * 0.08 } as Beat)),
    { f: 30, vfx: "puff", at: "chest", size: 0.14 },
    { f: 36, sfx: "vocal/hoohoo", vol: 0.8 },
  ],
  idle_scratch_head: [...every(22, 58, 12, { sfx: "scratch", vol: 0.6 }), { f: 64, sfx: "vocal/hmm", vol: 0.6 }],
  idle_scratch_belly: [...every(20, 50, 12, { sfx: "rustle", vol: 0.5 }), { f: 60, sfx: "vocal/sigh", vol: 0.6 }],
  idle_shake_off: [{ f: 8, sfx: "brrr" }],
  idle_stretch_shoulders: [{ f: 16, sfx: "vocal/hngh", vol: 0.6 }, { f: 80, sfx: "vocal/sigh", vol: 0.6 }],
  idle_impatient_tap: [...every(20, 80, 10, { sfx: "tap", vol: 0.5 }), { f: 92, sfx: "vocal/sigh", vol: 0.7 }],
  idle_flex_check: [{ f: 18, sfx: "vocal/hngh" }, { f: 18, vfx: "sparkle", at: "handR", size: 0.1 }],
  idle_cross_eyes: [{ f: 6, sfx: "boing", vol: 0.6 }],
  sit_down: [{ f: 10, sfx: "whoosh", vol: 0.5 }, { f: 24, sfx: "thump" }, { f: 24, vfx: "puff", at: "feet", size: 0.18 }],
  lie_down: [{ f: 38, sfx: "flop" }, { f: 40, vfx: "puff", at: "feet", size: 0.16 }],
  wake_startle: [
    { f: 0, sfx: "startle" }, { f: 0, sfx: "vocal/snort_wake" }, { f: 0, vfx: "bang", at: "head", size: 0.26 },
    { f: 6, sfx: "slide_up", vol: 0.7 }, { f: 16, sfx: "thump" }, { f: 16, vfx: "puff", at: "feet", size: 0.16 },
    { f: 28, sfx: "scratch", vol: 0.5 },
  ],
  wake_groggy: [{ f: 36, sfx: "rustle", vol: 0.5 }, { f: 72, sfx: "vocal/yawn", vol: 0.7 }],
  attn_perk: [{ f: 8, sfx: "ear_perk", vol: 0.6 }],
  think_eureka: [{ f: 9, sfx: "ding" }, { f: 9, vfx: "bulb", at: "head", size: 0.2 }],
};

/** Beats crossed when the playhead moved from prev to now (seconds); handles loop wrap-around. */
export function crossed(clip: string, prev: number, now: number, duration: number): Beat[] {
  const beats = EVENTS[clip];
  if (!beats || now === prev) return [];
  const fp = prev * FPS, fn = now * FPS, total = duration * FPS;
  if (fn >= fp) return beats.filter((b) => b.f > fp && b.f <= fn);
  return beats.filter((b) => b.f > fp && b.f <= total || b.f <= fn);     // wrapped past the loop end
}

// Performance director: picks small, intentional facial acting from what Monkey is doing and saying.
//
// Principles (from studying expressive game characters, adapted to a desktop assistant, never copied):
//   - Acting comes from intent (state, the sentence he's about to say), never from loudness alone.
//   - Each reaction has phases: a short anticipation, the hit, a hold you can read, then a settle back.
//   - Restraint: at most one reaction per sentence, a cooldown between them, and long stretches of calm.
//   - Asymmetry reads as thought: one brow up, a half smirk; symmetric shapes are for big, honest emotion.
//   - Brows carry most of the thought. On models with the V2 per-side brow morphs (browInnerUp/OuterUp/Down _L/_R,
//     browSqueeze) the cues use them for real asymmetry; older models ignore unknown morphs and keep the five
//     shared brow keys (browsUp, browsAngry, browsSad, browUp_L/R), which every cue still sets.
//   - States get a resting attitude: attentive while listening, a searching squint while thinking.
// No LLM call, nothing that delays speech: the text is already there when the sentence starts playing.

export type Cue = "curious" | "skeptical" | "excited" | "sympathetic" | "surprised" | "warm" | "proud" | "worried" | "focused";

interface Shape { [morph: string]: number }
interface Phase { t: number; shape: Shape }          // keyframes: seconds from cue start → target shape

const CUES: Record<Cue, { phases: Phase[]; dur: number }> = {
  // a lifted right brow and a tiny squint: "huh, tell me more"
  curious: { dur: 1.3, phases: [{ t: 0, shape: { browUp_R: 0.15 } },
    { t: 0.18, shape: { browUp_R: 0.6, browOuterUp_R: 0.5, browInnerUp_R: 0.2, browDown_L: 0.15, squint: 0.15 } },
    { t: 1.0, shape: { browUp_R: 0.5, browOuterUp_R: 0.4, squint: 0.1 } }] },
  // one brow up, the other slightly down, a half smirk, held: the readable "well, actually…"
  // (renders at app size showed 0.75 too subtle and a 0.3 squint reading as sleepy: bigger brow, lighter squint)
  skeptical: { dur: 1.6, phases: [{ t: 0, shape: { squint: 0.15, browDown_R: 0.2 } },
    { t: 0.15, shape: { browUp_L: 1, browOuterUp_L: 0.6, browDown_R: 0.55, browsAngry: 0.2, smirk_R: 0.5, squint: 0.12 } },
    { t: 1.2, shape: { browUp_L: 0.85, browOuterUp_L: 0.45, browDown_R: 0.4, smirk_R: 0.4, squint: 0.08 } }] },
  // anticipation dip, then a bright lift
  excited: { dur: 1.2, phases: [{ t: 0, shape: { squint: 0.25 } }, { t: 0.12, shape: { browsUp: 0.6, cheeksUp: 0.55, bigGrin: 0.5, wideEyes: 0.25 } },
    { t: 0.9, shape: { browsUp: 0.35, cheeksUp: 0.4, bigGrin: 0.35 } }] },
  sympathetic: { dur: 1.6, phases: [{ t: 0, shape: {} },
    { t: 0.25, shape: { browsSad: 0.55, browInnerUp_L: 0.5, browInnerUp_R: 0.5, browSqueeze: 0.3, sadEyes: 0.3, frown: 0.15 } },
    { t: 1.3, shape: { browsSad: 0.4, browInnerUp_L: 0.35, browInnerUp_R: 0.35, browSqueeze: 0.2, sadEyes: 0.2 } }] },
  // a quick squint before the eyes pop: the take reads bigger
  surprised: { dur: 1.1, phases: [{ t: 0, shape: { squint: 0.35, browDown_L: 0.25, browDown_R: 0.25 } },
    { t: 0.1, shape: { wideEyes: 0.85, browsUp: 0.9, browOuterUp_L: 0.5, browOuterUp_R: 0.5, mouthO: 0.35 } },
    { t: 0.75, shape: { wideEyes: 0.5, browsUp: 0.5, browOuterUp_L: 0.25, browOuterUp_R: 0.25 } }] },
  warm: { dur: 1.4, phases: [{ t: 0, shape: {} }, { t: 0.2, shape: { smile: 0.5, cheeksUp: 0.35, squint: 0.2 } },
    { t: 1.1, shape: { smile: 0.4, cheeksUp: 0.25 } }] },
  proud: { dur: 1.3, phases: [{ t: 0, shape: { squint: 0.2 } }, { t: 0.15, shape: { smirk_L: 0.55, browsUp: 0.3, chestPuff: 0.5 } },
    { t: 1.0, shape: { smirk_L: 0.4, chestPuff: 0.3 } }] },
  // inner brows up and pinched together, a small frown: "uh-oh, that's due soon" (deadlines, warnings)
  worried: { dur: 1.5, phases: [{ t: 0, shape: { browSqueeze: 0.2 } },
    { t: 0.2, shape: { browInnerUp_L: 0.75, browInnerUp_R: 0.7, browSqueeze: 0.5, browsSad: 0.35, frown: 0.12 } },
    { t: 1.2, shape: { browInnerUp_L: 0.5, browInnerUp_R: 0.45, browSqueeze: 0.35, browsSad: 0.2 } }] },
  // brows down and drawn in, a firm squint: "let's do this" (starting a task, focus mode)
  focused: { dur: 1.4, phases: [{ t: 0, shape: { browInnerUp_L: 0.15, browInnerUp_R: 0.15 } },
    { t: 0.14, shape: { browDown_L: 0.55, browDown_R: 0.55, browSqueeze: 0.55, browsAngry: 0.3, squint: 0.25, smirk_L: 0.2 } },
    { t: 1.1, shape: { browDown_L: 0.35, browDown_R: 0.35, browSqueeze: 0.35, browsAngry: 0.15, squint: 0.15 } }] },
};

/** Resting attitudes per voice state (subtle; reactions layer on top). */
const STATE_REST: Record<string, Shape> = {
  listening: { browsUp: 0.18, wideEyes: 0.12 },                    // attentive
  transcribing: { browsUp: 0.12 },
  thinking: { browUp_L: 0.3, browSqueeze: 0.25, browDown_R: 0.15, squint: 0.18 }, // searching, a little skeptical of the problem
};

const RULES: [RegExp, Cue][] = [
  [/\b(whoa|wow|no way|seriously\?|wait,? what|holy)\b/i, "surprised"],
  [/\b(sorry|unfortunately|sadly|ugh|that's rough|that sucks|bummer|i hear you)\b/i, "sympathetic"],
  [/\b(well,|actually|honestly|technically|supposedly|not so sure|hmm+|to be fair)\b/i, "skeptical"],
  [/\b(nice|awesome|let's go|great job|nailed it|amazing|yes!|woo)\b/i, "excited"],
  [/\b(uh[- ]oh|careful|watch out|overdue|due (today|tonight|tomorrow)|running late|deadline)\b/i, "worried"],
  [/\b(let's do this|let's get (to it|started)|focus|lock in|one thing at a time|game plan)\b/i, "focused"],
  [/\b(easy|done\.|got it covered|i got you|handled)\b/i, "proud"],
  [/\?\s*$/, "curious"],
  [/\b(glad|happy to|welcome|of course|anytime|love that)\b/i, "warm"],
];

export function cueFor(sentence: string): Cue | null {
  for (const [re, cue] of RULES) if (re.test(sentence)) return cue;
  return null;
}

function sample(phases: Phase[], t: number): Shape {
  let a = phases[0], b = phases[phases.length - 1];
  for (let i = 0; i < phases.length - 1; i++) {
    if (t >= phases[i].t && t <= phases[i + 1].t) { a = phases[i]; b = phases[i + 1]; break; }
  }
  if (t >= b.t) return b.shape;
  const k = b.t === a.t ? 1 : (t - a.t) / (b.t - a.t);
  const e = k * k * (3 - 2 * k);                                   // smoothstep between keys
  const out: Shape = {};
  for (const key of new Set([...Object.keys(a.shape), ...Object.keys(b.shape)])) {
    out[key] = (a.shape[key] ?? 0) + ((b.shape[key] ?? 0) - (a.shape[key] ?? 0)) * e;
  }
  return out;
}

export class PerformanceDirector {
  state = "idle";
  cue: Cue | null = null;
  private cueT = 0;
  private cooldownUntil = 0;
  private now = 0;
  cooldown = 2.4;            // seconds between reactions: calm is part of the performance

  setState(s: string) {
    if (s !== this.state && s !== "speaking") this.cue = null;      // a new state resets reactions (no stale looks)
    this.state = s;
  }

  /** A sentence is about to be spoken: maybe react to it (at most one reaction per sentence, with a cooldown). */
  sentence(text: string): Cue | null {
    if (this.now < this.cooldownUntil) return null;
    const c = cueFor(text);
    if (c) this.play(c);
    return c;
  }

  play(c: Cue) {
    this.cue = c;
    this.cueT = 0;
    this.cooldownUntil = this.now + CUES[c].dur + this.cooldown;
  }

  /** Advance and return acting targets for the face mixer. */
  update(dt: number): Shape {
    this.now += dt;
    const out: Shape = { ...(STATE_REST[this.state] ?? {}) };
    if (this.cue) {
      this.cueT += dt;
      const spec = CUES[this.cue];
      if (this.cueT >= spec.dur) this.cue = null;
      else for (const [k, v] of Object.entries(sample(spec.phases, this.cueT))) out[k] = Math.max(out[k] ?? 0, v);
    }
    return out;
  }
}

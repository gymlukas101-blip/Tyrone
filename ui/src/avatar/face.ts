// The face mixer: every facial morph is decided here, once per frame, from separate layers with clear ownership.
//
// Layers (highest wins where they compete):
//   override   yawn / sleep puff / blink: own their shapes outright while active
//   seal       a lip closure (viseme_PP / silence while talking): mouth corners and rounding give way
//   speech     visemes + jaw from the voice (attack fast, release a bit slower)
//   acting     brows, eyelids, cheeks, gaze-adjacent shapes and gentle mouth-corner moods, chosen by the
//              performance director (acting.ts) from what he's saying and doing
//   emote      the expression preset of a clip (happy, surprised, …)
//
// Rules that keep combinations appealing:
//   - Mouth-shape moods (smile, bigGrin, frown, grimace, smirk, mouthO) are scaled down while he talks, so a
//     smile tints speech instead of fighting it, and fully released during a lip seal.
//   - Vowel shapes and jaw don't double-count: the jaw is reduced when a viseme already opens the mouth.
//   - Brows and eyes are independent of the mouth (asymmetric brows survive speech).
//   - Brow beats: while talking, a loud onset (a stressed syllable) lifts the brows briefly, alternating both /
//     left outer / right inner so it reads as emphasis, not a tic (rate-limited). Uses the V2 per-side brow morphs
//     where the model has them, else the shared browsUp.
//   - Pupils (V2 E7 eyes: pupilDilate / pupilConstrict are one signed "net" size): moods set it (dilated when warm,
//     sad or interested, pinpoint in a shock, tight when angry or focused) and a slow natural flutter (hippus) keeps
//     the eyes alive when nothing else moves. Models without the morphs ignore them.
//   - Easing is time-based (time constants in seconds), so it looks the same at 15, 30, 60 or 144 fps.
// Everything is clamped to 0..1 and unknown morphs are ignored by the caller.

export const VISEMES = ["viseme_sil", "viseme_PP", "viseme_FF", "viseme_TH", "viseme_DD", "viseme_kk", "viseme_CH",
  "viseme_SS", "viseme_nn", "viseme_RR", "viseme_aa", "viseme_E", "viseme_I", "viseme_O", "viseme_U"] as const;
const OPENING: Record<string, number> = { viseme_aa: 1, viseme_O: 0.8, viseme_E: 0.6, viseme_I: 0.4, viseme_U: 0.45,
  viseme_CH: 0.35, viseme_DD: 0.3, viseme_kk: 0.35, viseme_nn: 0.2, viseme_RR: 0.35, viseme_SS: 0.15,
  viseme_TH: 0.2, viseme_FF: 0.1, viseme_PP: 0, viseme_sil: 0 };
export const MOUTH_MOODS = new Set(["smile", "bigGrin", "frown", "grimace", "smirk_L", "smirk_R", "mouthO", "tongueOut"]);
/** Mood shapes that open the lips (they must fully release for a closure); a plain smile/frown curve doesn't. */
export const LIP_PARTING = new Set(["bigGrin", "grimace", "mouthO", "tongueOut"]);

export interface FaceInput {
  talking: boolean;
  visemes: Record<string, number>;     // latest viseme weights from the voice (0..1)
  level: number;                       // voice loudness 0..1
  acting: Record<string, number>;      // performance director targets
  emote: Record<string, number>;       // clip expression preset targets
  override: Record<string, number>;    // yawn / blink / sleep: written as-is, on top
}

/** Exponential approach with a time constant: frame-rate independent. */
export function approach(now: number, target: number, dt: number, tauUp: number, tauDown = tauUp): number {
  const tau = target > now ? tauUp : tauDown;
  if (tau <= 0) return target;
  return now + (target - now) * (1 - Math.exp(-dt / tau));
}

const clamp = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);

export class FaceMixer {
  vis: Record<string, number> = {};
  jaw = 0;
  layer: Record<string, number> = {};          // acting + emote, eased
  out: Record<string, number> = {};            // final weights written this frame
  /** Speech timing (s). Attack fast so consonants land, release slower so the mouth doesn't chatter. */
  tau = { visUp: 0.035, visDown: 0.07, jawUp: 0.045, jawDown: 0.09, mood: 0.16, moodTalk: 0.12 };
  /** Brow beats: slow loudness follower, current pulse (0..1), time since the last beat, beat counter. */
  beat = { slow: 0, pulse: 0, since: 9, n: 0, minGap: 0.7, onset: 0.16, decay: 0.32 };
  /** Pupil flutter: amplitude (net pupil size) and running time. */
  hippus = { amp: 0.07, t: 0 };

  update(i: FaceInput, dt: number): Record<string, number> {
    const out: Record<string, number> = {};
    // ---- speech layer
    let seal = 0;
    let opening = 0;
    for (const v of VISEMES) {
      const target = i.talking ? clamp(i.visemes[v] ?? 0) : 0;
      const n = approach(this.vis[v] ?? 0, target, dt, this.tau.visUp, this.tau.visDown);
      this.vis[v] = n < 0.001 ? 0 : n;
      out[v] = this.vis[v];
      opening = Math.max(opening, this.vis[v] * OPENING[v]);
    }
    if (i.talking) seal = Math.max(this.vis.viseme_PP ?? 0, (this.vis.viseme_sil ?? 0) * 0.7);
    // Jaw from loudness, minus what the vowel shape already opens (no double-counting), closed by a seal.
    const jawTarget = i.talking ? clamp(Math.min(0.6, i.level * 0.8) * (1 - 0.45 * opening) * (1 - seal)) : 0;
    this.jaw = approach(this.jaw, jawTarget, dt, this.tau.jawUp, this.tau.jawDown);
    out.jawOpen = this.jaw;
    // ---- acting + emote layers (mouth moods give way to speech)
    const speechAmt = clamp(Math.max(opening, this.jaw / 0.6));
    const keys = new Set([...Object.keys(i.acting), ...Object.keys(i.emote), ...Object.keys(this.layer)]);
    for (const k of keys) {
      let target = Math.max(i.acting[k] ?? 0, i.emote[k] ?? 0);
      if (MOUTH_MOODS.has(k)) {
        if (i.talking) target *= 1 - 0.55 * speechAmt;      // a smile tints the words, it doesn't fight them
        // Lips must meet on M/B/P: shapes that part the lips let go; a closed-mouth smile curve may stay (warmth).
        target *= LIP_PARTING.has(k) ? 1 - seal : 1 - 0.6 * seal;
      }
      const n = approach(this.layer[k] ?? 0, clamp(target), dt, i.talking ? this.tau.moodTalk : this.tau.mood);
      if (n < 0.002 && !target) delete this.layer[k];
      else this.layer[k] = n;
      if (k in this.layer) out[k] = Math.max(out[k] ?? 0, this.layer[k]);
    }
    // ---- brow beats (emphasis on stressed syllables while talking)
    const b = this.beat;
    b.since += dt;
    b.slow = approach(b.slow, i.talking ? i.level : 0, dt, 0.35);
    if (i.talking && i.level - b.slow > b.onset && b.since > b.minGap) { b.pulse = 1; b.since = 0; b.n++; }
    b.pulse = b.pulse * Math.exp(-dt / b.decay);
    if (!i.talking) b.pulse = 0;
    if (b.pulse > 0.01) {
      const p = b.pulse;
      const add = (k: string, v: number) => { out[k] = clamp(Math.max(out[k] ?? 0, v)); };
      const kind = (b.n - 1) % 3;                          // both, then left outer, then right inner
      add("browsUp", p * (kind === 0 ? 0.22 : 0.1));
      if (kind === 0) { add("browInnerUp_L", p * 0.25); add("browInnerUp_R", p * 0.25); }
      else if (kind === 1) add("browOuterUp_L", p * 0.35);
      else add("browInnerUp_R", p * 0.35);
    }
    // ---- pupils: one signed size (dilate − constrict) plus a slow, irregular flutter, split back into the two keys
    this.hippus.t += dt;
    const ht = this.hippus.t;
    const flutter = this.hippus.amp * (0.6 * Math.sin(ht * 1.7) + 0.4 * Math.sin(ht * 1.03 + 1.3));
    const net = Math.max(-1, Math.min(1, (out.pupilDilate ?? 0) - (out.pupilConstrict ?? 0) + flutter));
    out.pupilDilate = clamp(net);
    out.pupilConstrict = clamp(-net);
    // mouthO from a mood and the O viseme shouldn't stack past fully round
    if (out.mouthO !== undefined) out.mouthO = clamp(out.mouthO * (1 - (this.vis.viseme_O ?? 0) * 0.5));
    // ---- overrides (yawn, blink, sleep) win outright
    for (const [k, v] of Object.entries(i.override)) out[k] = k === "jawOpen" ? Math.max(out[k] ?? 0, v) : clamp(v);
    this.out = out;
    return out;
  }

  /** A stop, barge-in or new utterance: no stale mouth shape may carry over. */
  resetSpeech() {
    this.vis = {};
    this.jaw = 0;
    this.beat.pulse = 0;
  }
}

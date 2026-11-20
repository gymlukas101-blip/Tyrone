// One rule for what the avatar shows, in both windows (main and companion).
//
// Inputs: the voice state from the backend ("state" events) and the computer-task mood ("automation" events).
// Output: one AvatarState. Higher priority wins at once; a lower one waits until the current state has been on screen
// for its minimum dwell, so quick blips (a 50 ms "thinking" between two sentences) never flicker the body.
//
// Priority (high → low):
//   speaking            his mouth must never freeze mid-sentence
//   needs you           a task is waiting on you (shown as "listening": ears up, looking at you)
//   listening / transcribing   you're talking to him
//   thinking            a reply is being prepared, or a task is working / verifying
//   idle
// Celebrate / shrug / wave for task results are one-shot emotes on top, not states (main.ts moodEmote).
import type { AvatarState } from "../avatar-types";

export type Mood = "idle" | "working" | "waiting" | "help" | "thinking" | "celebrate" | "blocked" | "sad" | "paused";

/** Minimum time a state stays on screen before a lower-priority one may replace it (ms). */
export const MIN_DWELL: Record<AvatarState, number> = { speaking: 0, listening: 350, transcribing: 300, thinking: 450, idle: 0 };

export function desired(voice: AvatarState, mood: Mood): { state: AvatarState; rank: number; why: string } {
  if (voice === "speaking") return { state: "speaking", rank: 5, why: "speaking" };
  if (mood === "help") return { state: "listening", rank: 4, why: "task needs you" };
  if (voice === "listening" || voice === "transcribing") return { state: voice, rank: 3, why: "you're talking" };
  if (voice === "thinking") return { state: "thinking", rank: 2, why: "preparing a reply" };
  if (mood === "working" || mood === "thinking" || mood === "waiting") return { state: "thinking", rank: 2, why: "task working" };
  return { state: "idle", rank: 0, why: "idle" };
}

export class AvatarStateResolver {
  voice: AvatarState = "idle";
  mood: Mood = "idle";
  shown: AvatarState = "idle";
  private shownRank = 0;
  private since: number;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(private apply: (s: AvatarState, why: string) => void,
              private now: () => number = () => performance.now(),
              private schedule: (fn: () => void, ms: number) => ReturnType<typeof setTimeout> = (fn, ms) => setTimeout(fn, ms),
              private cancel: (t: ReturnType<typeof setTimeout>) => void = (t) => clearTimeout(t)) {
    this.since = this.now();
  }

  setVoice(s: AvatarState) { this.voice = s; this.update(); }
  setMood(m: string) { this.mood = (m || "idle") as Mood; this.update(); }

  /** Re-evaluate; tests call this after advancing a fake clock. */
  update() {
    const d = desired(this.voice, this.mood);
    if (d.state === this.shown) { this.shownRank = d.rank; return; }
    const held = this.now() - this.since;
    const wait = MIN_DWELL[this.shown] - held;
    if (d.rank >= this.shownRank || wait <= 0) {
      if (this.timer !== null) { this.cancel(this.timer); this.timer = null; }
      this.shown = d.state; this.shownRank = d.rank; this.since = this.now();
      this.apply(d.state, d.why);
      return;
    }
    if (this.timer === null) {
      this.timer = this.schedule(() => { this.timer = null; this.update(); }, Math.ceil(wait));
    }
  }
}

import { describe, expect, it } from "vitest";
import { AvatarStateResolver, desired, MIN_DWELL } from "../src/avatar/resolver";
import type { AvatarState } from "../src/avatar-types";

/** A resolver on a fake clock: run(steps) applies [ms, kind, value] and returns what was shown after each step. */
function rig() {
  let t = 0;
  const timers: { at: number; fn: () => void; id: number }[] = [];
  let ids = 0;
  const shown: AvatarState[] = [];
  const r = new AvatarStateResolver((s) => shown.push(s), () => t,
    (fn, ms) => { const id = ++ids; timers.push({ at: t + ms, fn, id }); return id as any; },
    (id) => { const i = timers.findIndex((x) => x.id === (id as any)); if (i >= 0) timers.splice(i, 1); });
  const advance = (ms: number) => {
    const end = t + ms;
    for (;;) {
      timers.sort((a, b) => a.at - b.at);
      const next = timers[0];
      if (!next || next.at > end) break;
      timers.shift(); t = next.at; next.fn();
    }
    t = end;
  };
  return { r, shown, advance, now: () => t };
}

describe("priority table", () => {
  const cases: [AvatarState, string, AvatarState][] = [
    ["speaking", "help", "speaking"],        // never freeze his mouth
    ["idle", "help", "listening"],           // a task needs you
    ["thinking", "help", "listening"],
    ["listening", "working", "listening"],   // D7: you talking beats a running task
    ["transcribing", "working", "transcribing"],
    ["thinking", "idle", "thinking"],
    ["idle", "working", "thinking"],
    ["idle", "waiting", "thinking"],
    ["idle", "celebrate", "idle"],           // results are emotes, not states
    ["idle", "blocked", "idle"],
    ["idle", "paused", "idle"],
    ["idle", "idle", "idle"],
  ];
  it.each(cases)("voice %s + task %s → %s", (voice, mood, want) => {
    expect(desired(voice, mood as any).state).toBe(want);
  });
});

describe("dwell", () => {
  it("higher priority switches at once", () => {
    const { r, shown } = rig();
    r.setVoice("thinking");
    r.setVoice("speaking");
    expect(shown).toEqual(["thinking", "speaking"]);
  });

  it("a short blip of a lower state never flickers", () => {
    const { r, shown, advance } = rig();
    r.setVoice("listening");
    advance(100);
    r.setVoice("idle");               // 100 ms in: listening must stay until its dwell is over
    expect(shown).toEqual(["listening"]);
    advance(100);
    r.setVoice("listening");          // came back before the dwell ended: no change at all
    advance(1000);
    expect(shown).toEqual(["listening"]);
  });

  it("the lower state shows once the dwell has passed", () => {
    const { r, shown, advance } = rig();
    r.setVoice("thinking");
    advance(50);
    r.setVoice("idle");
    advance(MIN_DWELL.thinking);
    expect(shown).toEqual(["thinking", "idle"]);
  });

  it("speaking ends the moment the audio ends", () => {
    const { r, shown } = rig();
    r.setVoice("speaking");
    r.setVoice("idle");
    expect(shown).toEqual(["speaking", "idle"]);
  });

  it("companion during a task: voice states still show (D7)", () => {
    const { r, shown, advance } = rig();
    r.setMood("working");
    expect(r.shown).toBe("thinking");
    r.setVoice("listening");
    r.setVoice("transcribing");
    advance(400);
    r.setVoice("speaking");
    r.setVoice("idle");
    expect(shown).toEqual(["thinking", "listening", "transcribing", "speaking", "thinking"]);
    r.setMood("help");
    expect(r.shown).toBe("listening");
  });
});

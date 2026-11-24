import { describe, expect, it } from "vitest";
import { type Clock, failureOf, gate, LOAD, loadMessage, nextStepIn } from "../src/loader";

/** A manual clock: timers only fire when the test advances time. */
function manualClock() {
  let t = 0, seq = 0;
  const timers = new Map<number, { at: number; fn: () => void }>();
  const clock: Clock = {
    now: () => t,
    set: (fn, ms) => { const id = ++seq; timers.set(id, { at: t + ms, fn }); return id; },
    clear: (id) => { timers.delete(id as number); },
  };
  /** Move time forward, firing due timers in order, and let promise callbacks run in between. */
  const advance = async (ms: number) => {
    const end = t + ms;
    for (;;) {
      await Promise.resolve(); await Promise.resolve();
      const due = [...timers.entries()].filter(([, x]) => x.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]);
      t = due[1].at;
      due[1].fn();
    }
    t = end;
    await Promise.resolve(); await Promise.resolve();
  };
  return { clock, advance, now: () => t };
}
/** A task the test resolves (or rejects) by hand. */
function deferred<T>() {
  let resolve!: (v: T) => void, reject!: (e: unknown) => void;
  const promise = new Promise<T>((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}

describe("loader timing", () => {
  it("a fast load never shows the loader (no flash) and returns at once", async () => {
    const { clock, advance, now } = manualClock();
    const task = deferred<string>();
    let shown = 0, doneAt = -1;
    const p = gate(task.promise, { show: () => shown++ }, {}, clock).then((r) => { doneAt = now(); return r; });
    await advance(100);
    task.resolve("data");
    await advance(1);
    const r = await p;
    expect(shown).toBe(0);
    expect(r).toMatchObject({ value: "data", shown: false, failed: false });
    expect(doneAt).toBe(100);
  });

  it("shows after ~150 ms, then stays at least ~400 ms (no flicker)", async () => {
    const { clock, advance, now } = manualClock();
    const task = deferred<number>();
    let shownAt = -1, doneAt = -1;
    const p = gate(task.promise, { show: () => { shownAt = now(); } }, {}, clock).then((r) => { doneAt = now(); return r; });
    await advance(149);
    expect(shownAt).toBe(-1);
    await advance(1);
    expect(shownAt).toBe(LOAD.delay);
    await advance(50);                       // data at 200 ms: the loader has been up 50 ms
    task.resolve(7);
    await advance(10);
    expect(doneAt).toBe(-1);                 // held for the minimum display time
    await advance(400);
    expect((await p).value).toBe(7);
    expect(doneAt).toBe(LOAD.delay + LOAD.minShow);
  });

  it("a long load hands over as soon as the data is in (the minimum is already met)", async () => {
    const { clock, advance, now } = manualClock();
    const task = deferred<number>();
    let doneAt = -1;
    const p = gate(task.promise, { show: () => {} }, {}, clock).then((r) => { doneAt = now(); return r; });
    await advance(1200);
    task.resolve(1);
    await advance(0);
    await p;
    expect(doneAt).toBe(1200);
  });

  it("changes its words after a few seconds while still loading, and stops once loaded", async () => {
    const { clock, advance } = manualClock();
    const task = deferred<number>();
    const steps: number[] = [];
    const p = gate(task.promise, { show: () => {}, message: (n) => steps.push(n) }, {}, clock);
    await advance(2999);
    expect(steps).toEqual([]);
    await advance(1);
    expect(steps).toEqual([1]);
    await advance(5000);
    expect(steps).toEqual([1, 2]);
    task.resolve(1);
    await advance(20000);
    await p;
    expect(steps).toEqual([1, 2]);           // no timers left running after it loaded
  });

  it("a failure resolves (never throws) after the minimum display time, marked failed", async () => {
    const { clock, advance, now } = manualClock();
    const task = deferred<number>();
    let doneAt = -1;
    const p = gate(task.promise, { show: () => {} }, {}, clock).then((r) => { doneAt = now(); return r; });
    await advance(160);
    task.reject(new Error("offline"));
    await advance(1000);
    const r = await p;
    expect(r.failed).toBe(true);
    expect(String((r.error as Error).message)).toBe("offline");
    expect(doneAt).toBe(LOAD.delay + LOAD.minShow);
  });

  it("delay 0 (Try again) shows the loader at once", async () => {
    const { clock, advance } = manualClock();
    const task = deferred<number>();
    let shown = 0;
    const p = gate(task.promise, { show: () => shown++ }, { delay: 0 }, clock);
    expect(shown).toBe(1);
    task.resolve(1);
    await advance(500);
    expect((await p).shown).toBe(true);
  });
});

describe("loader words and results", () => {
  it("the words change with time and the last one says you can keep chatting", () => {
    expect(loadMessage("your calendar", 0)).toBe("Loading your calendar…");
    expect(loadMessage("your calendar", 1)).toBe("Still fetching your calendar…");
    expect(loadMessage("x", 3)).toMatch(/keep chatting/);
    expect(loadMessage("x", 9)).toBe(loadMessage("x", 3));
    expect(loadMessage("x", 1, ["a", "b"])).toBe("b");
  });
  it("{ok:false} results are failures with their message; anything else is content", () => {
    expect(failureOf({ ok: false, error: "No Garmin" })).toBe("No Garmin");
    expect(failureOf({ ok: false })).toBe("Something went wrong.");
    expect(failureOf({ ok: true })).toBeNull();
    expect(failureOf(null)).toBeNull();
    expect(failureOf([1, 2])).toBeNull();
  });
  it("a redrawn loader keeps its place in the word sequence", () => {
    expect(nextStepIn(0, 1000)).toBe(LOAD.steps[0] - 1000);
    expect(nextStepIn(0, 4000)).toBe(LOAD.steps[1] - 4000);
    expect(nextStepIn(0, 99_000)).toBeNull();
  });
});

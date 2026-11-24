import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EASE, setJuice, T, type Level, type Step } from "../src/motion";
import {
  closeDialog, closePlan, contentPlan, finishClose, iconPlan, isClosing, isOpen, MT, noteTrigger, onCancel, onClose, openDialog,
  openPlan, originFor,
} from "../src/menu-motion";

const GPU = new Set(["opacity", "translate", "scale", "rotate"]);
const LEVELS: Level[] = ["full", "calm", "min"];
const props = (steps: Step[]) => new Set(steps.flatMap((s) => s.frames.flatMap((f) => Object.keys(f).filter((k) => k !== "offset" && k !== "easing"))));
const longest = (steps: Step[]) => Math.max(0, ...steps.map((s) => Number(s.opts.duration ?? 0) + Number(s.opts.delay ?? 0)));

/** A WAAPI animation stand-in the test finishes by hand. */
function fakeAnim() {
  let res!: () => void, rej!: (e: unknown) => void;
  const finished = new Promise<void>((a, b) => { res = a; rej = b; });
  finished.catch(() => {});
  const a = { finished, playState: "running", reversed: false,
    cancel: vi.fn(() => { a.playState = "idle"; rej(new Error("AbortError")); }),
    finish: vi.fn(() => { a.playState = "finished"; res(); }),
    reverse: vi.fn(() => { a.reversed = !a.reversed; }),
    done: () => { a.playState = "finished"; res(); } };
  return a;
}
type FakeAnim = ReturnType<typeof fakeAnim>;

/** A <dialog> stand-in: showModal/close are the "native" ones (installDialogMotion isn't used without a DOM). */
function fakeDialog() {
  const anims: FakeAnim[] = [];
  const d: any = {
    tagName: "DIALOG", open: false, isConnected: true, dataset: {} as Record<string, string>, style: {} as Record<string, string>,
    children: [], firstElementChild: null,
    showModal: vi.fn(() => { d.open = true; }),
    close: vi.fn(() => { if (!d.open) return; d.open = false; onClose({ target: d } as unknown as Event); }),
    contains: () => false, querySelector: () => null, getBoundingClientRect: () => ({ left: 100, top: 100, width: 400, height: 300 }),
    animate: vi.fn(() => { const a = fakeAnim(); anims.push(a); return a; }),
  };
  return { d, anims };
}
const cancelEvent = (d: unknown, cancelable = true) => {
  const e = { target: d, cancelable, defaultPrevented: false, preventDefault: vi.fn(() => { e.defaultPrevented = true; }) };
  return e;
};
const tick = async () => { for (let i = 0; i < 4; i++) await Promise.resolve(); };

beforeEach(() => { vi.useFakeTimers(); setJuice("full"); });
afterEach(() => { vi.useRealTimers(); setJuice("auto"); vi.unstubAllGlobals(); });

describe("menu plans", () => {
  it.each(LEVELS)("only animate GPU-friendly properties (%s)", (lv) => {
    const all = [openPlan(lv), openPlan(lv, "right"), openPlan(lv, "left"), openPlan(lv, "below"), closePlan(lv), closePlan(lv, "left"),
                 closePlan(lv, "below"), contentPlan(lv, 3), iconPlan(lv)];
    for (const p of all) for (const k of props(p)) expect(GPU.has(k), k).toBe(true);
  });
  it.each(LEVELS)("an opening menu is readable fast: opaque within T.read, contents never start invisible (%s)", (lv) => {
    for (const from of ["origin", "right", "left", "below"] as const) {
      const op = openPlan(lv, from).find((s) => s.frames.some((f) => "opacity" in f))!;
      expect(Number(op.opts.duration)).toBeLessThanOrEqual(T.read);
    }
    for (const s of contentPlan(lv, 9)) {
      expect(Number(s.frames[0].opacity)).toBeGreaterThan(0.3);
      expect(Number(s.opts.delay)).toBeLessThanOrEqual(MT.contentCap);
    }
  });
  it("closing is the opening reversed and faster, with no bounce", () => {
    for (const lv of LEVELS) {
      expect(longest(closePlan(lv))).toBeLessThan(longest(openPlan(lv)) + 1);
      expect(longest(closePlan(lv))).toBeLessThanOrEqual(MT.close);
      for (const s of closePlan(lv)) expect(s.opts.easing).toBe(EASE.in);
    }
    expect(closePlan("full")[1].frames[1].scale).toBe(".62");     // back into the button it came from
  });
  it("reduced motion / Juice minimal: short fades only, no travel, scale or bounce", () => {
    for (const p of [openPlan("min"), closePlan("min"), openPlan("min", "right")]) {
      expect([...props(p)]).toEqual(["opacity"]);
      expect(longest(p)).toBeLessThanOrEqual(T.fade);
    }
    expect(contentPlan("min", 2)).toEqual([]);
    expect(iconPlan("min")).toEqual([]);
  });
  it("calm: no overshoot", () => {
    const scales = openPlan("calm").flatMap((s) => s.frames.map((f) => Number(f.scale ?? 1)));
    expect(Math.max(...scales)).toBe(1);
  });
  it("grows out of the opener, clamped to the box", () => {
    const box = { left: 100, top: 100, width: 400, height: 300 };
    expect(originFor(box, { left: 140, top: 120, width: 20, height: 20 })).toBe("50px 30px");
    expect(originFor(box, { left: 900, top: 0, width: 40, height: 40 })).toBe("400px 0px");   // far-away button: edge
    expect(originFor(box, null)).toBe("50% 50%");
  });
});

describe("dialog helper", () => {
  it("opens with the entrance and closes after the exit animation, then really closes once", async () => {
    const { d, anims } = fakeDialog();
    openDialog(d);
    expect(d.showModal).toHaveBeenCalledTimes(1);
    expect(d.open).toBe(true);
    expect(anims.length).toBeGreaterThan(0);                         // the entrance runs
    const after = vi.fn();
    closeDialog(d, after);
    expect(isClosing(d)).toBe(true);
    expect(isOpen(d)).toBe(false);                                   // logically closed at once
    expect(d.dataset.mClosing).toBe("1");
    expect(d.close).not.toHaveBeenCalled();                          // still on screen, animating out
    anims[anims.length - 2].done();                                  // the exit's fade finishes
    await tick();
    expect(d.close).toHaveBeenCalledTimes(1);
    expect(d.open).toBe(false);
    expect(after).toHaveBeenCalledTimes(1);
    expect(isClosing(d)).toBe(false);
    expect(d.dataset.mClosing).toBeUndefined();
  });

  it("Escape animates the first time (cancel is prevented) and closes at once if pressed again mid-exit", async () => {
    const { d } = fakeDialog();
    openDialog(d);
    const e1 = cancelEvent(d);
    onCancel(e1 as unknown as Event);
    expect(e1.preventDefault).toHaveBeenCalled();
    expect(isClosing(d)).toBe(true);
    expect(d.close).not.toHaveBeenCalled();
    const e2 = cancelEvent(d);
    onCancel(e2 as unknown as Event);                                // second Escape while it animates
    expect(e2.preventDefault).not.toHaveBeenCalled();
    expect(d.close).toHaveBeenCalledTimes(1);
    expect(d.open).toBe(false);
    expect(isClosing(d)).toBe(false);
  });

  it("an Escape the browser won't let us delay closes natively; the close event cleans up", () => {
    const { d } = fakeDialog();
    openDialog(d);
    const e = cancelEvent(d, false);
    onCancel(e as unknown as Event);
    expect(e.preventDefault).not.toHaveBeenCalled();
    d.close();                                                       // what the browser does next
    expect(d.open).toBe(false);
    expect(isClosing(d)).toBe(false);
  });

  it("never gets stuck: if the exit animation never finishes, a timer closes it", () => {
    const { d } = fakeDialog();
    openDialog(d);
    closeDialog(d);
    expect(d.close).not.toHaveBeenCalled();
    vi.advanceTimersByTime(MT.close + 200);
    expect(d.close).toHaveBeenCalledTimes(1);
    expect(d.open).toBe(false);
  });

  it("opening while it closes reverses the exit and it stays open (rapid toggling)", () => {
    const { d, anims } = fakeDialog();
    openDialog(d);
    closeDialog(d);
    const exit = anims.slice(-2);
    openDialog(d);
    expect(exit.every((a) => a.reverse.mock.calls.length === 1)).toBe(true);
    expect(isOpen(d)).toBe(true);
    expect(d.showModal).toHaveBeenCalledTimes(1);                    // never re-shown, never closed
    vi.advanceTimersByTime(2000);
    expect(d.close).not.toHaveBeenCalled();
    expect(d.open).toBe(true);
    for (let i = 0; i < 5; i++) { closeDialog(d); openDialog(d); }   // hammering it
    vi.advanceTimersByTime(2000);
    expect(d.close).not.toHaveBeenCalled();
    expect(isOpen(d)).toBe(true);
    closeDialog(d); closeDialog(d);                                  // a double click on ✕
    vi.advanceTimersByTime(2000);
    expect(d.close).toHaveBeenCalledTimes(1);
  });

  it("Escape while it is still opening closes it (from where it is)", () => {
    const { d, anims } = fakeDialog();
    openDialog(d);
    const entrance = anims.slice();
    onCancel(cancelEvent(d) as unknown as Event);
    expect(entrance.every((a) => a.cancel.mock.calls.length === 1)).toBe(true);
    expect(isClosing(d)).toBe(true);
    finishClose(d);
    expect(d.open).toBe(false);
  });

  it("gives focus back to the button that opened it", async () => {
    const opener = { isConnected: true, focus: vi.fn(), matches: () => true, getBoundingClientRect: () => ({ left: 0, top: 0, width: 10, height: 10 }) };
    const body = {};
    vi.stubGlobal("document", { activeElement: body, body, querySelector: () => null });
    const { d } = fakeDialog();
    noteTrigger(opener as unknown as Element);
    openDialog(d);
    expect(d.style.transformOrigin).toMatch(/px/);                   // grows out of the opener
    closeDialog(d);
    vi.advanceTimersByTime(MT.close + 200);
    expect(d.open).toBe(false);
    expect(opener.focus).toHaveBeenCalledTimes(1);
  });

  it("reduced motion closes with a short fade only", () => {
    setJuice("minimal");
    const { d, anims } = fakeDialog();
    openDialog(d);
    const n = anims.length;
    closeDialog(d);
    const exit = d.animate.mock.calls.slice(n);
    expect(exit.length).toBe(1);
    expect(Object.keys(exit[0][0][0])).toEqual(["opacity"]);
    vi.advanceTimersByTime(T.fade + 200);
    expect(d.open).toBe(false);
  });

  it("closing a dialog that isn't open just runs the callback", () => {
    const { d } = fakeDialog();
    const after = vi.fn();
    closeDialog(d, after);
    expect(after).toHaveBeenCalledTimes(1);
    expect(d.close).not.toHaveBeenCalled();
  });
});

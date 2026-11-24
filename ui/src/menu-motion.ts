// Menu motion: how every dialog, panel and menu opens, closes and switches (docs/ui/MOTION.md, "Menus").
//
//  - Dialogs: installDialogMotion() routes every showModal()/close() and the Escape "cancel" through one helper, so
//    each dialog in the app (Settings, Tasks, Mailing lists, Brain, history, and any added later) pops out of the
//    button that opened it, closes back into it (reversed, faster), and slides sideways when one dialog hands over to
//    another. While a dialog is closing it already reports `open === false`, so opening it again just reverses the
//    exit. Escape always closes: a second Escape (or one the browser won't let us delay) closes at once.
//  - Panels and cards (Today, To-do, Homework, Health, Lab): openFrom() / closeTo() / slideIn() do the same for
//    elements that aren't dialogs.
//  - Readability: text is opaque within ~110 ms and the box is at full size by ~150 ms; the overshoot and the
//    header-icon bounce happen after that, around readable content. Only opacity and scale/translate/rotate move.
//  - Levels follow motion.ts (full / calm / min); a hidden window skips motion (end state at once).
import { EASE, T, hidden, level, type Level, type Step } from "./motion";

export const MT = {
  open: 380,          // the springy settle (the box is readable and full size well before this ends)
  close: 140,         // exits are faster than entrances and never bounce
  fade: 100,          // opacity of an opening box
  contentStagger: 22, contentCap: 66, contentDur: 220,
  iconDelay: 70, iconDur: 480,
  switchPx: 56,
};

export type From = "origin" | "right" | "left" | "below";

// ------------------------------------------------------------------ plans (pure, unit-tested)
/** The box of an opening dialog/panel. Scale grows from the opener (transform-origin set by the caller). */
export function openPlan(lv: Level, from: From = "origin"): Step[] {
  const fill: FillMode = "backwards";
  if (lv === "min") return [{ frames: [{ opacity: 0 }, { opacity: 1 }], opts: { duration: T.fade, easing: EASE.linear, fill } }];
  const op: Step = { frames: [{ opacity: 0 }, { opacity: 1 }], opts: { duration: MT.fade, easing: EASE.linear, fill } };
  const calm = lv === "calm";
  if (from === "left" || from === "right") {
    const px = Math.round((from === "right" ? 1 : -1) * MT.switchPx * (calm ? 0.5 : 1));
    return [op, { frames: [{ translate: `${px}px 0`, scale: calm ? "1" : ".96" }, { translate: "0 0", scale: "1" }],
                  opts: { duration: calm ? T.base : 320, easing: calm ? EASE.out : EASE.snap, fill } }];
  }
  if (from === "below") {
    return [op, { frames: [{ translate: `0 ${calm ? 8 : 18}px`, scale: calm ? "1" : ".97" }, { translate: "0 0", scale: "1" }],
                  opts: { duration: calm ? T.base : 340, easing: calm ? EASE.out : EASE.pop, fill } }];
  }
  if (calm) return [op, { frames: [{ scale: ".88" }, { scale: "1" }], opts: { duration: T.base, easing: EASE.out, fill } }];
  // full: out of the button, a little past full size, settle. With this ease-out the box passes 100 % at ~140 ms.
  return [op, { frames: [{ scale: ".5" }, { scale: "1.035", offset: 0.55 }, { scale: ".995", offset: 0.8 }, { scale: "1" }],
                opts: { duration: MT.open, easing: EASE.out, fill } }];
}

/** Closing: the opening reversed (back into the button, or out to the side when another menu takes over), faster. */
export function closePlan(lv: Level, to: From = "origin"): Step[] {
  const fill: FillMode = "forwards";
  const dur = lv === "min" ? T.fade : MT.close;
  const op: Step = { frames: [{ opacity: 1 }, { opacity: 0 }], opts: { duration: dur, easing: EASE.in, fill } };
  if (lv === "min") return [op];
  const calm = lv === "calm";
  const end: Keyframe = to === "left" || to === "right"
    ? { translate: `${Math.round((to === "right" ? 1 : -1) * MT.switchPx * (calm ? 0.5 : 1))}px 0`, scale: "1" }
    : to === "below" ? { translate: `0 ${calm ? 6 : 14}px`, scale: calm ? "1" : ".97" }
    : { translate: "0 0", scale: calm ? ".92" : ".62" };
  return [op, { frames: [{ translate: "0 0", scale: "1" }, end], opts: { duration: dur, easing: EASE.in, fill } }];
}

/** Contents cascade in behind the box: never fully transparent, so nothing is unreadable for long. */
export function contentPlan(lv: Level, i: number): Step[] {
  if (lv === "min") return [];
  const delay = Math.min(i * MT.contentStagger, MT.contentCap);
  const calm = lv === "calm";
  return [{ frames: [{ opacity: 0.35, translate: `0 ${calm ? 5 : 12}px` }, { opacity: 1, translate: "0 0" }],
            opts: { duration: calm ? 180 : MT.contentDur, delay, easing: calm ? EASE.out : EASE.pop, fill: "backwards" } }];
}

/** The header icon bounces in once the box has landed (full only; calm gets a small pop). */
export function iconPlan(lv: Level): Step[] {
  if (lv === "min") return [];
  if (lv === "calm") return [{ frames: [{ scale: "1" }, { scale: "1.08" }, { scale: "1" }], opts: { duration: T.base, delay: MT.iconDelay, easing: EASE.out } }];
  return [{ frames: [
    { scale: ".4", rotate: "-18deg" }, { scale: "1.25", rotate: "8deg", offset: 0.45 }, { scale: ".92", rotate: "-3deg", offset: 0.72 }, { scale: "1", rotate: "0deg" },
  ], opts: { duration: MT.iconDur, delay: MT.iconDelay, easing: EASE.out, fill: "backwards" } }];
}

/** transform-origin (px, relative to the box) that makes a box grow out of the opener's centre. Clamped to the box
 *  edges so a far-away button doesn't turn the pop into a long slide. */
export function originFor(box: { left: number; top: number; width: number; height: number },
                          opener: { left: number; top: number; width: number; height: number } | null): string {
  if (!opener || !box.width || !box.height) return "50% 50%";
  const cx = opener.left + opener.width / 2 - box.left, cy = opener.top + opener.height / 2 - box.top;
  const x = Math.max(0, Math.min(box.width, cx)), y = Math.max(0, Math.min(box.height, cy));
  return `${Math.round(x)}px ${Math.round(y)}px`;
}

// ------------------------------------------------------------------ the opener (origin) of a menu
const hasDom = typeof document !== "undefined";
const doc = (): Document | null => (typeof document !== "undefined" ? document : null);   // read late: tests stub it
let trigger: { el: Element; at: number } | null = null;
const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
/** Remember what the owner just pressed: the next menu that opens grows out of it. */
export function noteTrigger(el: Element | null | undefined) { if (el) trigger = { el, at: now() }; }
/** The element a menu opening now should grow out of (the button just pressed, or the focused button). */
export function openerFor(box?: Element | null, maxAgeMs = 10_000): Element | null {
  const D = doc();
  if (!D) return null;
  const ok = (el: Element | null | undefined) => !!el && el.isConnected && !box?.contains(el) && el !== D.body;
  if (trigger && now() - trigger.at < maxAgeMs && ok(trigger.el)) return trigger.el;
  const a = D.activeElement;
  if (ok(a) && a!.matches?.("button, [role=button], [role=tab], summary")) return a;
  return null;
}

// ------------------------------------------------------------------ running plans
type Anim = { finished: Promise<unknown>; cancel(): void; finish?(): void; reverse?(): void; id?: string; playState?: string };
type Box = Element & { animate?: Element["animate"]; style?: CSSStyleDeclaration };
function play(el: Box | null | undefined, steps: Step[], id: string): Anim[] {
  if (!el || !steps.length || !el.animate || hidden() || (hasDom && !el.isConnected)) return [];
  const out: Anim[] = [];
  for (const s of steps) {
    try { const a = el.animate(s.frames, { ...s.opts, id }) as unknown as Anim; out.push(a); } catch { /* no individual transforms */ }
  }
  return out;
}
const rectOf = (el: Element) => { const r = el.getBoundingClientRect(); return { left: r.left, top: r.top, width: r.width, height: r.height }; };

/** Stagger an element's main blocks in and bounce its header icon (shared by dialogs and panels). */
function playContents(root: Element, lv: Level) {
  const items = contentsOf(root);
  items.forEach((el, i) => play(el, contentPlan(lv, i), "mm-c"));
  const icon = root.querySelector(":scope header .bi, :scope > header .icon, .taskstop h3, :scope > h3 .bi, header strong, .todaytabs [aria-selected=true]");
  if (icon) play(icon, iconPlan(lv), "mm-i");
}
/** The blocks of a menu worth cascading: its header and the first few sections (not every row: that's the lists' job). */
export function contentsOf(root: Element): Element[] {
  const one = root.children.length === 1 && !(root.firstElementChild as HTMLElement).matches?.("header, h3") ? root.firstElementChild! : root;
  const out: Element[] = [];
  for (const c of Array.from(one.children)) {
    if ((c as HTMLElement).matches?.(".close, .toast, .bk-bg, .m-load, script, [hidden]")) continue;
    if ((c as HTMLElement).matches?.(".body")) out.push(...Array.from(c.children).slice(0, 4));
    else out.push(c);
    if (out.length >= 7) break;
  }
  return out.filter((e) => !(e as HTMLElement).matches?.("header, h3")).slice(0, 6);
}

// ------------------------------------------------------------------ dialogs
type Dlg = HTMLDialogElement & Box;
interface DState { phase: "opening" | "closing"; anims: Anim[]; timer: ReturnType<typeof setTimeout> | null; then: (() => void)[]; to: From; rv?: string }
const states = new WeakMap<object, DState>();
const openers = new WeakMap<object, Element | null>();
let natives: { showModal: () => void; close: (rv?: string) => void; open: (this: HTMLDialogElement) => boolean } | null = null;

// Before installDialogMotion() (and in unit tests with stand-in dialogs) the element's own methods are the real ones.
const realOpen = (d: Dlg) => (natives ? natives.open.call(d) : !!d.open);
const nativeShow = (d: Dlg) => (natives ? natives.showModal.call(d) : d.showModal());
const nativeClose = (d: Dlg, rv?: string) => (natives ? natives.close.call(d, rv) : d.close(rv));

/** True while a dialog is animating out (it's logically closed already). */
export const isClosing = (d: object) => states.get(d)?.phase === "closing";
/** Logically open: shown and not on its way out. */
export const isOpen = (d: Dlg) => realOpen(d) && !isClosing(d);

function stop(st: DState | undefined) {
  if (!st) return;
  if (st.timer) clearTimeout(st.timer);
  st.timer = null;
  for (const a of st.anims) { try { a.cancel(); } catch { /* gone */ } }
  st.anims = [];
}

/** Open a dialog modally with the menu entrance. Opening one that is closing reverses its exit instead. */
export function openDialog(d: Dlg, opts: { from?: From } = {}) {
  const st = states.get(d);
  if (st?.phase === "closing") {                         // interrupted: turn around from wherever it is
    const back = st.anims.filter((a) => typeof a.reverse === "function");
    if (st.timer) clearTimeout(st.timer);
    st.timer = null;
    delete (d as HTMLElement).dataset.mClosing;
    states.delete(d);
    closingNow.delete(d);
    if (back.length && level() !== "min") {
      for (const a of back) a.reverse!();
      const done = () => { for (const a of back) { try { a.cancel(); } catch { /* gone */ } } };
      Promise.all(back.map((a) => a.finished)).then(done, () => {});
    } else for (const a of st.anims) { try { a.cancel(); } catch { /* gone */ } }
    return;
  }
  if (realOpen(d)) return;                                // already open (a re-render): no replay
  const opener = openerFor(d);
  openers.set(d, opener ?? doc()?.activeElement ?? null);
  // another dialog handing over to this one (Tasks → Mailing lists): slide across instead of popping
  const handover = opts.from ?? (closingNow.size ? "right" : "origin");
  for (const other of closingNow) { const o = states.get(other); if (o && o.to === "origin" && handover === "right") retarget(other as Dlg, "left"); }
  nativeShow(d);
  (d as HTMLElement).dataset.m = "1";
  const lv = level();
  if (hidden()) return;
  if (handover === "origin" && opener) {
    try { (d.style as CSSStyleDeclaration).transformOrigin = originFor(rectOf(d), rectOf(opener)); } catch { /* no layout */ }
  } else if (d.style) d.style.transformOrigin = "";
  const anims = play(d, openPlan(lv, handover), "mm-open");
  if (!anims.length) return;
  const s: DState = { phase: "opening", anims, timer: null, then: [], to: "origin" };
  states.set(d, s);
  playContents(d, lv);
  const end = () => { if (states.get(d) === s) states.delete(d); };
  anims[anims.length - 1].finished.then(end, end);
}

const closingNow = new Set<object>();
function retarget(d: Dlg, to: From) {
  const st = states.get(d);
  if (!st || st.phase !== "closing") return;
  for (const a of st.anims) { try { a.cancel(); } catch { /* gone */ } }
  st.to = to;
  st.anims = play(d, closePlan(level(), to), "mm-close");
  if (st.anims.length) st.anims[0].finished.then(() => finishClose(d), () => {});
  else finishClose(d);
}

/** Close a dialog with the exit animation, then really close it (close event, focus back to the opener). */
export function closeDialog(d: Dlg, then?: () => void, rv?: string) {
  const st = states.get(d);
  if (st?.phase === "closing") { if (then) st.then.push(then); return; }   // a double click: one close is enough
  if (!realOpen(d)) { then?.(); return; }
  stop(st);
  states.delete(d);
  const lv = level();
  const s: DState = { phase: "closing", anims: [], timer: null, then: then ? [then] : [], to: "origin", rv };
  states.set(d, s);
  closingNow.add(d);
  (d as HTMLElement).dataset.mClosing = "1";
  s.anims = play(d, closePlan(lv, "origin"), "mm-close");
  if (!s.anims.length) { finishClose(d); return; }
  s.anims[0].finished.then(() => finishClose(d), () => {});
  s.timer = setTimeout(() => finishClose(d), (lv === "min" ? T.fade : MT.close) + 160);   // never stuck open
}

/** End a close now: the real close() (fires "close"; the cleanup runs from there). */
export function finishClose(d: Dlg) {
  const st = states.get(d);
  if (!st || st.phase !== "closing") return;
  if (realOpen(d)) { try { nativeClose(d, st.rv); } catch { /* already gone */ } }
  cleanup(d);
}

function cleanup(d: Dlg) {
  const st = states.get(d);
  closingNow.delete(d);
  const wasClosing = st?.phase === "closing";
  stop(st);
  states.delete(d);
  delete (d as HTMLElement).dataset.mClosing;
  if (d.style) d.style.transformOrigin = "";
  if (wasClosing) for (const fn of st!.then) { try { fn(); } catch (e) { console.error(e); } }
  // Focus goes back to whatever opened it (the browser does this too; this covers a lost focus, e.g. the opener
  // was re-rendered or focus sat on <body> when the dialog opened).
  const D = doc();
  if (D) {
    const a = D.activeElement;
    const opener = openers.get(d);
    openers.delete(d);                                     // once per open (the "close" event may run this again)
    const lost = !a || a === D.body || d.contains(a);
    let otherModal: Element | null = null;
    try { otherModal = D.querySelector("dialog:modal"); } catch { /* old engine */ }
    if (lost && !otherModal && opener && opener !== D.body && (opener as HTMLElement).isConnected) {
      try { (opener as HTMLElement).focus({ preventScroll: true }); } catch { /* not focusable */ }
    }
  }
}

/** Escape / the browser's close request. The first one animates; one during the exit (or one the browser won't let
 *  us delay) closes at once. */
export function onCancel(e: Event) {
  const d = e.target as Dlg;
  if (!d || (d as any).tagName !== "DIALOG") return;
  if (isClosing(d)) { finishClose(d); return; }           // let the browser close it now (no preventDefault)
  if (!e.cancelable || hidden()) return;                  // the browser closes it; "close" cleans up
  e.preventDefault();
  closeDialog(d);
}
export function onClose(e: Event) {
  const d = e.target as Dlg;
  if (!d || (d as any).tagName !== "DIALOG") return;
  cleanup(d);
}

/** Route every dialog in the page through the helpers above (call once, before any dialog opens). */
export function installDialogMotion() {
  if (!hasDom || typeof HTMLDialogElement === "undefined" || natives) return;
  const p = HTMLDialogElement.prototype;
  const openDesc = Object.getOwnPropertyDescriptor(p, "open")!;
  natives = { showModal: p.showModal, close: p.close, open: openDesc.get as (this: HTMLDialogElement) => boolean };
  p.showModal = function (this: Dlg) { openDialog(this); };
  p.close = function (this: Dlg, rv?: string) { closeDialog(this, undefined, rv); };
  Object.defineProperty(p, "open", {
    configurable: true, enumerable: openDesc.enumerable,
    get(this: Dlg) { return natives!.open.call(this) && !isClosing(this); },
    set(this: Dlg, v: boolean) { openDesc.set!.call(this, v); },
  });
  document.addEventListener("cancel", onCancel, true);
  document.addEventListener("close", onClose, true);
  // what the owner pressed (pointer or keyboard): menus grow out of it
  document.addEventListener("pointerdown", (e) => noteTrigger((e.target as Element)?.closest?.("button, [role=button], [role=tab], summary, a")), true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") noteTrigger((e.target as Element)?.closest?.("button, [role=button], [role=tab], summary, a"));
  }, true);
}

// ------------------------------------------------------------------ panels and cards (not dialogs)
const panelState = new WeakMap<object, { anims: Anim[]; timer: ReturnType<typeof setTimeout> | null }>();

/** A panel or card that just appeared: pops out of `opener` (default: the button just pressed), contents cascade,
 *  header icon bounces. Replaces the element's CSS entrance (class m-js). */
export function openFrom(el: HTMLElement | null | undefined, opener: Element | null = openerFor(el), from: From = "origin") {
  if (!el || hidden()) return [];
  const ps = panelState.get(el);
  if (ps) { if (ps.timer) clearTimeout(ps.timer); for (const a of ps.anims) { try { a.cancel(); } catch { /* gone */ } } panelState.delete(el); }
  delete el.dataset.mClosing;
  const lv = level();
  el.classList.add("m-js");
  if (from === "origin" && opener) el.style.transformOrigin = originFor(rectOf(el), rectOf(opener));
  const anims = play(el, openPlan(lv, from), "mm-open");
  playContents(el, lv);
  return anims;
}

/** Animate a panel out (back toward where it came from, faster), then `done` (hide or remove it). Calling openFrom
 *  on it meanwhile cancels the close. Never leaves it half-closed: a timer finishes the job if the animation can't. */
export function closeTo(el: HTMLElement | null | undefined, done: () => void, to: From = "origin") {
  if (!el) return;
  const prev = panelState.get(el);
  if (prev) return;                                        // already closing
  const anims = play(el, closePlan(level(), to), "mm-close");
  if (!anims.length) { done(); return; }
  el.dataset.mClosing = "1";
  const st = { anims, timer: null as ReturnType<typeof setTimeout> | null };
  panelState.set(el, st);
  let called = false;
  const fin = () => {
    if (called || panelState.get(el) !== st) return;
    called = true;
    if (st.timer) clearTimeout(st.timer);
    panelState.delete(el);
    delete el.dataset.mClosing;
    done();
    for (const a of anims) { try { a.cancel(); } catch { /* gone */ } }
  };
  anims[0].finished.then(fin, () => {});
  st.timer = setTimeout(fin, MT.close + 160);
}
export const panelClosing = (el: object) => panelState.has(el);

/** Switching tabs or sections: the new content slides in from the side it lives on. */
export function slideIn(el: Element | null | undefined, dir: "left" | "right" | "up" | "down") {
  const lv = level();
  if (!el || lv === "min") return [];
  const a = lv === "calm" ? 0.5 : 1;
  const px = Math.round(28 * a);
  const from = dir === "right" ? `${px}px 0` : dir === "left" ? `${-px}px 0` : dir === "down" ? `0 ${px}px` : `0 ${-px}px`;
  return play(el, [{ frames: [{ opacity: 0.3, translate: from }, { opacity: 1, translate: "0 0" }],
                     opts: { duration: lv === "calm" ? 200 : 300, easing: lv === "calm" ? EASE.out : EASE.snap, fill: "backwards" } }], "mm-slide");
}

/** The window came back from the tray: the header buttons hop in, the open panel pops. Once, no loop. */
export function wake(root: ParentNode = document) {
  const lv = level();
  if (lv === "min" || hidden()) return;
  const btns = Array.from(root.querySelectorAll("#side > header > button:not([hidden])")).slice(0, 9);
  btns.forEach((b, i) => play(b, [{ frames: [{ translate: `0 ${lv === "calm" ? 4 : 10}px`, opacity: 0.4 }, { translate: "0 0", opacity: 1 }],
    opts: { duration: lv === "calm" ? 200 : 320, delay: Math.min(i * 25, 150), easing: lv === "calm" ? EASE.out : EASE.pop, fill: "backwards" } }], "mm-wake"));
  const panel = root.querySelector("#today:not([hidden]), #cards > .card:not(.folded)");
  if (panel) play(panel, [{ frames: [{ scale: lv === "calm" ? ".98" : ".95", opacity: 0.6 }, { scale: "1", opacity: 1 }],
    opts: { duration: lv === "calm" ? 200 : 320, easing: lv === "calm" ? EASE.out : EASE.pop } }], "mm-wake");
}
if (hasDom) {
  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { hiddenAt = now(); return; }
    if (hiddenAt && now() - hiddenAt > 800) requestAnimationFrame(() => wake());
  });
}

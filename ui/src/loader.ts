// Loading UIs for menus that take time (docs/ui/MOTION.md, "Loading").
//
// One rule set for every slow load (Today, Homework, To-do, Health, Settings sections, Tasks, Mailing lists, the
// morning brief, update checks, image generation…):
//  - nothing shows for the first LOAD.delay ms (fast loads stay instant, no flash);
//  - once shown, the loader stays at least LOAD.minShow ms (no flicker);
//  - a skeleton in the panel's real layout with a jungle shimmer, a small playful loader (banana trio, swinging
//    vine or a bobbing monkey head; CSS + inline SVG), and words that change if it's slow ("Still fetching…");
//  - an error state with Try again;
//  - the skeleton crossfades out over the real content (no layout jump: the skeleton matches the real layout);
//  - motion follows html[data-motion] (full / calm / min = a slow opacity pulse), pauses while the window is
//    hidden, and nothing keeps running once the content is in.
import { h } from "./dom";
import { hidden, level } from "./motion";

export const LOAD = { delay: 150, minShow: 400, fade: 220, steps: [3000, 8000, 15000] };

// ------------------------------------------------------------------ timing (pure, unit-tested)
export interface Clock { now(): number; set(fn: () => void, ms: number): unknown; clear(id: unknown): void }
export const realClock: Clock = {
  now: () => (typeof performance !== "undefined" ? performance.now() : Date.now()),
  set: (fn, ms) => setTimeout(fn, ms), clear: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};
export interface Gated<T> { value?: T; error?: unknown; failed: boolean; shown: boolean }
export interface GateUi { show(): void; message?(step: number): void }

/**
 * Run `task` with a loader that only appears after `delay` and, once shown, stays at least `minShow`.
 * Resolves (never rejects) when the content may replace the loader. `message(n)` fires at each LOAD.steps mark while
 * the loader is up (n = 1, 2, 3).
 */
export function gate<T>(task: Promise<T>, ui: GateUi, o: { delay?: number; minShow?: number; steps?: number[] } = {},
                        clock: Clock = realClock): Promise<Gated<T>> {
  const delay = o.delay ?? LOAD.delay, minShow = o.minShow ?? LOAD.minShow, steps = o.steps ?? LOAD.steps;
  const t0 = clock.now();
  return new Promise((resolve) => {
    let shownAt: number | null = null;
    let settled = false;
    const timers: unknown[] = [];
    const show = () => {
      if (settled) return;
      shownAt = clock.now();
      ui.show();
      steps.forEach((ms, i) => timers.push(clock.set(() => { if (!settled) ui.message?.(i + 1); }, Math.max(0, ms - (shownAt! - t0)))));
    };
    const showTimer = delay <= 0 ? (show(), null) : clock.set(show, delay);
    const settle = (r: Omit<Gated<T>, "shown">) => {
      settled = true;
      if (showTimer !== null) clock.clear(showTimer);
      timers.forEach((t) => clock.clear(t));
      if (shownAt === null) { resolve({ ...r, shown: false }); return; }
      const wait = shownAt + minShow - clock.now();
      if (wait > 0) clock.set(() => resolve({ ...r, shown: true }), wait); else resolve({ ...r, shown: true });
    };
    task.then((value) => settle({ value, failed: false }), (error) => settle({ error, failed: true }));
  });
}

/** The words a loader shows at each step (0 = at once, then after 3 s, 8 s, 15 s). */
export function loadMessage(what: string, step: number, custom?: string[]): string {
  if (custom?.[step]) return custom[step];
  const w = what || "that";
  return [`Loading ${w}…`, `Still fetching ${w}…`, "Still working on it. Hang tight 🍌",
          "This is taking longer than usual. You can keep chatting meanwhile."][Math.min(step, 3)];
}

/** `{ok: false, error}` results are failures; anything else is content. */
export function failureOf(v: unknown): string | null {
  if (v && typeof v === "object" && "ok" in v && (v as { ok: unknown }).ok === false) {
    const e = (v as { error?: unknown }).error;
    return typeof e === "string" && e ? e : "Something went wrong.";
  }
  return null;
}

// ------------------------------------------------------------------ the pieces (DOM)
export type Skel = "list" | "tiles" | "health" | "block" | "rows" | "table" | "settings" | "form" | "tile";
export type Art = "bananas" | "vine" | "monkey" | "none";

const bar = (cls = "") => h("i", { class: `m-sk ${cls}` });
/** A skeleton in the real layout of a panel (sizes match the real rows so the content lands where it was). */
export function skeleton(kind: Skel, rows = 4): HTMLElement {
  const box = h("div", { class: `m-skel m-skel-${kind}`, "aria-hidden": "true" });
  const n = Math.max(1, Math.min(rows, 8));
  const row = (i: number) => h("div", { class: "m-sk-row", style: `--i:${i}` }, bar("m-sk-dot"),
    h("div", { class: "m-sk-lines" }, bar(`m-sk-l ${i % 2 ? "m-w60" : "m-w80"}`), bar("m-sk-s m-w40")));
  switch (kind) {
    case "tiles":
      box.append(h("div", { class: "m-sk-hero" }, bar("m-sk-s m-w30"), bar("m-sk-xl m-w70"), bar("m-sk-s m-w50"), bar("m-sk-pill")),
        h("div", { class: "m-sk-grid" }, ...[0, 1, 2, 3].map((i) => h("div", { class: "m-sk-tile", style: `--i:${i + 1}` },
          bar("m-sk-s m-w40"), bar("m-sk-l m-w80"), bar("m-sk-l m-w60")))));
      break;
    case "health":
      box.append(h("div", { class: "m-sk-healthtop" }, bar("m-sk-ring"), h("div", { class: "m-sk-lines" }, bar("m-sk-xl m-w50"), bar("m-sk-l m-w70"), bar("m-sk-s m-w40"))),
        h("div", { class: "m-sk-grid three" }, ...[0, 1, 2].map((i) => h("div", { class: "m-sk-tile", style: `--i:${i + 1}` }, bar("m-sk-s m-w50"), bar("m-sk-xl m-w40")))),
        bar("m-sk-chart"));
      break;
    case "table":
      for (let i = 0; i < n; i++) box.append(h("div", { class: "m-sk-trow", style: `--i:${i}` }, bar("m-sk-dot sq"), bar("m-sk-l m-w30"), bar("m-sk-s m-w15"), bar("m-sk-s m-w15"), bar("m-sk-pill sm")));
      break;
    case "settings":
      box.append(h("div", { class: "m-sk-nav" }, ...[0, 1, 2, 3, 4, 5].map(() => bar("m-sk-pill sm"))));
      for (let i = 0; i < 3; i++) box.append(h("div", { class: "m-sk-sec", style: `--i:${i}` }, bar("m-sk-h m-w30"), bar("m-sk-l m-w80"), bar("m-sk-l m-w60"), bar("m-sk-pill")));
      break;
    case "form":
      box.append(bar("m-sk-h m-w40"));
      for (let i = 0; i < n; i++) box.append(h("div", { class: "m-sk-field", style: `--i:${i}` }, bar("m-sk-s m-w25"), bar("m-sk-input")));
      box.append(bar("m-sk-pill"));
      break;
    case "block":
      for (let i = 0; i < n; i++) box.append(bar(`m-sk-l ${["m-w80", "m-w60", "m-w70", "m-w50"][i % 4]}`));
      break;
    case "tile":
      box.append(bar("m-sk-l m-w80"), bar("m-sk-l m-w60"));
      break;
    case "rows":
      for (let i = 0; i < n; i++) box.append(h("div", { class: "m-sk-row slim", style: `--i:${i}` }, bar("m-sk-dot sm"), bar(`m-sk-l ${i % 2 ? "m-w70" : "m-w50"}`)));
      break;
    default:                                              // list: to-dos, homework, accounts, events
      box.append(h("div", { class: "m-sk-head" }, bar("m-sk-pill sm"), bar("m-sk-pill sm"), bar("m-sk-pill sm")));
      for (let i = 0; i < n; i++) box.append(row(i));
  }
  return box;
}

const BANANA = `<svg viewBox="0 0 32 32" width="22" height="22"><path d="M5 19c6 7 18 6 22-6 1-3 0-6-1-7-2 7-8 12-19 11z" fill="#ffd43b" stroke="#14240f" stroke-width="2.4" stroke-linejoin="round"/><path d="M26 6l1-3" stroke="#14240f" stroke-width="2.6" stroke-linecap="round"/><path d="M9 20c6 2 12 0 15-6" fill="none" stroke="#e0a800" stroke-width="1.6" stroke-linecap="round"/></svg>`;
const HEAD = `<svg viewBox="0 0 48 44" width="40" height="36"><circle cx="8" cy="22" r="7" fill="#8b5a2b" stroke="#14240f" stroke-width="2.4"/><circle cx="40" cy="22" r="7" fill="#8b5a2b" stroke="#14240f" stroke-width="2.4"/><circle cx="8" cy="22" r="3" fill="#f2c48d"/><circle cx="40" cy="22" r="3" fill="#f2c48d"/><circle cx="24" cy="21" r="17" fill="#8b5a2b" stroke="#14240f" stroke-width="2.6"/><ellipse cx="24" cy="27" rx="12" ry="10" fill="#f2c48d"/><ellipse cx="18.5" cy="18" rx="2.6" ry="3.2" fill="#14240f"/><ellipse cx="29.5" cy="18" rx="2.6" ry="3.2" fill="#14240f"/><circle cx="19.3" cy="17" r="1" fill="#fff"/><circle cx="30.3" cy="17" r="1" fill="#fff"/><path d="M18 29c3 3 9 3 12 0" fill="none" stroke="#14240f" stroke-width="2.4" stroke-linecap="round"/></svg>`;
const LEAF = `<svg viewBox="0 0 20 12" width="16" height="10"><path d="M1 6c5-6 13-6 18 0-5 6-13 6-18 0z" fill="#3cc24a" stroke="#14240f" stroke-width="1.6"/></svg>`;

/** The little loader character (decorative: the words next to it carry the meaning). */
export function loaderArt(kind: Art): HTMLElement | null {
  if (kind === "none") return null;
  const el = h("span", { class: `m-art m-art-${kind}`, "aria-hidden": "true" });
  if (kind === "bananas") el.innerHTML = [0, 1, 2].map((i) => `<span class="m-ban" style="--i:${i}">${BANANA}</span>`).join("");
  else if (kind === "vine") el.innerHTML = `<span class="m-vine"><span class="m-vine-rope"></span><span class="m-vine-leaf">${LEAF}</span><span class="m-vine-head">${HEAD}</span></span>`;
  else el.innerHTML = `<span class="m-head">${HEAD}</span><span class="m-head-shadow"></span>`;
  return el;
}

export interface LoadOpts<T = unknown> {
  what: string;                      // "your homework" → "Loading your homework…", "Still fetching your homework…"
  skel?: Skel; rows?: number; art?: Art;
  msgs?: string[];                   // custom words per step
  compact?: boolean;                 // inline (a settings row): art + words, no big skeleton
  failed?: (v: T) => string | null | undefined;
  retry?: boolean;                   // offer Try again on failure (default true)
  delay?: number; minShow?: number;
}

/** The loading block: art + words + skeleton. Live region: the words are announced, the art and bars are hidden. */
export function loadingBox(o: LoadOpts<any>): HTMLElement {
  const msg = h("p", { class: "m-load-msg" }, loadMessage(o.what, 0, o.msgs));
  const box = h("div", { class: `m-load ${o.compact ? "compact" : ""}`, role: "status", "aria-live": "polite", "data-step": "0" },
    h("div", { class: "m-load-top" }, loaderArt(o.art ?? "bananas"), msg),
    o.compact ? null : skeleton(o.skel ?? "list", o.rows));
  return box;
}
function setStep(box: HTMLElement, o: LoadOpts<any>, step: number) {
  const msg = box.querySelector<HTMLElement>(".m-load-msg");
  if (!msg) return;
  msg.textContent = loadMessage(o.what, step, o.msgs);
  box.dataset.step = String(step);
  if (level() !== "min" && !hidden()) msg.animate?.([{ opacity: 0.2, translate: "0 6px" }, { opacity: 1, translate: "0 0" }], { duration: 180, easing: "ease-out" });
}

/** The fx layer the skeleton fades out on. Inside a modal dialog it's a click-through popover, which sits in the top
 *  layer above the dialog and survives the dialog redrawing its children (Settings does on every render). */
function ghostHost(near: Element): HTMLElement | null {
  const dlg = near.closest("dialog");
  if (dlg) {
    if (dlg.getAnimations?.().some((a) => (a as Animation).playState === "running" && String((a as Animation).id).startsWith("mm-"))) return null;
    let fx = document.getElementById("m-fx-top");
    if (!fx) { fx = h("div", { id: "m-fx-top", popover: "manual", "aria-hidden": "true" }); document.body.append(fx); }
    if (typeof fx.showPopover !== "function") return null;
    try { if (fx.matches(":popover-open")) fx.hidePopover(); fx.showPopover(); } catch { return null; }   // re-show = above the newest dialog
    return fx;
  }
  let fx = document.getElementById("m-fx");
  if (!fx) { fx = h("div", { id: "m-fx", "aria-hidden": "true" }); fx.inert = true; document.body.append(fx); }
  return fx;
}

/** Take the loader out: its skeleton fades away on top while the real content (rendered right after) fades in
 *  underneath, in the same place. Then nothing of it is left running. */
export function reveal(box: HTMLElement | null | undefined, host?: HTMLElement | null) {
  if (!box) return;
  const parent = host ?? box.parentElement;
  parent?.removeAttribute("aria-busy");
  if (parent) {
    parent.dataset.mReveal = "1";
    setTimeout(() => { if (parent.dataset.mReveal) delete parent.dataset.mReveal; }, LOAD.fade + 200);
  }
  if (!box.isConnected || hidden() || level() === "min") { box.remove(); return; }
  const r = box.getBoundingClientRect();
  const fx = r.width && r.height ? ghostHost(box) : null;
  if (!fx) { box.remove(); return; }
  box.classList.add("m-leaving");
  box.removeAttribute("role"); box.removeAttribute("aria-live");
  Object.assign(box.style, { position: "fixed", left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px`, margin: "0" });
  fx.append(box);
  const a = box.animate?.([{ opacity: 1 }, { opacity: 0 }], { duration: LOAD.fade, easing: "ease-out", fill: "forwards" });
  const rm = () => {
    box.remove();
    if (fx.id === "m-fx-top" && !fx.childElementCount) { try { fx.hidePopover(); } catch { /* already hidden */ } }
  };
  if (a) a.finished.then(rm, rm); else rm();
  setTimeout(rm, LOAD.fade + 300);
}

/** The error state: what went wrong and Try again (focus moves to it, so the keyboard can retry at once). */
export function errorBox(message: string, what: string, onRetry: (() => void) | null): HTMLElement {
  const retry = onRetry ? h("button", { type: "button", class: "primary m-retry", onclick: onRetry }, "↻ Try again") : null;
  const box = h("div", { class: "m-load-error", role: "alert" },
    h("span", { class: "m-art m-art-sad", "aria-hidden": "true" }),
    h("div", {}, h("p", { class: "m-err-title" }, `Couldn't load ${what}`), h("p", { class: "meta" }, message), retry));
  (box.querySelector(".m-art-sad") as HTMLElement).innerHTML = HEAD;
  return box;
}

/**
 * Load into a panel with the full loading UI.
 *   mount():  called only if a loader must show (slow load or an error): returns where it goes (e.g. a new card).
 *   load():   the backend call; called again on Try again.
 * Resolves with the value once it's in (after the minimum display time) plus the host if one was mounted, so the
 * caller renders into that same host. Failures stay on screen with Try again; the promise resolves after a retry
 * works (if the panel is closed meanwhile it simply never resolves).
 */
export async function loadInto<T>(mount: () => HTMLElement | null, load: () => Promise<T>, o: LoadOpts<T>):
    Promise<{ value: T; host: HTMLElement | null }> {
  let host: HTMLElement | null = null;
  let box: HTMLElement | null = null;
  let delay = o.delay ?? LOAD.delay;
  for (;;) {
    const res = await gate(load(), {
      show: () => {
        host ??= mount();
        if (!host) return;
        host.setAttribute("aria-busy", "true");
        box = loadingBox(o);
        host.append(box);
      },
      message: (n) => { if (box) setStep(box, o, n); },
    }, { delay, minShow: o.minShow });
    const err = res.failed ? String((res.error as Error)?.message ?? res.error ?? "Something went wrong.")
      : (o.failed ? o.failed(res.value as T) : failureOf(res.value)) ?? null;
    if (!err) {
      if (box) reveal(box, host);
      return { value: res.value as T, host };
    }
    if (o.retry === false) { if (box) reveal(box, host); return { value: res.value as T, host }; }
    host ??= mount();
    (box as HTMLElement | null)?.remove();
    if (!host) return new Promise(() => {});
    host.removeAttribute("aria-busy");
    await new Promise<void>((retry) => {
      const eb = errorBox(err, o.what, () => { eb.remove(); retry(); });
      host!.append(eb);
      eb.querySelector<HTMLElement>(".m-retry")?.focus({ preventScroll: true });
    });
    box = null;
    delay = 0;                                            // the owner asked: show the loader at once
  }
}

/**
 * A loader for something that finishes by an event, not a promise (Check everything, a mailing-list scan):
 * shows at once, steps its words, and done() takes it out (respecting the minimum display time).
 */
export function startLoading(host: HTMLElement, o: LoadOpts<any>, clock: Clock = realClock) {
  const box = loadingBox(o);
  host.setAttribute("aria-busy", "true");
  host.append(box);
  const t0 = clock.now();
  const timers = (o.msgs?.length ? o.msgs.map((_, i) => i).slice(1) : [1, 2, 3])
    .map((n) => clock.set(() => setStep(box, o, n), (LOAD.steps[n - 1] ?? LOAD.steps[LOAD.steps.length - 1] * n)));
  let ended = false;
  return {
    box,
    done(then?: () => void) {
      if (ended) return;
      ended = true;
      timers.forEach((t) => clock.clear(t));
      const wait = t0 + (o.minShow ?? LOAD.minShow) - clock.now();
      const fin = () => { reveal(box, host); then?.(); };
      if (wait > 0) clock.set(fin, wait); else fin();
    },
  };
}

/**
 * A button whose action takes time (Check now, Detect, Connect…): after LOAD.delay it shows a tiny banana trio and
 * `busyText`, keeps that at least LOAD.minShow, and puts the button back when done. Returns the action's result.
 */
export async function busyButton<T>(btn: HTMLButtonElement, task: () => Promise<T>, busyText?: string): Promise<T> {
  const label = Array.from(btn.childNodes);
  let shown = false;
  btn.disabled = true;
  const res = await gate(task(), {
    show: () => {
      shown = true;
      btn.classList.add("m-btn-loading");
      btn.setAttribute("aria-busy", "true");
      btn.replaceChildren(loaderArt("bananas")!, h("span", {}, busyText ?? btn.textContent ?? ""));
    },
  });
  if (shown) { btn.replaceChildren(...label); btn.classList.remove("m-btn-loading"); btn.removeAttribute("aria-busy"); }
  btn.disabled = false;
  if (res.failed) throw res.error;
  return res.value as T;
}

/** A compact loader for a state that lasts and gets redrawn (a task that is planning): its words follow how long it
 *  has been going, so a redraw doesn't start the messages over. */
export function loadingSince(o: LoadOpts<any>, since: number, at = realClock.now()): HTMLElement {
  const el = loadingBox({ ...o, compact: o.compact ?? true });
  const step = LOAD.steps.filter((ms) => at - since >= ms).length;
  if (step) { el.querySelector(".m-load-msg")!.textContent = loadMessage(o.what, step, o.msgs); el.dataset.step = String(step); }
  return el;
}
/** ms until the words of a loadingSince() change next (null: they won't). */
export function nextStepIn(since: number, at = realClock.now()): number | null {
  const next = LOAD.steps.find((ms) => at - since < ms);
  return next == null ? null : next - (at - since);
}

/** A dialog frame shown while its content loads (Tasks, Mailing lists, Brain): its title, ✕ and the loader's spot. */
export function dialogShell(dlg: HTMLDialogElement, title: string): HTMLElement {
  const host = h("div", { class: "m-shell-body" });
  dlg.replaceChildren(h("div", { class: "taskstop" }, h("h3", {}, title),
    h("button", { type: "button", class: "ghost mini", "aria-label": "Close", onclick: () => dlg.close() }, "✕")), host);
  dlg.dataset.shell = "1";
  if (!dlg.open) dlg.showModal();
  return host;
}
/** After a load that may have shown a dialogShell: false when the owner closed it meanwhile (then it stays closed). */
export function shellKept(dlg: HTMLDialogElement): boolean {
  const shown = dlg.dataset.shell === "1";
  delete dlg.dataset.shell;
  return !shown || dlg.open;
}

// Pause the loaders while the window is hidden (motion.ts pauses running animations; this also covers one that
// starts while hidden).
if (typeof document !== "undefined") {
  const sync = () => document.documentElement.toggleAttribute("data-m-hidden", document.hidden);
  document.addEventListener("visibilitychange", sync);
  sync();
}

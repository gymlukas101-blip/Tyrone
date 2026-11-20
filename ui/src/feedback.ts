// Visual feedback for moments that otherwise only make a sound, so everything still reads with the sound off.
//
// One small vocabulary, used sparingly:
//   pop    a badge that springs up above Monkey's head and fades (what just happened, in a glyph and 1–3 words)
//   flash  a soft glow around the stage edge (error = red, warning = amber, good = green)
//   shake  a short horizontal shake (error, "stop")
//   pulse  the status label bumps once (a state change you might miss, like "Got it…")
// With "reduce motion" on, pops and flashes fade in and out without scaling or shaking: still visible, never jumpy.
import { h } from "./dom";

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
let lastPop = "";
let lastPopAt = 0;

export function pop(text: string, kind: "info" | "good" | "warn" | "bad" = "info", ms = 1400) {
  const stage = document.getElementById("stage");
  if (!stage) return;
  const now = performance.now();
  if (text === lastPop && now - lastPopAt < 800) return;      // the same moment twice in a row: once is enough
  lastPop = text; lastPopAt = now;
  stage.querySelectorAll(".fbpop").forEach((e) => e.remove());   // one at a time, newest wins
  const el = h("div", { class: `fbpop ${kind}${reduced() ? " still" : ""}`, role: "status", "aria-live": "polite" }, text);
  stage.append(el);
  setTimeout(() => el.classList.add("out"), ms);
  setTimeout(() => el.remove(), ms + 400);
}

export function flash(kind: "good" | "warn" | "bad") {
  const stage = document.getElementById("stage");
  if (!stage) return;
  stage.classList.remove("fbflash-good", "fbflash-warn", "fbflash-bad");
  void stage.offsetWidth;                                         // restart the animation
  stage.classList.add(`fbflash-${kind}`);
  setTimeout(() => stage.classList.remove(`fbflash-${kind}`), 900);
}

export function shake(target: HTMLElement | null) {
  if (!target || reduced()) return;
  target.classList.remove("fbshake");
  void target.offsetWidth;
  target.classList.add("fbshake");
  setTimeout(() => target.classList.remove("fbshake"), 450);
}

export function pulse(target: HTMLElement | null) {
  if (!target) return;
  target.classList.remove("fbpulse");
  void target.offsetWidth;
  target.classList.add("fbpulse");
  setTimeout(() => target.classList.remove("fbpulse"), 500);
}

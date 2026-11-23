// Toy-block 3D icons and background for the to-do panel (docs/ui/BLOCKY_ICONS.md).
// A visual layer over todo.ts: it decorates the panel after each draw and never changes what the panel does.
// Icons come from the shared baked sheets (blocky/skin.ts). Nothing animates at rest except an occasional hop of the
// empty-state hero (full Juice only). Without the sheets (no WebGL, software GL, bake failed) the panel is unchanged.
import { baked, ensureBaked, glyph, go, heroIcon, icon, juice, motionOK, release, wireHoverPress } from "./blocky/skin";

export function decorate(card: HTMLElement) {
  if (!baked) { void ensureBaked(() => document.querySelectorAll<HTMLElement>(".card.todo").forEach((c) => decorate(c))); return; }
  if (!card.classList.contains("blocky")) {
    // The background is static on purpose: pointer parallax re-rasterized two panel-sized layers on every move
    // (measured: +60% long frames while hovering in software rendering). The gallery keeps it as a prototype.
    card.classList.add("blocky");
    const bg = document.createElement("div");
    bg.className = "bk-bg";
    bg.setAttribute("aria-hidden", "true");
    bg.append(document.createElement("i"), document.createElement("i"));
    card.prepend(bg);
    wireHoverPress(card);
    wireCheck(card);
    ambient(card);
  }
  const title = card.querySelector(".cardtitle");
  if (title && !title.querySelector(".bi")) { title.textContent = (title.textContent ?? "").replace(/^\p{Extended_Pictographic}️?\s*/u, ""); title.prepend(icon("notepad", "bi-title")); }
  card.querySelectorAll(".cb").forEach((cb) => { if (!cb.querySelector(".bi")) cb.append(icon("box", "cb-ico")); });
  const add = card.querySelector(".todo-add .primary");
  if (add && !add.querySelector(".bi")) add.prepend(icon("add"));
  card.querySelectorAll("button[aria-label^='Edit ']").forEach((b) => glyph(b, "edit"));
  card.querySelectorAll("button[aria-label^='Delete ']").forEach((b) => glyph(b, "trash"));
  card.querySelectorAll(".todo-row .src").forEach((s) => {
    if (s.querySelector(".bi")) return;
    s.setAttribute("role", "img"); s.setAttribute("aria-label", s.getAttribute("title") ?? "");
    glyph(s, s.textContent?.includes("🎙") ? "mic" : "monkey");
  });
  card.querySelectorAll(".todo-row:not(.is-done) .asg-why").forEach((w) => {
    if (w.querySelector(".bi") || w.textContent?.startsWith("no due date")) return;
    w.prepend(icon(w.closest(".overdue") ? "alarm" : "calendar", "bi-due"));
  });
  const empty = card.querySelector("p.empty");
  if (empty && !empty.querySelector(".bi")) {
    const t = empty.textContent ?? "";
    empty.prepend(heroIcon(/overdue/i.test(t) ? "lock" : /checked off/i.test(t) ? "box" : "banana"));
  }
}

/** The "done!" pop. Runs after todo.ts's own click handler (bubbling), so `.on` already says the new state. */
function wireCheck(card: HTMLElement) {
  card.addEventListener("click", (e) => {
    const cb = (e.target as Element).closest?.(".cb");
    const i = cb?.querySelector<HTMLElement>(".cb-ico");
    if (!cb || !i) return;
    release(i);
    if (cb.classList.contains("on") && motionOK()) {
      cb.classList.remove("cb-pop"); void cb.clientWidth; cb.classList.add("cb-pop");
      go(i, "pop", "checkedPop");
    }
  });
}

/** Full Juice only: every 8–12 s the empty-state hero (or the Add icon) does one hop, while the panel is open,
 *  unfolded and the window visible. A timer, not an animation loop: nothing runs in between. */
function ambient(card: HTMLElement) {
  const next = () => setTimeout(() => {
    if (!document.body.contains(card)) return;
    if (!document.hidden && juice() === "full" && motionOK() && !card.classList.contains("folded")) {
      go(card.querySelector<HTMLElement>("p.empty .bi") ?? card.querySelector<HTMLElement>(".todo-add .primary .bi"), "hover");
    }
    next();
  }, 8000 + Math.random() * 4000);
  next();
}

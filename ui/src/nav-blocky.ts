// Toy-block 3D icons for the header buttons and the composer's mic (docs/ui/BLOCKY_ICONS.md). Visual layer only: the
// glyph text is swapped for a baked sprite once the sheets exist; labels, titles and handlers are untouched.
// A cached bake applies at start-up; a first bake waits for an idle moment a few seconds after start so it never
// competes with the avatar's own start-up work.
import { ensureBaked, glyph, icon, wireHoverPress } from "./blocky/skin";

const HEADER: Record<string, string> = {
  labBtn: "flask", todayBtn: "sun", asgBtn: "checkBadge", todoBtn: "notepad", tasksBtn: "hand", healthBtn: "heart",
  newChat: "newChat", settingsBtn: "gear",
};

function apply() {
  for (const [id, recipe] of Object.entries(HEADER)) {
    const b = document.getElementById(id);
    if (!b || b.querySelector(":scope > .bi")) continue;
    const t = [...b.childNodes].find((n) => n.nodeType === Node.TEXT_NODE && n.textContent?.trim());
    if (!t) continue;
    t.replaceWith(icon(recipe, "bi-nav"));
  }
  const mic = document.getElementById("mic");
  if (mic) { glyph(mic, "mic"); mic.querySelector(".bi")?.classList.add("bi-mic"); }
  const header = document.querySelector<HTMLElement>("#side > header");
  if (header && !header.dataset.bi) { header.dataset.bi = "1"; wireHoverPress(header); }
  const composer = document.getElementById("composer");
  if (composer && !composer.dataset.bi) { composer.dataset.bi = "1"; wireHoverPress(composer, "#mic"); }
}

export function initNavIcons() {
  let cached = false;
  try { cached = Object.keys(localStorage).some((k) => k.startsWith("monkey.blocky.")); } catch { /* storage blocked */ }
  const start = () => void ensureBaked(apply);
  if (cached) start();
  else setTimeout(() => (typeof requestIdleCallback === "function" ? requestIdleCallback(start, { timeout: 4000 }) : start()), 3000);
}

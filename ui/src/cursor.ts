// Settings → Look & mic → Animated banana cursor: options + a live preview that needs no computer-control permission.
// The preview runs the exact controller Monkey injects into his browser (monkey/automation/cursor/banana_cursor.js).
import "../../monkey/automation/cursor/banana_cursor.js";
import svg from "../../monkey/automation/cursor/banana.svg?raw";
import manifestText from "../../monkey/automation/cursor/manifest.json?raw";
import type { Api } from "./bridge";
import { h, toast } from "./dom";

const manifest = JSON.parse(manifestText) as { hotspot: [number, number] };
type Ctl = { configure(c: Record<string, unknown>): void; moveTo(x: number, y: number, o?: object): number; hover(role: string): boolean;
  press(): number; release(): number; setState(s: string, label?: string): void; hide(): void; dragTo(x: number, y: number): number; endDrag(): void };
const lib = () => (window as any).MonkeyBananaCursor as { create(o: object): Ctl };

export function cursorSettings(api: Api, s: Record<string, any>): HTMLElement {
  const stage = h("div", { class: "cursorstage", "aria-label": "Banana cursor preview" });
  const btn = h("span", { class: "cs-btn" }, "Save draft");
  const link = h("span", { class: "cs-link" }, "Read more");
  const text = h("span", { class: "cs-text" }, "plain text");
  const drop = h("span", { class: "cs-drop" }, "drop here");
  stage.append(btn, link, text, drop);
  const fxHost = h("div", { class: "cs-layer" });
  stage.append(fxHost);
  let c: Ctl | null = null;
  const conf = () => ({ scale: Number(s.cursor_scale ?? 1), glow: Number(s.cursor_glow ?? 0.7), motion: s.cursor_motion ?? "auto",
    clickFx: s.cursor_click_fx !== false, busyFx: s.cursor_busy_fx !== false });
  const ensure = () => { if (!c) { c = lib().create({ host: fxHost, svg, hotspot: manifest.hotspot }); c.configure(conf()); c.moveTo(24, 26); } return c; };
  const centre = (el: HTMLElement) => { const r = el.getBoundingClientRect(), b = stage.getBoundingClientRect();
    return [r.left - b.left + r.width / 2, r.top - b.top + r.height / 2] as const; };
  const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
  let busy = false;
  const demo = async () => {                      // what a real click looks like: travel, hover, press, ripple, busy
    if (busy) return; busy = true;
    const k = ensure(); k.setState("idle"); k.hover("");
    const [x, y] = centre(btn); await wait(k.moveTo(x, y) + 40);
    k.hover("button"); await wait(220);
    await wait(k.press()); k.release(); btn.classList.add("pressed"); setTimeout(() => btn.classList.remove("pressed"), 160);
    k.setState("busy"); await wait(1300); k.setState("idle");
    const [tx, ty] = centre(text); await wait(k.moveTo(tx, ty) + 200);
    k.hover("generic");                           // plain text: no glow (not interactive)
    busy = false;
  };
  const stateBtn = (label: string, fn: (k: Ctl) => void | Promise<void>) =>
    h("button", { type: "button", class: "ghost mini", onclick: () => void fn(ensure()) }, label);
  const controls = h("div", { class: "row cs-ctl" },
    stateBtn("▶ Play the demo", () => demo()),
    stateBtn("Default", (k) => { k.setState("idle"); k.hover(""); }),
    stateBtn("Hover", (k) => { const [x, y] = centre(link); k.moveTo(x, y); setTimeout(() => k.hover("link"), 200); }),
    stateBtn("Click", async (k) => { await wait(k.press()); k.release(); }),
    stateBtn("Double-click", async (k) => { for (let i = 0; i < 2; i++) { await wait(k.press()); k.release(); await wait(70); } }),
    stateBtn("Busy", (k) => k.setState("busy")),
    stateBtn("Drag", async (k) => { const [x, y] = centre(drop); await wait(k.dragTo(x, y) + 60); k.endDrag(); k.release(); }),
    stateBtn("Thinking", (k) => k.setState("thinking")),
    stateBtn("Your turn", (k) => k.setState("waiting")),
    stateBtn("Paused", (k) => k.setState("paused")),
    stateBtn("Error", (k) => { k.setState("error"); setTimeout(() => k.setState("idle"), 1400); }),
    stateBtn("Success", (k) => k.setState("success")));
  const save = async (changes: Record<string, any>) => { Object.assign(s, changes); await api.save_settings(changes); c?.configure(conf()); };
  const mode = h("select", {}, h("option", { value: "control" }, "On while Monkey controls something (recommended)"),
    h("option", { value: "off" }, "Off")) as HTMLSelectElement;
  mode.value = s.cursor_mode ?? "control";
  mode.addEventListener("change", () => { void save({ cursor_mode: mode.value }); toast("Saved"); });
  const range = (key: string, min: number, max: number, step: number, label: string) => {
    const inp = h("input", { type: "range", min, max, step, value: String(s[key] ?? (key === "cursor_scale" ? 1 : 0.7)) }) as HTMLInputElement;
    inp.addEventListener("input", () => void save({ [key]: Number(inp.value) }));
    return h("label", { class: "field" }, h("span", {}, label), inp);
  };
  const motion = h("select", {}, h("option", { value: "auto" }, "Follow Windows animation settings"), h("option", { value: "full" }, "Full"),
    h("option", { value: "reduced" }, "Reduced (no flying, no ripples)")) as HTMLSelectElement;
  motion.value = s.cursor_motion ?? "auto";
  motion.addEventListener("change", () => void save({ cursor_motion: motion.value }));
  const tick = (key: string, label: string) => {
    const cb = h("input", { type: "checkbox", checked: s[key] !== false }) as HTMLInputElement;
    cb.addEventListener("change", () => void save({ [key]: cb.checked }));
    return h("label", { class: "field toggle" }, cb, h("span", {}, label));
  };
  return h("div", { class: "cursorsettings", id: "cursorSettings" },
    h("h5", {}, "🍌 Animated banana cursor"),
    h("p", { class: "help" }, "When Monkey clicks in his own browser, a banana pointer shows exactly where, so you can follow along. " +
      "It's only a picture: your own mouse is never replaced, and Stop / Pause still work the same."),
    h("label", { class: "field" }, h("span", {}, "Show it"), mode),
    range("cursor_scale", 0.75, 1.6, 0.05, "Size"), range("cursor_glow", 0, 1, 0.05, "Glow"),
    h("label", { class: "field" }, h("span", {}, "Animation"), motion),
    tick("cursor_click_fx", "Click ripples"), tick("cursor_busy_fx", "Loading ring while a page loads"),
    stage, controls);
}

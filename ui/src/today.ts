// The Today view: one place for "what should I do now", built only from real data Monkey already has.
//
// Tabs: Focus (the top item with why it's first, plus next due / schedule / unread / weather tiles), Homework (the
// full checklist), Schedule (today's classes and events). No XP, levels or made-up rows: a section with nothing to
// show says why (not connected, nothing due, not loaded yet). Drawing it makes no network calls: dashboard() reads
// the cached brief and the cached assignment board.
import { renderAssignments } from "./assignments";
import { countdown, h, toast } from "./dom";
import { pop } from "./motion";
import { loadInto, skeleton } from "./loader";
import { closeTo, openFrom } from "./menu-motion";

type Sec = { status: string; items: any[]; note: string };
export interface Dash { ok: boolean; sections: Record<string, Sec>; stats?: Record<string, number>; brief_day?: string | null }
interface TodayApi {
  dashboard(): Promise<Dash>;
  get_assignments(refresh: boolean): Promise<any>;
  toggle_assignment(id: string, done: boolean): Promise<{ ok: boolean; synced?: boolean; error?: string }>;
  open_url(url: string): Promise<any> | void;
}

const TABS = [["focus", "Focus"], ["homework", "Homework"], ["schedule", "Schedule"]] as const;
type Tab = typeof TABS[number][0];
let api: TodayApi;
let root: HTMLElement | null = null;
let tab: Tab = "focus";
export let lastDrawMs = 0;                       // first draw time (checked by the UI tests)

const WHY: Record<string, string> = {
  not_connected: "Not connected", unavailable: "Not available right now", empty: "Nothing here", expired: "Sign-in expired",
  loading: "Loading…",
};
let drawSeq = 0;                                 // only the latest draw may write to the panel

function statusLine(s: Sec | undefined) {
  if (!s) return h("p", { class: "meta" }, "Not loaded yet.");
  if (s.status === "ok" && s.items.length) return null;
  const line = h("p", { class: `meta status-${s.status}` }, s.note || WHY[s.status] || s.status);
  // still coming in: a small shimmering skeleton of the tile's rows under the words (gone once it's loaded)
  return s.status === "loading" ? h("div", { class: "tile-loading" }, line, skeleton("tile")) : line;
}

function tile(title: string, s: Sec | undefined, body: () => HTMLElement | null) {
  return h("section", { class: `ttile ${s?.status ?? "unavailable"}`, "aria-label": title },
    h("h4", {}, title), statusLine(s) ?? body());
}

function list(items: string[]) {
  return h("ul", { class: "items" }, ...items.map((i) => h("li", {}, i)));
}

function focusPanel(d: Dash) {
  const f = d.sections.focus;
  const it = f?.items?.[0];
  const hero = h("section", { class: "focushero", "aria-label": "Your focus" },
    h("div", { class: "focuslabel" }, "Do this first"));
  if (!it) {
    hero.append(statusLine(f) ?? h("p", { class: "meta" }, "Nothing due."));
  } else {
    const done = h("div", { class: "focusactions" });
    const markBtn = h("button", { class: "primary", type: "button" }, "✓ Mark done in Monkey") as HTMLButtonElement;
    markBtn.title = "Ticks it off your list. It never submits anything; with a Canvas token it also ticks Canvas's planner.";
    markBtn.onclick = async () => {
      markBtn.disabled = true;
      const r = await api.toggle_assignment(it.id, true);
      if (!r.ok) { markBtn.disabled = false; toast(`⚠ ${r.error ?? "Couldn't mark it"}`); return; }
      hero.classList.add("is-done");
      const where = r.synced ? "Marked done in Monkey and on your Canvas planner." : "Marked done in Monkey.";
      const undo = h("button", { class: "ghost", type: "button" }, "Undo") as HTMLButtonElement;
      undo.onclick = async () => {
        const u = await api.toggle_assignment(it.id, false);
        if (u.ok) { hero.classList.remove("is-done"); void draw(); } else toast(`⚠ ${u.error ?? "Couldn't undo"}`);
      };
      done.replaceChildren(h("span", { class: "donemsg", role: "status" }, where), undo);
      undo.focus();                               // keyboard focus stays on the card, not lost with the old button
      setTimeout(() => { if (done.isConnected && hero.classList.contains("is-done")) void draw(); }, 10000);   // undo window
    };
    done.append(markBtn);
    if (it.url) done.append(h("button", { class: "ghost", type: "button", onclick: () => api.open_url(it.url) }, "Open on Canvas"));
    hero.append(
      h("div", { class: "focustitle" }, it.title),
      h("div", { class: "focusmeta" }, [it.course, it.due ? countdown(it.due) : "no due date"].filter(Boolean).join(" · ")),
      it.reason ? h("p", { class: "focuswhy" }, `Why first: ${it.reason}`) : "",
      done);
  }
  const due = d.sections.due;
  return h("div", { class: "focuspanel" }, hero,
    h("div", { class: "ttiles" },
      tile("Next due", due, () => due.items.length
        ? list(due.items.map((x: any) => `${x.title} (${x.course})${x.due ? ` · ${countdown(x.due)}` : ""}`))
        : h("p", { class: "meta" }, "Nothing else due soon.")),
      tile("Today", d.sections.schedule, () => list(d.sections.schedule.items)),
      tile("Unread email", d.sections.unread, () => list(d.sections.unread.items)),
      tile("Weather", d.sections.weather, () => list(d.sections.weather.items))));
}

async function homeworkPanel() {
  const box = h("div", { class: "card homework" });
  const r = await api.get_assignments(false);
  if (!r.ok) { box.append(h("p", { class: "meta" }, r.error ?? "Couldn't load assignments.")); return box; }
  renderAssignments(box, r, (id, done) => api.toggle_assignment(id, done), (u) => void api.open_url(u));
  return box;
}

function schedulePanel(d: Dash) {
  const s = d.sections.schedule;
  return h("div", { class: "ttiles one" }, tile("Today", s, () =>
    h("div", {}, list(s.items), s.note ? h("p", { class: "meta" }, s.note) : "")));
}

async function draw(attempt = 0) {
  if (!root) return;
  const seq = ++drawSeq;
  const t0 = performance.now();
  const panel = root.querySelector<HTMLElement>("#todayPanel")!;
  let content: HTMLElement;
  let d: Dash | null = null;
  const which = tab;
  // Slow (over 150 ms) first draw of a tab: a skeleton in the tab's real layout, words that change if it's slow, an
  // error with Try again; background reloads (attempt > 0) stay quiet.
  const got = await loadInto(() => {
    if (attempt > 0 || seq !== drawSeq || !root) return null;
    panel.replaceChildren();
    return panel;
  }, async () => {
    d = await api.dashboard();
    return which === "focus" ? focusPanel(d) : which === "schedule" ? schedulePanel(d) : await homeworkPanel();
  }, { what: which === "focus" ? "your day" : which === "schedule" ? "your calendar" : "your homework",
       skel: which === "focus" ? "tiles" : which === "schedule" ? "rows" : "list", art: which === "focus" ? "monkey" : "bananas",
       failed: () => null });
  content = got.value;
  if (seq !== drawSeq || !root) return;          // a newer tab/draw started meanwhile: don't overwrite it
  panel.setAttribute("aria-labelledby", `todayTab-${tab}`);
  panel.classList.toggle("m-quiet", attempt > 0);  // a background reload doesn't replay the entrance
  panel.replaceChildren(content);
  lastDrawMs = performance.now() - t0;
  if ((d as any)?.loading && attempt < 10) setTimeout(() => { if (seq === drawSeq && !root!.hidden) void draw(attempt + 1); }, 1500);
  if ((window as any).__todayDrawMs === undefined) (window as any).__todayDrawMs = lastDrawMs;
}

function select(next: Tab, focus = false) {
  // The new tab's content slides in from the side the tab is on (motion.css: #todayPanel[data-m-dir]).
  const from = TABS.findIndex(([id]) => id === tab), to = TABS.findIndex(([id]) => id === next);
  root!.querySelector<HTMLElement>("#todayPanel")!.dataset.mDir = to > from ? "right" : to < from ? "left" : "";
  tab = next;
  root!.querySelectorAll<HTMLButtonElement>("[role=tab]").forEach((b) => {
    const on = b.dataset.tab === tab;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
    if (on && focus) b.focus();
    if (on && from !== to) pop(b, 0.7);
  });
  void draw();
}

/** Build the view (hidden) inside the side panel. */
export function initToday(a: TodayApi, host: HTMLElement, before: Element) {
  api = a;
  const tabs = h("div", { class: "todaytabs", role: "tablist", "aria-label": "Today" },
    ...TABS.map(([id, label]) => h("button", { type: "button", role: "tab", id: `todayTab-${id}`, "data-tab": id,
      "aria-controls": "todayPanel", "aria-selected": String(id === tab), tabindex: id === tab ? "0" : "-1",
      onclick: () => select(id) }, label)));
  tabs.addEventListener("keydown", (e) => {
    const k = (e as KeyboardEvent).key;
    const i = TABS.findIndex(([id]) => id === tab);
    const n = k === "ArrowRight" ? i + 1 : k === "ArrowLeft" ? i - 1 : k === "Home" ? 0 : k === "End" ? TABS.length - 1 : null;
    if (n === null || !(e.target as HTMLElement).matches("[role=tab]")) return;
    e.preventDefault();
    select(TABS[(n + TABS.length) % TABS.length][0], true);
  });
  const close = h("button", { type: "button", class: "ghost mini todayclose", title: "Back to the chat",
    onclick: () => toggleToday(false) }, "✕ Chat");
  root = h("section", { id: "today", "aria-label": "Today", hidden: true },
    h("div", { class: "todaybar" }, tabs, close), h("div", { id: "todayPanel", role: "tabpanel", tabindex: "0" }));
  host.insertBefore(root, before);
}

export function toggleToday(open?: boolean, returnFocus = true) {
  if (!root) return;
  // the logical state is the button's (a closing view is still on screen for ~140 ms but already "closed")
  const isOpen = document.getElementById("todayBtn") ? btnPressed() : !root.hidden;
  const show = open ?? !isOpen;
  if (show === isOpen) return;
  const btn = document.getElementById("todayBtn");
  btn?.setAttribute("aria-pressed", String(show));
  if (show) {
    // opening (or reopening mid-close): the pane rises in, the selected tab bounces; contents follow per tab
    root.hidden = false;
    document.body.classList.add("today-open");
    openFrom(root, btn, "below");          // a full-pane view: rises in (scaling the whole pane cost a long task on software GL)
    select(tab, true);
    return;
  }
  // closing: sinks away, faster than it came, then hides; the chat comes back when it's gone
  if (returnFocus) btn?.focus();
  const el = root;
  closeTo(el, () => {
    if (btn?.getAttribute("aria-pressed") === "true") return;        // reopened meanwhile
    el.hidden = true;
    document.body.classList.remove("today-open");
  }, "below");                                                       // sinks away (translate + fade)
}

export function todayOpen() { return !!root && !root.hidden && btnPressed(); }
const btnPressed = () => document.getElementById("todayBtn")?.getAttribute("aria-pressed") === "true";

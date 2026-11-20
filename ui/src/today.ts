// The Today view: one place for "what should I do now", built only from real data Monkey already has.
//
// Tabs: Focus (the top item with why it's first, plus next due / schedule / unread / weather tiles), Homework (the
// full checklist), Schedule (today's classes and events). No XP, levels or made-up rows: a section with nothing to
// show says why (not connected, nothing due, not loaded yet). Drawing it makes no network calls: dashboard() reads
// the cached brief and the cached assignment board.
import { renderAssignments } from "./assignments";
import { countdown, h, toast } from "./dom";

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
};

function statusLine(s: Sec | undefined) {
  if (!s) return h("p", { class: "meta" }, "Not loaded yet.");
  if (s.status === "ok" && s.items.length) return null;
  return h("p", { class: `meta status-${s.status}` }, s.note || WHY[s.status] || s.status);
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
    markBtn.title = "Ticks it off in Monkey only. It doesn't submit anything on Canvas.";
    markBtn.onclick = async () => {
      markBtn.disabled = true;
      const r = await api.toggle_assignment(it.id, true);
      if (!r.ok) { markBtn.disabled = false; toast(`⚠ ${r.error ?? "Couldn't mark it"}`); return; }
      hero.classList.add("is-done");
      const undo = h("button", { class: "ghost", type: "button" }, "Undo") as HTMLButtonElement;
      undo.onclick = async () => {
        const u = await api.toggle_assignment(it.id, false);
        if (u.ok) { hero.classList.remove("is-done"); void draw(); } else toast(`⚠ ${u.error ?? "Couldn't undo"}`);
      };
      done.replaceChildren(h("span", { class: "donemsg", role: "status" }, "Marked done in Monkey."), undo);
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

async function draw() {
  if (!root) return;
  const t0 = performance.now();
  const d = await api.dashboard();
  const panel = root.querySelector<HTMLElement>("#todayPanel")!;
  panel.setAttribute("aria-labelledby", `todayTab-${tab}`);
  panel.replaceChildren(tab === "focus" ? focusPanel(d) : tab === "schedule" ? schedulePanel(d) : await homeworkPanel());
  lastDrawMs = performance.now() - t0;
  if ((window as any).__todayDrawMs === undefined) (window as any).__todayDrawMs = lastDrawMs;
}

function select(next: Tab, focus = false) {
  tab = next;
  root!.querySelectorAll<HTMLButtonElement>("[role=tab]").forEach((b) => {
    const on = b.dataset.tab === tab;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
    if (on && focus) b.focus();
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

export function toggleToday(open?: boolean) {
  if (!root) return;
  const show = open ?? root.hidden;
  root.hidden = !show;
  document.body.classList.toggle("today-open", show);
  document.getElementById("todayBtn")?.setAttribute("aria-pressed", String(show));
  if (show) select(tab, true);
}

// Phone screen time: the phone card at the top of the To-do panel (today vs goal, last 7 days, top apps, goal
// to-dos, a gentle suggestion, manual entry) and the Settings → Phone section (turn on, pick the phone, setup steps,
// pairing QR, status, import, Forget data). Self-contained: main.ts only mounts these and forwards events.
// Python side: monkey/integrations/screentime.py. Off by default; nothing is read until the owner turns it on.
import type { Api } from "./bridge";
import { loadInto } from "./loader";
import { h, toast } from "./dom";
import { qrSvg } from "./reminders";      // qrcode-generator, drawn locally
import "./screentime.css";

export interface StApp { name: string; minutes: number }
export interface StDay {
  day: string; total_min: number; pickups: number | null; apps: StApp[]; device: string; platform: string;
  source: string; received: number | null; estimated: boolean;
}
export interface StGoal {
  id: string; todo_id: string; kind: "total" | "app" | "group"; app: string; apps?: string[]; label?: string;
  limit_min: number; day: string; repeat: boolean; status: string; used_min: number | null; text: string;
}
/** The offered "Social: TikTok, Instagram, YouTube ≤ 3h" group (never created until the owner clicks). */
export interface StGroupSuggestion { label: string; apps: string[]; limit_min: number; text: string; todo_text: string; used_min: number | null }
export interface StStatus {
  enabled: boolean; platform: "" | "iphone" | "android"; transport: "folder" | "ntfy" | "manual"; folder: string;
  folder_exists: boolean; paired: boolean; server: string; topic: string; last_received: { ts: number; source: string } | null;
  last_error: string; days: number; goal_min: number; keep_days: number; in_brief: boolean; nudges: boolean;
}
export interface StSuggestion { text: string; total_min: number; goal_min: number; todo: { id: string; text: string } }
export interface StPanel {
  enabled: boolean; goal_min?: number; today?: StDay | null; yesterday?: StDay | null;
  week?: { day: string; total_min: number }[]; goals?: StGoal[]; suggestion?: StSuggestion | null;
  suggested_group?: StGroupSuggestion | null; status?: StStatus;
}
export interface StState {
  ok: boolean; error?: string; status?: StStatus; panel?: StPanel; steps?: string[]; pair_uri?: string;
  tasker_js?: string; cryptojs_url?: string; check?: { ok: boolean; read?: number; error?: string; errors?: string[]; note?: string };
}
type Res = { ok: boolean; error?: string; panel?: StPanel; days?: number; saved?: number };
export interface ScreenTimeApi {
  screentime_state(): Promise<StState>;
  screentime_pair(): Promise<StState>;
  screentime_unpair(): Promise<StState>;
  screentime_check(): Promise<StState>;
  screentime_manual(total: string, day: string, pickups: string | null, top_app: string, top_app_time: string): Promise<Res>;
  screentime_import(text: string, filename: string): Promise<Res>;
  screentime_add_goal(kind: string, limit: string, app: string, repeat: boolean, label: string): Promise<Res>;
  screentime_group_suggestion(accept: boolean): Promise<Res>;
  screentime_stop_goal(id: string): Promise<Res>;
  screentime_forget(): Promise<StState>;
}
interface Hooks { openSettings: () => void; ask: (text: string) => void }

export const fmtMin = (m: number | null | undefined) => {
  if (m === null || m === undefined) return "?";
  const v = Math.max(0, Math.round(m)), hh = Math.floor(v / 60), mm = v % 60;
  return hh && mm ? `${hh}h ${mm}m` : hh ? `${hh}h` : `${mm}m`;
};
const timeOf = (ts: number | null | undefined) =>
  ts ? new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
const isoToday = () => { const d = new Date(), p = (n: number) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; };
const weekday = (iso: string) => new Date(iso + "T12:00").toLocaleDateString([], { weekday: "short" });

// ------------------------------------------------------------------ the phone card in the To-do panel
let mounted: { card: HTMLElement; api: Api; hooks: Hooks; box: HTMLElement } | null = null;

/** Put the phone card at the top of the To-do panel (above the to-do list). */
export function mountPhoneCard(todoCard: HTMLElement, api: Api, hooks: Hooks) {
  todoCard.querySelectorAll(".st-card").forEach((n) => n.remove());
  const box = h("section", { class: "st-card", "aria-label": "Phone screen time" });
  const body = todoCard.querySelector(".todo-body");
  if (body) body.before(box); else todoCard.append(box);
  mounted = { card: todoCard, api, hooks, box };
  void refreshPhoneCard();
}

export async function refreshPhoneCard(panel?: StPanel) {
  if (!mounted || !document.body.contains(mounted.box)) return;
  if (!panel) {
    const m = mounted;
    const first = !m.box.childElementCount;          // first fill: a small skeleton if it's slow (loader.ts)
    const r = first ? (await loadInto(() => m.box, () => m.api.screentime_state(),
      { what: "your screen time", skel: "block", rows: 2, art: "bananas", failed: () => null })).value
      : await m.api.screentime_state();
    if (!r.ok || !r.panel) return;
    panel = r.panel;
  }
  drawCard(panel);
}

function meter(total: number, goal: number, label = "Phone time today vs your goal") {
  const over = goal > 0 && total > goal;
  const pct = goal > 0 ? Math.min(100, (total / goal) * 100) : 0;
  const bar = h("div", { class: `st-meter ${over ? "over" : ""}`, role: "meter", "aria-label": label,
    "aria-valuemin": "0", "aria-valuemax": String(goal), "aria-valuenow": String(Math.min(total, goal)),
    "aria-valuetext": `${fmtMin(total)} of ${fmtMin(goal)}` });
  bar.append(h("span", { class: "st-fill" }));
  (bar.firstElementChild as HTMLElement).style.width = `${pct}%`;
  return bar;
}

function weekBars(week: { day: string; total_min: number }[], goal: number) {
  const days = [...week].reverse().slice(-7);
  const max = Math.max(goal, ...days.map((d) => d.total_min), 60);
  const label = "Last 7 days: " + days.map((d) => `${weekday(d.day)} ${fmtMin(d.total_min)}`).join(", ")
    + (goal ? `. Goal ${fmtMin(goal)}.` : ".");
  const plot = h("div", { class: "st-plot" });
  const names = h("div", { class: "st-days" });
  for (const d of days) {
    const bar = h("span", { class: `st-bar ${d.day === isoToday() ? "today" : ""}`, title: `${weekday(d.day)} ${d.day}: ${fmtMin(d.total_min)}` });
    bar.style.height = `${Math.max(4, (d.total_min / max) * 100)}%`;
    plot.append(bar);
    names.append(h("span", {}, weekday(d.day).slice(0, 2)));
  }
  if (goal > 0) {
    const line = h("span", { class: "st-goal-line", title: `Goal ${fmtMin(goal)}` });
    line.style.bottom = `${(goal / max) * 100}%`;
    plot.append(line);
  }
  return h("div", { class: "st-week", role: "img", "aria-label": label }, plot, names);
}

function goalRow(g: StGoal, api: Api) {
  const used = g.used_min;
  const state = g.status === "met" ? "✓ made it" : g.status === "missed" ? "⚠ went over" : g.status === "nodata" ? "no data"
    : used === null ? "waiting for data" : used > g.limit_min ? `⚠ over: ${fmtMin(used)}` : `${fmtMin(used)} so far`;
  const group = g.kind === "group" && g.apps?.length
    ? h("div", { class: "st-group" }, h("span", { class: "meta" }, `${g.apps.join(" + ")}: ${used === null ? "?" : fmtMin(used)} of ${fmtMin(g.limit_min)}`),
        used !== null ? meter(used, g.limit_min, `${g.label || "App group"} today vs its goal`) : null)
    : null;
  return h("li", { class: `st-goal ${g.status} ${g.kind}` },
    h("span", {}, "🎯 ", g.text, g.repeat ? h("span", { class: "meta" }, " · every day") : null), h("span", { class: "meta" }, state), group,
    g.repeat ? h("button", { type: "button", class: "ghost mini", title: "Stop making this to-do every day",
      onclick: async () => { const r = await api.screentime_stop_goal(g.id); if (r.ok) { toast("✓ It won't repeat"); void refreshPhoneCard(r.panel); } else toast(`⚠ ${r.error}`); } },
      "Stop repeating") : null);
}

function extras(p: StPanel) {
  const api = mounted!.api;
  const total = h("input", { "aria-label": "Today's phone screen time", placeholder: "e.g. 2h 15m", class: "st-in", autocomplete: "off" });
  const topApp = h("input", { "aria-label": "Top app (optional)", placeholder: "Top app, e.g. Instagram", class: "st-in", autocomplete: "off" });
  const topTime = h("input", { "aria-label": "Time on the top app", placeholder: "45m", class: "st-in short", autocomplete: "off" });
  const manual = h("form", { class: "st-form", onsubmit: async (e: Event) => {
    e.preventDefault();
    if (!total.value.trim()) return;
    const r = await api.screentime_manual(total.value.trim(), "today", null, topApp.value.trim(), topTime.value.trim());
    if (!r.ok) return toast(`⚠ ${r.error}`);
    toast("✓ Saved today's screen time");
    void refreshPhoneCard(r.panel);
  } }, h("label", {}, "Today's total ", total), topApp, topTime, h("button", { type: "submit", class: "ghost mini" }, "Save"));
  const where = h("p", { class: "meta" }, "From the phone: Settings → Screen Time (iPhone) or Digital Wellbeing (Android).");
  const kind = h("select", { "aria-label": "Goal type" }, h("option", { value: "total" }, "Phone under"),
    h("option", { value: "app" }, "App at most"), h("option", { value: "group" }, "Apps together at most"));
  const limit = h("input", { "aria-label": "Limit", placeholder: "2h", class: "st-in short", value: p.goal_min ? fmtMin(p.goal_min) : "" });
  const app = h("input", { "aria-label": "App name", placeholder: "Instagram", class: "st-in", hidden: true });
  const label = h("input", { "aria-label": "Group name", placeholder: "Social", class: "st-in short", hidden: true });
  const repeat = h("input", { type: "checkbox" });
  kind.addEventListener("change", () => {
    app.hidden = kind.value === "total"; label.hidden = kind.value !== "group";
    app.setAttribute("aria-label", kind.value === "group" ? "Apps, separated by commas" : "App name");
    app.placeholder = kind.value === "group" ? "TikTok, Instagram, YouTube" : "Instagram";
    if (kind.value === "app" && !limit.value) limit.value = "30m";
  });
  const goal = h("form", { class: "st-form", onsubmit: async (e: Event) => {
    e.preventDefault();
    const r = await api.screentime_add_goal(kind.value, limit.value.trim(), app.value.trim(), repeat.checked, label.value.trim());
    if (!r.ok) return toast(`⚠ ${r.error}`);
    toast("✓ Goal added to your to-do list");
    void refreshPhoneCard(r.panel);
  } }, kind, limit, label, app, h("label", { class: "meta" }, repeat, " every day"), h("button", { type: "submit", class: "ghost mini" }, "Add goal to-do"));
  return h("details", { class: "st-more", open: p.status?.transport === "manual" && !p.today },
    h("summary", {}, "Type today's total · add a goal to-do"), manual, where, goal, h("p", { class: "meta" }, "Goal to-dos check themselves off after the day if you stayed under, or get flagged if you went over."));
}

function drawCard(p: StPanel) {
  if (!mounted) return;
  const { box, hooks } = mounted;
  if (!p.enabled) {
    box.className = "st-card off";
    box.replaceChildren(h("span", { class: "meta" }, "📱 Phone screen time is off."),
      h("button", { type: "button", class: "ghost mini", onclick: () => hooks.openSettings() }, "Set up"));
    return;
  }
  box.className = "st-card";
  const goal = p.goal_min ?? 0;
  const t = p.today;
  const st = p.status;
  const head = t
    ? h("div", { class: "st-total" }, h("strong", {}, fmtMin(t.total_min)), " on your phone today")
    : h("div", { class: "st-total" }, h("strong", {}, "No data yet"), " for today");
  const facts: string[] = [];
  if (goal && t) {
    const diff = t.total_min - goal;
    facts.push(diff > 0 ? `⚠ ${fmtMin(diff)} over your ${fmtMin(goal)} goal` : `✓ ${fmtMin(-diff)} left of ${fmtMin(goal)}`);
  } else if (goal) facts.push(`Goal ${fmtMin(goal)}`);
  if (t?.pickups != null) facts.push(`${t.pickups} pickups`);
  if (t?.received) facts.push(`updated ${timeOf(t.received)}`);
  else if (!t && p.yesterday) facts.push(`yesterday ${fmtMin(p.yesterday.total_min)}`);
  if (t?.estimated) facts.push("sum of apps");
  const apps = t?.apps?.length
    ? h("div", { class: "st-apps" }, ...t.apps.slice(0, 3).map((a) => h("span", { class: "st-app" }, `${a.name} ${fmtMin(a.minutes)}`)))
    : null;
  const sug = p.suggestion
    ? h("div", { class: "st-suggest", role: "status" }, h("span", {}, "💡 ", p.suggestion.text),
        h("button", { type: "button", class: "ghost mini", onclick: () => hooks.ask(`Help me get this to-do done: "${p.suggestion!.todo.text}"`) }, "🐒 Help me start"))
    : null;
  const warn = st?.last_error ? h("p", { class: "meta st-err" }, `⚠ ${st.last_error}`,
    h("button", { type: "button", class: "ghost mini", onclick: () => hooks.openSettings() }, "Phone settings")) : null;
  const goals = p.goals?.length ? h("ul", { class: "st-goals" }, ...p.goals.map((g) => goalRow(g, mounted!.api))) : null;
  const sg = p.suggested_group;
  const offer = sg ? h("div", { class: "st-offer", role: "group", "aria-label": "Suggested goal" },
    h("span", {}, "🎯 Suggested goal: ", h("strong", {}, sg.text),
      h("span", { class: "meta" }, ` · adds a daily to-do “${sg.todo_text}”` + (sg.used_min !== null ? ` · ${fmtMin(sg.used_min)} so far today` : ""))),
    h("button", { type: "button", class: "ghost mini", onclick: async () => {
      const r = await mounted!.api.screentime_group_suggestion(true);
      if (!r.ok) return toast(`⚠ ${r.error}`);
      toast(`✓ Added: ${sg.todo_text}, every day`);
      void refreshPhoneCard(r.panel);
    } }, "Add daily goal"),
    h("button", { type: "button", class: "ghost mini", onclick: async () => {
      const r = await mounted!.api.screentime_group_suggestion(false);
      if (r.ok) void refreshPhoneCard(r.panel);
    } }, "No thanks")) : null;
  box.replaceChildren(...[
    h("div", { class: "st-top" },
      h("span", { class: "st-icon", "aria-hidden": "true" }, "📱"),
      h("div", { class: "st-main" }, head, goal && t ? meter(t.total_min, goal) : null,
        h("div", { class: "meta st-facts" }, facts.join(" · "))),
      p.week && p.week.length > 1 ? weekBars(p.week, goal) : null),
    apps, sug, goals, offer, warn, extras(p)].filter(Boolean) as Node[]);
}

/** Backend events: "screentime" (new data / forgotten) and "screentime_nudge" (once a day, in-app only). */
export function screenTimeEvent(name: string, p: any) {
  if (name === "screentime_nudge" && p?.text) toast(`💡 ${p.text}`, 9000);
  void refreshPhoneCard();
  void refreshPhoneSettings();
}

// ------------------------------------------------------------------ Settings → Phone
let settingsBox: { sec: HTMLElement; api: Api } | null = null;

/** The Settings section (id set-phone). It loads and redraws itself; Settings doesn't need to re-render. */
export function phoneSettings(api: Api): HTMLElement {
  const sec = h("section", { id: "set-phone" }, h("h4", {}, "Phone screen time"));
  settingsBox = { sec, api };
  void refreshPhoneSettings(true);
  return sec;
}

export async function refreshPhoneSettings(first = false) {
  if (!settingsBox) return;
  const box = settingsBox;
  // the first load gets a skeleton if the app is slow to answer (loader.ts); later refreshes redraw in place
  const r = first ? (await loadInto(() => box.sec, () => box.api.screentime_state(),
    { what: "your phone settings", skel: "block", rows: 3, art: "bananas", failed: () => null })).value
    : await box.api.screentime_state();
  if (!r.ok || !r.status) {
    settingsBox.sec.replaceChildren(h("h4", {}, "Phone screen time"), h("p", { class: "help" }, `⚠ ${r.error ?? "Unavailable"}`));
    return;
  }
  drawSettings(r);
}

function drawSettings(r: StState) {
  if (!settingsBox) return;
  const { sec, api } = settingsBox;
  const st = r.status!;
  const save = async (changes: Record<string, any>, note = "Saved") => {
    await api.save_settings(changes);
    toast(note);
    await refreshPhoneSettings();
    void refreshPhoneCard();
  };
  const toggle = (label: string, key: string, on: boolean) => {
    const cb = h("input", { type: "checkbox", checked: on }) as HTMLInputElement;
    cb.addEventListener("change", () => void save({ [key]: cb.checked }));
    return h("label", { class: "field toggle" }, cb, h("span", {}, label));
  };
  const intro = h("p", { class: "help" },
    "See your phone's screen time next to your to-dos, set a daily goal, and let goal to-dos check themselves off. ",
    "Apple doesn't let any app or PC read an iPhone's Screen Time, so either a Shortcuts automation on the iPhone saves "
    + "a small summary to iCloud Drive for Monkey, or you type today's total and top app in the To-do panel. ",
    "Monkey keeps it only on this PC (monkey.db, the last 30 days by default), and it's off until you turn it on.");
  const parts: (HTMLElement | null)[] = [h("h4", {}, "Phone screen time"), intro,
    toggle("Track my phone's screen time", "screentime_enabled", st.enabled)];
  if (st.enabled) {
    const plat = h("select", { "aria-label": "Your phone" },
      h("option", { value: "iphone" }, "iPhone"), h("option", { value: "android" }, "Android"));
    plat.value = st.platform;
    plat.addEventListener("change", () => void save({ screentime_platform: plat.value, screentime_transport: "" }));
    // An iPhone Shortcut can't encrypt, so the relay is offered for Android only (iCloud Drive is the iPhone's carrier).
    const how = st.platform === "android"
      ? h("select", { "aria-label": "How it gets here" },
          h("option", { value: "ntfy" }, "Encrypted relay (Tasker, recommended)"),
          h("option", { value: "folder" }, "Synced folder (Syncthing)"),
          h("option", { value: "manual" }, "I'll type it in (no setup)"))
      : h("select", { "aria-label": "How it gets here" },
          h("option", { value: "folder" }, "Shortcuts → iCloud Drive (iOS 26+)"),
          h("option", { value: "manual" }, "I'll type it in: total + top app (no setup)"));
    how.value = st.transport;
    how.addEventListener("change", () => void save({ screentime_transport: how.value }));
    const goalIn = h("input", { "aria-label": "Daily goal", placeholder: "e.g. 2h", value: st.goal_min ? fmtMin(st.goal_min) : "", class: "st-in short" });
    const goalSave = () => {
      const v = goalIn.value.trim();
      const m = v ? parseGoal(v) : 0;
      if (m === null) return toast("⚠ Type the goal like 2h or 90m");
      void save({ screentime_goal_min: m }, m ? `Daily goal: ${fmtMin(m)}` : "No daily goal");
    };
    goalIn.addEventListener("change", goalSave);
    parts.push(
      h("div", { class: "field" }, h("span", {}, "Your phone"), plat),
      h("div", { class: "field" }, h("span", {}, "How it gets here"), how),
      h("div", { class: "field" }, h("span", {}, "Daily goal"), goalIn, h("span", { class: "meta" }, "(blank = none)")));
    if (st.transport === "folder") {
      const folder = h("input", { "aria-label": "Folder Monkey reads", value: st.folder, class: "st-in wide" });
      folder.addEventListener("change", () => void save({ screentime_folder: folder.value.trim() }));
      parts.push(h("div", { class: "field" }, h("span", {}, "Folder Monkey reads"), folder,
        h("span", { class: `meta ${st.folder_exists ? "ok" : ""}` }, st.folder_exists ? "✓ found" : "not found yet")));
    }
    if (st.transport === "ntfy") parts.push(pairingBox(r, save));
    if (r.steps?.length && st.platform || st.transport === "manual") {
      parts.push(h("details", { id: "phoneSteps", open: !st.last_received },
        h("summary", {}, st.platform === "iphone" ? "Set up the iPhone (about 5 minutes)" : st.platform === "android" ? "Set up the Android phone (about 10 minutes)" : "How it works"),
        h("ol", { class: "help st-steps" }, ...(r.steps ?? []).map((s) => h("li", {}, s))),
        st.transport === "ntfy" && r.tasker_js ? h("div", { class: "st-script" },
          h("button", { type: "button", class: "ghost mini", onclick: () => copy(r.tasker_js!, "Script copied") }, "Copy script"),
          h("pre", { class: "st-code" }, r.tasker_js)) : null));
    } else if (!st.platform) {
      parts.push(h("p", { class: "help" }, "Pick your phone to see the setup steps."));
    }
    const last = st.last_received ? `Last summary ${new Date(st.last_received.ts * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })} (${st.last_received.source})` : "Nothing received yet";
    const fileIn = h("input", { type: "file", accept: ".json,.csv,.txt", hidden: true }) as HTMLInputElement;
    fileIn.addEventListener("change", async () => {
      const f = fileIn.files?.[0];
      if (!f) return;
      if (f.size > 64 * 1024) return toast("⚠ That file is too big for a screen-time summary");
      const res = await api.screentime_import(await f.text(), f.name);
      toast(res.ok ? `✓ Imported ${res.saved} of ${res.days} day(s)` : `⚠ ${res.error}`, 6000);
      fileIn.value = "";
      await refreshPhoneSettings(); void refreshPhoneCard();
    });
    parts.push(
      h("div", { class: "field" }, h("span", { class: `dot ${st.last_received ? "on" : ""}` }), h("span", { class: "st-status" }, `${last} · ${st.days} day(s) stored, kept ${st.keep_days} days`)),
      st.last_error ? h("p", { class: "keynote bad" }, `⚠ ${st.last_error}`) : null,
      h("div", { class: "field st-btns" },
        st.transport !== "manual" ? h("button", { type: "button", class: "ghost", onclick: async () => {
          const res = await api.screentime_check();
          const c = res.check;
          toast(c?.ok ? `✓ Checked: ${c.read ?? 0} new day(s)${c.errors?.length ? `, ${c.errors.length} skipped` : ""}` : `⚠ ${c?.error ?? res.error}`, 6000);
          await refreshPhoneSettings(); void refreshPhoneCard();
        } }, "Check now") : null,
        h("button", { type: "button", class: "ghost", onclick: () => fileIn.click() }, "Import JSON/CSV…"), fileIn,
        h("button", { type: "button", class: "ghost danger", onclick: async () => {
          if (!confirm("Delete all phone screen-time data Monkey stored? (Your goal to-dos stay.)")) return;
          await api.screentime_forget(); toast("✓ Screen-time data deleted"); await refreshPhoneSettings(); void refreshPhoneCard();
        } }, "Forget data")),
      toggle("Mention yesterday's total in the morning brief", "screentime_in_brief", st.in_brief),
      toggle("Suggest putting the phone down when it's high and important to-dos are open (in the app only)", "screentime_nudges", st.nudges));
  }
  sec.replaceChildren(...parts.filter(Boolean) as HTMLElement[]);
}

function pairingBox(r: StState, save: (c: Record<string, any>, note?: string) => Promise<void>) {
  const { api } = settingsBox!;
  const st = r.status!;
  const box = h("div", { class: "st-pair" });
  const server = h("input", { "aria-label": "Relay address", value: st.server, class: "st-in wide" });
  server.addEventListener("change", () => void save({ screentime_ntfy_server: server.value.trim() }, "Relay saved. Pair the phone again."));
  box.append(h("p", { class: "help" },
    "The phone encrypts each summary with a key only it and this PC have, then posts it to a private topic on a free relay (ntfy). ",
    "Monkey fetches it from there; the relay only ever sees scrambled bytes, and nothing has to reach into your PC."),
    h("div", { class: "field" }, h("span", {}, "Relay"), server));
  if (!r.pair_uri) {
    box.append(h("div", { class: "field" }, h("span", {}, ""), h("button", { type: "button", class: "primary", onclick: async () => {
      const res = await api.screentime_pair();
      if (!res.ok) return toast(`⚠ ${res.error}`);
      await refreshPhoneSettings();
    } }, "Pair phone")));
    return box;
  }
  const reveal = h("details", { id: "phonePairQr" }, h("summary", {}, "Show the pairing code (scan it with the phone camera)"));
  reveal.addEventListener("toggle", () => {
    if (!reveal.open || reveal.querySelector("svg")) return;
    let svg = "";
    try { svg = qrSvg(r.pair_uri!); } catch { /* too long for a QR code */ }
    const qr = h("div", { class: "st-qr", role: "img", "aria-label": "Pairing QR code" });
    qr.innerHTML = svg;                      // the library's own SVG markup for our pairing text
    reveal.append(svg ? qr : h("p", { class: "help" }, "Too long for a QR code: use Copy pairing text."),
      h("p", { class: "help" }, "Keep this private: anyone with it could read or fake your screen-time summaries."));
  });
  box.append(h("div", { class: "field" }, h("span", { class: "dot on" }), h("span", {}, `Paired · topic ${st.topic.slice(0, 14)}…`)),
    reveal,
    h("div", { class: "field st-btns" },
      h("button", { type: "button", class: "ghost", onclick: () => copy(r.pair_uri!, "Pairing text copied: paste it into Tasker on the phone") }, "Copy pairing text"),
      h("button", { type: "button", class: "ghost", onclick: async () => {
        if (!confirm("Make a new key? The phone stops working until you give it the new pairing text.")) return;
        await api.screentime_pair(); await refreshPhoneSettings();
      } }, "New key"),
      h("button", { type: "button", class: "ghost danger", onclick: async () => { await api.screentime_unpair(); await refreshPhoneSettings(); } }, "Unpair")));
  return box;
}

async function copy(text: string, note: string) {
  try { await navigator.clipboard.writeText(text); toast(`✓ ${note}`); } catch { toast("⚠ Couldn't copy: select the text and press Ctrl+C"); }
}

/** "2h", "90m", "1h 30m", "1:30", "120" -> minutes (null when it isn't a duration). */
export function parseGoal(v: string): number | null {
  const s = v.trim().toLowerCase();
  if (/^\d+$/.test(s)) return Math.min(1440, Number(s));
  const c = s.match(/^(\d{1,2}):([0-5]\d)$/);
  if (c) return Number(c[1]) * 60 + Number(c[2]);
  const m = s.match(/^(?:(\d+(?:\.\d+)?)\s*h(?:ours?|rs?)?)?\s*(?:(\d+)\s*m(?:in(?:utes?|s)?)?)?$/);
  if (!m || (!m[1] && !m[2])) return null;
  const total = Math.round(Number(m[1] ?? 0) * 60 + Number(m[2] ?? 0));
  return total > 0 && total <= 1440 ? total : null;
}

// ------------------------------------------------------------------ demo (?demo in a browser, no Python)
export function demoScreenTimeApi(settings: () => Record<string, any>, emit: (e: [string, any][]) => void, empty: boolean): ScreenTimeApi {
  const iso = (d: number) => { const x = new Date(); x.setDate(x.getDate() - d); const p = (n: number) => String(n).padStart(2, "0"); return `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}`; };
  const now = () => Date.now() / 1000;
  const days: StDay[] = empty ? [] : [134, 98, 171, 122, 87, 143, 110].map((m, i) => ({
    day: iso(i), total_min: m, pickups: null, device: "iPhone", platform: "ios", source: "folder",
    received: now() - 3600 * (i * 24 + 1), estimated: false,
    apps: i === 0 ? [{ name: "TikTok", minutes: 58 }, { name: "Instagram", minutes: 41 }, { name: "YouTube", minutes: 27 }, { name: "Messages", minutes: 8 }] : [],
  }));
  const goals: StGoal[] = [];
  let groupOffer = !empty;
  const key = (n: string) => ({ yt: "youtube", ig: "instagram", insta: "instagram" } as Record<string, string>)[n.toLowerCase().replace(/[^a-z0-9]/g, "")] ?? n.toLowerCase().replace(/[^a-z0-9]/g, "");
  const groupUse = (apps: string[]) => { const d = days.find((x) => x.day === iso(0)); if (!d?.apps.length) return null;
    const want = new Set(apps.map(key)); return d.apps.filter((a) => want.has(key(a.name))).reduce((t, a) => t + a.minutes, 0); };
  const SG = { label: "Social", apps: ["TikTok", "Instagram", "YouTube"], limit_min: 180 };
  let paired = !empty;
  const s = () => {
    const c = settings();
    return { enabled: c.screentime_enabled ?? !empty, platform: (c.screentime_platform || "iphone") as StStatus["platform"],
      transport: (c.screentime_transport || (c.screentime_platform === "android" ? "ntfy" : "folder")) as StStatus["transport"],
      goal_min: c.screentime_goal_min ?? (empty ? 0 : 120), in_brief: c.screentime_in_brief ?? true, nudges: c.screentime_nudges ?? true };
  };
  const panel = (): StPanel => {
    const c = s();
    if (!c.enabled) return { enabled: false };
    const today = days.find((d) => d.day === iso(0)) ?? null;
    const sug = today && today.total_min >= (c.goal_min || 180)
      ? { text: `You've been on your phone ${fmtMin(today.total_min)} today${c.goal_min ? ` (goal ${fmtMin(c.goal_min)})` : ""}, and “Email the TA about the lab makeup” is still open. Maybe park the phone and knock it out?`,
          total_min: today.total_min, goal_min: c.goal_min, todo: { id: "t1", text: "Email the TA about the lab makeup" } } : null;
    return { enabled: true, goal_min: c.goal_min, today, yesterday: days.find((d) => d.day === iso(1)) ?? null,
      week: days.map((d) => ({ day: d.day, total_min: d.total_min })),
      goals: goals.filter((g) => g.day === iso(0)).map((g) => ({ ...g, used_min: g.kind === "group" ? groupUse(g.apps ?? []) : g.used_min })),
      suggestion: sug, status: status(),
      suggested_group: groupOffer ? { ...SG, text: "Social: TikTok, Instagram, YouTube ≤ 3h", todo_text: "Social apps under 3h today", used_min: groupUse(SG.apps) } : null };
  };
  const status = (): StStatus => {
    const c = s();
    return { ...c, folder: c.platform === "android" ? "C:\\Users\\you\\Sync\\Monkey" : "C:\\Users\\you\\iCloudDrive\\Monkey",
      folder_exists: !empty, paired, server: "https://ntfy.sh", topic: paired ? "monkey-st-demo0000demo0000demo" : "",
      last_received: days.length ? { ts: days[0].received!, source: days[0].source } : null, last_error: "", days: days.length, keep_days: 30 };
  };
  const state = (): StState => {
    const st = status();
    const uri = paired ? "https://ntfy.sh/monkey-st-demo0000demo0000demo#" + "0f".repeat(32) : "";
    const steps = st.transport === "manual" ? ["Look at today's total and top app in the phone's Settings → Screen Time.", "Type them in the To-do panel's phone card."]
      : st.platform === "iphone" ? ["Install iCloud for Windows and turn on iCloud Drive.", "Make a Shortcuts automation: Get App & Website Data → Dictionary → Save File to iCloud Drive/Monkey.", "Click Check now.", "No Screen Time action in Shortcuts? Choose \"I'll type it in\"."]
      : ["Install Tasker and allow Usage access.", `Add the global variable MONKEY_PAIR = ${uri || "(click Pair phone first)"}.`, "App Info → JavaScriptlet → HTTP Request (POST %st_url, body %st_body).", "Click Check now."];
    return { ok: true, status: st, panel: panel(), steps, pair_uri: uri, tasker_js: "// demo: the real script is shown in the desktop app", cryptojs_url: "" };
  };
  const upd = () => emit([["screentime", { action: "updated" }]]);
  return {
    async screentime_state() { return state(); },
    async screentime_pair() { paired = true; return state(); },
    async screentime_unpair() { paired = false; return state(); },
    async screentime_check() { return { ...state(), check: { ok: true, read: 0, errors: [] } }; },
    async screentime_manual(total, _day, _pickups, topApp, topTime) {
      const m = parseGoal(total);
      if (m === null) return { ok: false, error: "type it like 2h 15m or 135" };
      const am = topApp ? parseGoal(topTime) : null;
      if (topApp && am === null) return { ok: false, error: `how long on ${topApp}? Type it like 45m` };
      let d = days.find((x) => x.day === iso(0));
      if (d) { d.total_min = m; d.source = "manual"; d.received = now(); }
      else days.unshift(d = { day: iso(0), total_min: m, pickups: null, apps: [], device: "typed in Monkey", platform: "", source: "manual", received: now(), estimated: false });
      if (topApp && am !== null) d.apps = [{ name: topApp, minutes: am }, ...d.apps.filter((a) => a.name.toLowerCase() !== topApp.toLowerCase())].sort((a, b) => b.minutes - a.minutes);
      upd();
      return { ok: true, panel: panel() };
    },
    async screentime_import() { return { ok: false, error: "Demo mode: import works in the desktop app" }; },
    async screentime_add_goal(kind, limit, app, repeat, label) {
      const m = parseGoal(limit);
      if (m === null) return { ok: false, error: "the limit must be like 2h or 30m" };
      if (kind === "app" && !app.trim()) return { ok: false, error: "which app?" };
      const apps = kind === "group" ? [...new Set(app.split(",").map((x) => x.trim()).filter(Boolean))] : [];
      if (kind === "group" && apps.length < 2) return { ok: false, error: "a group needs at least two apps, like TikTok, Instagram, YouTube" };
      const text = kind === "app" ? `${fmtMin(m)} or less on ${app.trim()} today` : kind === "group" ? `${label || "Chosen"} apps under ${fmtMin(m)} today` : `Phone under ${fmtMin(m)} today`;
      goals.push({ id: "g" + (goals.length + 1), todo_id: "", kind: kind as StGoal["kind"], app: kind === "app" ? app.trim() : "", apps, label: label || "Chosen",
        limit_min: m, day: iso(0), repeat, status: "pending",
        used_min: kind === "app" ? (days[0]?.apps.find((a) => key(a.name) === key(app))?.minutes ?? 0) : days[0]?.total_min ?? null, text });
      return { ok: true, panel: panel() };
    },
    async screentime_group_suggestion(accept) {
      groupOffer = false;
      if (accept) goals.push({ id: "g" + (goals.length + 1), todo_id: "", kind: "group", app: "", apps: SG.apps, label: SG.label, limit_min: SG.limit_min,
        day: iso(0), repeat: true, status: "pending", used_min: null, text: "Social apps under 3h today" });
      return { ok: true, panel: panel() };
    },
    async screentime_stop_goal(id) { const g = goals.find((x) => x.id === id); if (g) g.repeat = false; return { ok: true, panel: panel() }; },
    async screentime_forget() { days.length = 0; upd(); return state(); },
  };
}

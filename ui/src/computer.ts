// Computer tasks: the permission flow, the live task panel, and the floating companion view.
// Everything consequential happens in Python behind PermissionGate; this file only asks and shows.
import type { Api, AutoState, AutoTask, Approval, ComputerEvent } from "./bridge";
import { baked, ensureBaked, icon, wireHoverPress } from "./blocky/skin";
import { h, toast } from "./dom";
import { openInbox } from "./inboxcleanup";
import { openMailing } from "./mailinglists";
import { type TaskTemplate, approvalKind, loadTemplates, templateChip } from "./tasktemplates";
import { attention, enter } from "./motion";

let api: Api;
let state: AutoState | null = null;
let current: AutoTask | null = null;
let approvals: Approval[] = [];
const listeners: (() => void)[] = [];

let feed: ComputerEvent[] = [];
let feedTask = "";
const BACKEND_ICON: Record<string, string> = { browser: "🌐", uia: "🪟", visual: "👁" };
const BACKEND_NAME: Record<string, string> = { browser: "Monkey's browser", uia: "a Windows app", visual: "the screen (pixels)" };

const STATE_LABEL: Record<string, string> = {
  READY: "Ready", PLANNING: "Thinking", RECOVERING: "Retrying", RUNNING: "Working", WAITING: "Waiting", NEEDS_INPUT: "Needs you", PAUSED: "Paused",
  BLOCKED: "Stuck", VERIFYING: "Checking", COMPLETED: "Done ✓", FAILED: "Stopped", CANCELLED: "Stopped",
};
const LIVE = ["RUNNING", "WAITING", "NEEDS_INPUT", "VERIFYING", "BLOCKED", "PLANNING", "RECOVERING"];
const hotkey = () => (state?.stop_hotkey ?? "ctrl+alt+q").split("+").map((k) => k[0].toUpperCase() + k.slice(1)).join("+");

export function initComputer(a: Api) { api = a; void refresh(); }
export function onChange(fn: () => void) { listeners.push(fn); }
function changed() { for (const fn of listeners) { try { fn(); } catch (e) { console.error(e); } } }

export async function refresh() {
  state = await api.automation_state();
  approvals = state.approvals ?? [];
  current = state.tasks.find((t) => t.id === state!.active) ?? state.tasks.find((t) => LIVE.includes(t.state) || t.state === "PAUSED") ?? null;
  changed();
}

/** Backend event "automation": {task, avatar, control, approvals}. Returns the avatar mood. */
export function automationEvent(p: any): string {
  const t = p.task as AutoTask;
  if (!state) state = { enabled: true, tasks: [], active: null, approvals: [], demo_url: "", stop_hotkey: "ctrl+alt+q", windows_supported: false };
  state.tasks = [t, ...state.tasks.filter((x) => x.id !== t.id)];
  if (LIVE.includes(t.state) || t.state === "PAUSED") state.active = t.id;
  current = t;
  approvals = p.approvals ?? [];
  document.body.classList.toggle("computer-control", !!p.control);
  changed();
  return p.avatar ?? "idle";
}

/** Backend event "computer_event": one structured step of a general task (what really happened, by which backend). */
export function computerEvent(p: ComputerEvent) {
  if (p.task_id && p.task_id !== feedTask) { feed = []; feedTask = p.task_id; }
  if (p.ev === "ACTION_EXECUTED" && p.op === "observe") return;           // too chatty to show
  feed = [...feed.slice(-39), p];
  changed();
}

/** One human line per event. Failures say why; "verified" means it was read back, not just sent. */
export function describeEvent(e: ComputerEvent): string {
  const what = e.name ? `${e.role ? e.role + " " : ""}“${e.name}”` : "";
  const icon = BACKEND_ICON[e.backend ?? ""] ?? "•";
  switch (e.ev) {
    case "DRIVER_SWITCHED": return `↪ switched to ${BACKEND_NAME[e.to ?? ""] ?? e.to}${e.why ? ` (${e.why})` : ""}`;
    case "WINDOW_SELECTED": return `🪟 now working in ${e.process || e.window}`;
    case "BROWSER_NAVIGATED": return `🌐 opened ${e.url ?? ""}`;
    case "ACTION_VERIFIED": return `${icon} ✓ ${e.op?.replace("_", " ")} ${what}${e.stage === "verified" ? " (checked)" : ""}`;
    case "ACTION_EXECUTED": return `${icon} ${e.op?.replace("_", " ")} ${what}`;
    case "ACTION_FAILED": return `${icon} ✗ ${e.op?.replace("_", " ")} ${what}: ${e.detail ?? e.error}`;
    case "RECOVERY": return `↻ recovered (${e.recovered_by})`;
    case "WAIT_STARTED": return `⏳ waiting for ${e.kind}`;
    case "WAIT_FINISHED": return `⏳ ${e.ok ? "done waiting" : "gave up waiting"} (${e.kind})`;
    case "PLAN_UPDATED": return `🧭 ${e.subgoal}`;
    case "USER_INPUT_NEEDED": return `🙋 ${e.message}`;
    case "TASK_COMPLETED": return "🎉 done and verified";
    case "MODEL_CALL": return "💭 asked Claude for the next steps";
    default: return "";
  }
}

function activity(compact: boolean): HTMLElement | "" {
  const shown = feed.filter((e) => e.ev !== "ACTION_ACCEPTED" && describeEvent(e));
  if (!shown.length) return "";
  const last = [...feed].reverse().find((e) => e.backend);
  const where = last?.backend ? h("span", { class: `where b-${last.backend}` }, `${BACKEND_ICON[last.backend]} ${BACKEND_NAME[last.backend]}`) : "";
  if (compact) return h("div", { class: "activity compact" }, where, h("span", { class: "meta" }, describeEvent(shown[shown.length - 1])));
  return h("div", { class: "activity" }, h("div", { class: "row" }, h("b", {}, "Live"), where),
    h("ol", { class: "feed" }, ...shown.slice(-6).map((e) => h("li", { class: e.ev === "ACTION_FAILED" ? "bad" : e.ev === "ACTION_VERIFIED" ? "ok" : "" }, describeEvent(e)))));
}

export function controlBanner(): HTMLElement {
  const el = h("div", { id: "controlBanner", role: "status" });
  const draw = () => {
    const live = current && LIVE.includes(current.state);
    el.hidden = !live;
    el.replaceChildren(...(live ? [
      h("span", {}, current!.state === "NEEDS_INPUT" ? "🙋 Monkey needs you"
        : current!.window?.process ? `🖐 Monkey is using ${current!.window.process} and his browser` : "🖐 Monkey is using his browser"),
      h("button", { type: "button", class: "ghost mini danger", onclick: () => void control("stop") }, `■ Stop (${hotkey()})`),
    ] : []));
  };
  onChange(draw); draw();
  return el;
}

async function control(action: "pause" | "resume" | "stop" | "done") {
  if (!current) return;
  const r = await api.automation_control(action, current.id);
  if (!r.ok) toast(`⚠ ${r.error}`);
}

/** The live panel: what Monkey is doing, what he needs from you, and the controls. */
export function taskPanel(compact = false): HTMLElement {
  const box = h("div", { class: `taskpanel${compact ? " compact" : ""}` });
  const draw = () => {
    const t = current;
    box.hidden = !t && !compact;              // the Tasks menu shows the live task only while there is one
    if (!t) {
      box.replaceChildren(h("p", { class: "meta" }, compact ? "No task running." : "No task running. Ask Monkey below, or pick one of the things he can do."));
      return;
    }
    const pend = t.pending;
    const ap = approvals.find((a) => a.task_id === t.id && a.id === pend?.approval_id) ?? approvals.find((a) => a.task_id === t.id);
    const parts: HTMLElement[] = [
      h("div", { class: "taskhead" }, h("span", { class: `badge s-${t.state.toLowerCase()}` }, STATE_LABEL[t.state] ?? t.state),
        h("span", { class: "tasknote" }, t.note || t.subgoal || ""), compact ? "" : templateChip(t.template)),
    ];
    if (!compact) parts.push(h("p", { class: "meta" }, `“${t.objective}”`));
    if (!compact) parts.push(h("p", { class: "meta" }, [t.progress?.modules_done ? `${t.progress.modules_done} module(s) done` : "",
      `${t.usage?.actions ?? 0} steps`, t.usage?.model_calls ? `${t.usage.model_calls} Claude call(s) · $${(t.usage.usd ?? 0).toFixed(3)}` : "no Claude calls"]
      .filter(Boolean).join(" · ")));
    if (t.skill === "general" && feedTask === t.id) parts.push(activity(compact) as HTMLElement);
    if (t.state === "NEEDS_INPUT" && pend) {
      const card = h("div", { class: "needs" }, compact ? "" : h("p", {}, pend.message));
      const say = async (text: string) => {
        const r = await api.automation_reply(t.id, text);
        toast(r.message, 3500);
      };
      if (pend.kind === "question" && pend.info?.options) {
        const rec = pend.info.recommend?.letter;
        if (compact) card.append(h("p", { class: "q" }, pend.info.question ?? ""));
        card.append(h("div", { class: "opts" }, ...pend.info.options.map((o, i) => {
          const L = String.fromCharCode(65 + i);
          return h("button", { type: "button", class: `opt${L === rec ? " picked" : ""}`, title: `Answer ${L}`,
            onclick: () => void say(L) }, h("b", {}, L), h("span", {}, o),
            L === rec ? h("span", { class: "pickbadge", title: pend.info?.recommend?.reason ?? "" }, "🍌 Monkey's pick") : "");
        })));
        if (pend.info.recommend?.reason) card.append(h("p", { class: "meta why" }, `Why ${rec}: ${pend.info.recommend.reason}`));
        card.append(h("p", { class: "meta" }, "Click a letter, or say or type it (“B”). You choose; Monkey clicks it."));
      } else if (pend.kind === "domain") {
        card.append(h("div", { class: "row" },
          h("button", { type: "button", class: "primary mini", onclick: () => void say("allow") }, `Allow ${pend.info?.host ?? ""}`),
          h("button", { type: "button", class: "ghost mini", onclick: () => void say("no") }, "Don't")));
      } else if (pend.kind === "submit") {
        const word = (pend.info as any)?.word === "start" ? "start" : "submit";
        card.append(h("button", { type: "button", class: "primary mini", onclick: () => void say(word) },
          word === "start" ? "Start the quiz" : "Submit"),
          h("p", { class: "meta" }, `Or say or type “${word}”.`));
      } else if (pend.kind === "confirm") {
        if (compact) card.append(h("p", { class: "q" }, `“${pend.info?.statement ?? ""}”`));
        card.append(h("button", { type: "button", class: "primary mini", onclick: () => void say("I confirm") }, "I confirm"),
          h("p", { class: "meta" }, "Only if it's true for you. You can also say or type “I confirm”."));
      } else if (pend.kind === "approval" && ap) {
        card.append(approvalKind(ap.kind), h("div", { class: "row" },
          h("button", { type: "button", class: "primary mini", onclick: async () => {
            const r = await api.automation_approve(t.id, ap.id, ap.token, true); if (!r.ok) toast(`⚠ ${r.error}`); } }, "Allow once"),
          h("button", { type: "button", class: "ghost mini", onclick: () => void api.automation_approve(t.id, ap.id, "", false) }, "Don't")));
      } else {
        card.append(h("button", { type: "button", class: "primary mini", title: "Monkey also notices on his own when the page changes",
          onclick: () => void control("done") }, pend.kind === "sign_in" ? "I'm signed in" : "I did it"));
      }
      parts.push(card);
      // A new question or approval wiggles once when it first shows (redraws of the same one stay still).
      const ask = `${t.id}:${pend.kind}:${pend.approval_id ?? pend.message}`;
      if (box.dataset.ask !== ask) { box.dataset.ask = ask; requestAnimationFrame(() => attention(card)); }
    }
    const row = h("div", { class: "row taskctl" });
    if (LIVE.includes(t.state)) row.append(h("button", { type: "button", class: "ghost mini", onclick: () => void control("pause") }, "⏸ Pause"));
    if (t.state === "PAUSED") row.append(h("button", { type: "button", class: "primary mini", onclick: () => void control("resume") }, "▶ Resume"));
    if (LIVE.includes(t.state) || t.state === "PAUSED") row.append(h("button", { type: "button", class: "ghost mini danger", onclick: () => void control("stop") }, "■ Stop"));
    if (!compact) row.append(h("button", { type: "button", class: "ghost mini", onclick: () => void showHistory(t.id) }, "History"));
    parts.push(row);
    const ev = t.outcome?.evidence;
    if (t.state === "COMPLETED" && ev) parts.push(h("p", { class: "meta ok" }, typeof ev === "string"
      ? `Checked on screen: “${ev}”` : `Checked on the site: ${ev.done} of ${ev.total} complete.`));
    box.replaceChildren(...parts);
  };
  onChange(draw); draw();
  return box;
}

async function showHistory(taskId: string) {
  const r = await api.automation_history(taskId);
  const tr = api.automation_trace ? await api.automation_trace(taskId) : { ok: true, events: [] };
  const dlg = h("dialog", { class: "histdlg" });
  const steps = (tr.events ?? []).filter((e) => e.ev !== "ACTION_ACCEPTED" && describeEvent(e)).slice(-120).map((e) =>
    h("li", { class: e.ev === "ACTION_FAILED" ? "bad" : "" }, `${(e.t ?? 0).toFixed(1)}s · ${describeEvent(e)}${e.ms ? ` · ${e.ms} ms` : ""}`));
  const rows = (r.log ?? []).slice(-80).reverse().map((a) => h("li", {},
    `${new Date(a.ts * 1000).toLocaleTimeString()} · ${a.kind} ${a.target}`.trim() + ` · ${a.outcome}` + (a.risk ? ` (${a.risk.toLowerCase()})` : "")));
  dlg.append(h("h3", {}, "What Monkey did"), h("p", { class: "meta" }, "Only the kind of action, which control and the site are kept: never what was typed, page text or screenshots."),
    ...(steps.length ? [h("h4", {}, "Step by step"), h("ol", { class: "histlist feed" }, ...steps), h("h4", {}, "Permission log")] : []),
    h("ol", { class: "histlist" }, ...rows), h("button", { type: "button", class: "primary", onclick: () => { dlg.close(); dlg.remove(); } }, "Close"));
  document.body.append(dlg);
  dlg.showModal();
}

function browserPick(st: AutoState): HTMLElement {
  const sel = h("select", {},
    h("option", { value: "my_chrome", selected: st.browser === "my_chrome" }, "My Chrome: the tabs I share (Monkey extension)"),
    h("option", { value: "chrome", selected: (st.browser ?? "chrome") === "chrome" }, "Monkey's own Chrome window"),
    h("option", { value: "edge", selected: st.browser === "edge" }, "Monkey's own Edge window")) as HTMLSelectElement;
  const note = h("small", { class: "meta" });
  const pairBox = h("div", { class: "pairbox" });
  const draw = async () => {
    const v = sel.value;
    note.textContent = v === "my_chrome"
      ? "He works in your real Chrome, signed in as you, but only in tabs you share (and pop-ups they open, like Duo)."
      : `His own window and profile (sign in there once); your normal browser isn't touched.${v === "chrome" && st.chrome_installed === false ? " Chrome isn't installed on this PC, so Edge is used." : ""}`;
    pairBox.hidden = v !== "my_chrome";
    if (v !== "my_chrome" || !api.automation_bridge) return;
    const b = await api.automation_bridge("status");
    const code = h("input", { readonly: true, value: b.pairing_code ?? "", class: "code" }) as HTMLInputElement;
    const ok = b.extension_connected;
    pairBox.replaceChildren(
      h("p", { class: ok ? "meta ok" : "meta" }, ok ? `✓ Chrome is connected · ${b.tabs ?? 0} tab(s) shared` : b.error ? `⚠ ${b.error}` : "Not connected yet. One-time setup:"),
      ...(ok ? [] : [h("ol", { class: "steps" },
        h("li", {}, "In Chrome open ", h("b", {}, "chrome://extensions"), ", turn on ", h("b", {}, "Developer mode"), " (top right)."),
        h("li", {}, "Click ", h("b", {}, "Load unpacked"), " and pick Monkey's extension folder ",
          h("button", { type: "button", class: "ghost mini", onclick: async () => { const r = await api.automation_bridge!("open_folder"); if (!r.ok) toast(`⚠ ${r.error ?? ""} ${r.path ?? ""}`, 6000); } }, "Open folder")),
        h("li", {}, "Click the 🍌 Monkey icon in Chrome's toolbar, paste this code and press Pair:"),
        h("li", {}, "Open the page you want help with, click the Monkey icon → ", h("b", {}, "Let Monkey use this tab"), "."))]),
      h("div", { class: "row" }, code,
        h("button", { type: "button", class: "ghost mini", onclick: async () => { await navigator.clipboard.writeText(code.value).catch(() => code.select()); toast("Pairing code copied"); } }, "Copy"),
        h("button", { type: "button", class: "ghost mini", title: "The old code stops working; paste the new one in the extension",
          onclick: async () => { await api.automation_bridge!("new_code"); void draw(); } }, "New code")),
      h("small", { class: "meta" }, "Chrome shows “Monkey for Chrome started debugging this browser” while he works; press Cancel on that bar to stop him instantly."));
  };
  sel.addEventListener("change", async () => {
    await api.save_settings({ automation_browser: sel.value });
    if (state) state.browser = sel.value;
    toast(sel.value === "chrome" && st.chrome_installed === false ? "Chrome isn't installed, so Monkey will use Edge until it is." : "Saved.", 3000);
    void draw();
  });
  void draw();
  return h("div", { class: "field" }, h("label", {}, h("span", {}, "Where Monkey works"), sel), note, pairBox);
}

/** A capability in the Tasks menu: one of Monkey's own panels (inbox cleanup, mailing lists) or a browser template.
 *  Titles and blurbs of the browser ones come from Python (automation/templates.py). `icon` is the toy-block recipe. */
interface Cap { id: string; glyph: string; icon: string; panel?: "inbox" | "mailing"; title?: string; blurb?: string }
const CAPS: Cap[] = [
  { id: "inbox_cleanup", glyph: "🧹", icon: "broom", panel: "inbox", title: "Clean up my inbox",
    blurb: "Archives promos and old notifications after checking each one. Never deletes." },
  { id: "mailing_lists", glyph: "📭", icon: "inbox", panel: "mailing", title: "Unsubscribe from lists",
    blurb: "Newsletters you never open. You approve each one." },
  { id: "form_fill", glyph: "📋", icon: "clipboard", blurb: "He fills it in; you review before Submit." },
  { id: "look_only", glyph: "🔎", icon: "search", blurb: "Searches and shows you. Never books or buys." },
  { id: "account_settings", glyph: "⚙", icon: "gear", blurb: "Settings, notifications, trials. Asks before each change." },
  { id: "shopping", glyph: "🛒", icon: "box", blurb: "Fills the cart or booking. You pay." },
  { id: "course", glyph: "🎒", icon: "backpack", blurb: "Canvas or another course site." },
];
const EXAMPLES = ["Clean up my inbox", "Cancel my Spotify free trial reminder", "Find the cheapest flight to Denver on Dec 18, just show me",
  "Fill in the club sign-up form with my name and email, let me review"];
export const CAN_CANNOT = "Monkey reads and looks around freely, and stops for your OK before anything that sends, submits, buys, deletes or changes an account. Email: he archives, never deletes. Never: banking or payment sites, Instagram/Snapchat automation, typing card or payment details, changing passwords or security settings.";

let chosen = "";                 // the browser template picked in the Tasks menu ('' = none yet)
let askText = "";
let askUrl = "";                 // a start page Monkey proposed (automation_propose)

/** Swap a capability chip's glyph for its toy-block icon once the sheets exist (no WebGL: the glyph stays). The icon
 *  is the button's direct child, so it owns the hover/press animation and motion.css leaves the button alone. */
function blockyChips(root: HTMLElement) {
  const apply = () => {
    for (const b of root.querySelectorAll<HTMLElement>(".tk-cap[data-icon]")) {
      const g = b.querySelector(":scope > .tk-ico");
      if (g) g.replaceWith(icon(b.dataset.icon!, "tk-bi"));
    }
  };
  if (baked) apply(); else void ensureBaked(apply);
  if (!root.dataset.bi) { root.dataset.bi = "1"; wireHoverPress(root, ".tk-cap"); }
}

/** The Tasks dialog, general-first: "What should Monkey do?", what he can do (capabilities), what he can't, the live
 *  task, the details form for a browser task (course fields only for Course modules), and recent tasks. */
export async function openTasks(prefill?: { objective?: string; start_url?: string; template?: string }) {
  await refresh();
  const templates = await loadTemplates(api);
  let dlg = document.getElementById("tasksDlg") as HTMLDialogElement | null;
  if (!dlg) { dlg = h("dialog", { id: "tasksDlg", class: "tasksdlg tkdlg" }) as HTMLDialogElement; document.body.append(dlg); }
  dlg.classList.add("tkdlg");
  const st = state!;
  if (prefill?.objective !== undefined) askText = prefill.objective;
  if (prefill?.start_url !== undefined) askUrl = prefill.start_url;
  if (prefill?.template !== undefined || prefill?.objective !== undefined) {
    chosen = prefill?.template && templates.some((t) => t.id === prefill.template) ? prefill.template
      : prefill?.objective ? "generic" : chosen;
  }
  const busy = !!current && (LIVE.includes(current.state) || current.state === "PAUSED");
  const tplOf = (id: string) => templates.find((t) => t.id === id);

  // ---- "What should Monkey do?"
  const objective = h("textarea", { rows: 2, class: "tk-objective", "aria-label": "What should Monkey do?",
    placeholder: "Anything you'd do yourself on a website or your PC, e.g. “clean up my inbox” or “find the cheapest flight to Denver on Dec 18, just show me”" }) as HTMLTextAreaElement;
  objective.value = askText;
  objective.addEventListener("input", () => { askText = objective.value; });
  const askErr = h("p", { class: "keynote", role: "status" });
  const fail = (el: HTMLElement, msg: string) => { el.className = "keynote bad"; el.textContent = `⚠ ${msg}`; el.scrollIntoView({ block: "nearest" }); };
  const route = async () => {
    askErr.className = "keynote"; askErr.textContent = "";
    const text = objective.value.trim();
    if (!text) return fail(askErr, "Say what Monkey should do, or pick one of the things below.");
    const r = api.automation_route ? await api.automation_route(text) : { ok: true, panel: "", template: "generic", refusal: "" };
    if (r.refusal) return fail(askErr, r.refusal);
    if (r.panel === "inbox_cleanup") { dlg!.close(); void openInbox({ organize: /organi[sz]e|label/i.test(text) }); return; }
    if (r.panel === "mailing_lists") { dlg!.close(); void openMailing(); return; }
    pick(r.template || "generic");
  };
  const ask = h("section", { class: "tk-ask" },
    h("label", { class: "field" }, h("span", {}, "What should Monkey do?"), objective),
    h("div", { class: "tk-examples" }, h("small", { class: "meta" }, "For example:"),
      ...EXAMPLES.map((e) => h("button", { type: "button", class: "ghost mini tk-ex", onclick: () => { objective.value = askText = e; objective.focus(); } }, e))),
    h("div", { class: "tk-askrow" }, h("button", { type: "button", class: "primary tk-go", onclick: () => void route() }, "Go"),
      h("small", { class: "meta" }, "Monkey works out the kind of task and shows you exactly what he'll do first.")),
    askErr);

  // ---- what Monkey can do (capability chips)
  const caps = h("div", { class: "tk-caps", role: "group", "aria-label": "What Monkey can do" });
  const drawCaps = () => caps.replaceChildren(...CAPS.filter((c) => c.panel || tplOf(c.id)).map((c) => {
    const t = tplOf(c.id);
    return h("button", { type: "button", class: `ghost tk-cap${chosen === c.id ? " on" : ""}`, "data-cap": c.id, "data-icon": c.icon,
      "aria-pressed": String(chosen === c.id), title: t?.blurb ?? c.blurb ?? "",
      onclick: () => {
        if (c.panel === "inbox") { dlg!.close(); void openInbox(); return; }
        if (c.panel === "mailing") { dlg!.close(); void openMailing(); return; }
        pick(c.id);
      } },
      h("span", { class: "tk-ico", "aria-hidden": "true" }, c.glyph), h("b", {}, c.title ?? t?.title ?? c.id), h("small", {}, c.blurb ?? t?.blurb ?? ""));
  }));
  drawCaps();
  blockyChips(caps);

  // ---- the details of a browser task (only once one is picked)
  const formBox = h("section", { class: "tk-form", "aria-label": "Task details" });
  const pick = (id: string) => {
    chosen = id; drawCaps(); blockyChips(caps); drawForm();
    formBox.scrollIntoView({ block: "nearest" });
    enter(formBox, "rise");
  };
  const drawForm = () => {
    const tpl = tplOf(chosen);
    formBox.hidden = !tpl;
    if (!tpl) { formBox.replaceChildren(); return; }
    if (!objective.value && tpl.example) objective.placeholder = `e.g. ${tpl.example}`;
    if (!st.enabled) {
      formBox.replaceChildren(h("h4", {}, tpl.title), h("p", { class: "meta" }, tpl.blurb),
        h("p", { class: "tk-off" }, "This one works in Monkey's own browser, which is off. Turn on “Let Monkey use his own browser” at the bottom to start it."));
      return;
    }
    if (busy) {
      formBox.replaceChildren(h("h4", {}, tpl.title), h("p", { class: "meta" }, "One task at a time: pause or stop the running one to start another."));
      return;
    }
    formBox.replaceChildren(...taskForm(tpl, st, objective));
  };
  drawForm();

  // ---- recent tasks (browser tasks and the last inbox cleanup)
  const inbox = await api.inbox_state?.().catch(() => null);
  const runs: HTMLElement[] = [];
  const last = inbox?.undo_run ?? inbox?.last_run;
  if (last) runs.push(h("li", {}, h("span", { class: "badge s-completed" }, last.status === "undone" ? "Undone" : "Done ✓"),
    ` 🧹 Inbox cleanup · ${last.summary?.say ?? ""} `,
    inbox?.undo_run ? h("button", { type: "button", class: "ghost mini", onclick: () => { dlg!.close(); void openInbox(); } }, "Open") : ""));
  runs.push(...st.tasks.filter((t) => !LIVE.includes(t.state) && t.state !== "PAUSED").slice(0, 8).map((t) =>
    h("li", {}, h("span", { class: `badge s-${t.state.toLowerCase()}` }, STATE_LABEL[t.state] ?? t.state), " ", t.objective.slice(0, 70),
      " ", templateChip(t.template), " ", h("button", { type: "button", class: "ghost mini", onclick: () => void showHistory(t.id) }, "History"))));

  const sw = h("input", { type: "checkbox", id: "tkEnable", checked: st.enabled }) as HTMLInputElement;
  sw.addEventListener("change", async () => {
    state = await api.automation_enable(sw.checked);
    toast(sw.checked ? "Browser tasks on" : "Browser tasks off: everything stopped");
    void openTasks();
  });
  dlg.replaceChildren(
    h("div", { class: "taskstop" }, h("h3", {}, "🖐 Tasks"),
      h("button", { type: "button", class: "ghost mini", "aria-label": "Close", onclick: () => dlg!.close() }, "✕")),
    taskPanel(false),
    ask,
    h("section", { class: "tk-capsec" }, h("h4", {}, "Things Monkey can do"), caps),
    h("p", { class: "tk-limits limits" }, h("b", {}, "What Monkey can and can't do: "), CAN_CANNOT),
    formBox,
    runs.length ? h("section", { class: "tk-recent" }, h("h4", {}, "Recent tasks"), h("ul", { class: "pastlist" }, ...runs))
      : h("section", { class: "tk-recent" }, h("h4", {}, "Recent tasks"), h("p", { class: "meta" }, "Nothing yet. Ask above, or pick one of the things Monkey can do.")),
    h("label", { class: "field toggle tk-switch" }, sw, h("span", {}, h("b", {}, "Let Monkey use his own browser"),
      h("small", {}, " For website tasks (forms, settings, look-ups, shopping, courses). Off by default; turning it off stops everything at once. Inbox cleanup and mailing lists don't need it."))),
  );
  if (!dlg.open) dlg.showModal();
  dlg.scrollTop = 0;
}

/** The details form of one browser task. Course-only fields (course page, the sign-in and video sites courses use,
 *  the demo course) exist only in the Course template. */
function taskForm(tpl: TaskTemplate, st: AutoState, objective: HTMLTextAreaElement): HTMLElement[] {
  const isCourse = tpl.skill === "course";
  const url = h("input", { class: "tk-start", placeholder: "https://example.org/account (optional)" }) as HTMLInputElement;
  const courseUrl = h("input", { class: "tk-course-url", name: "course_url", placeholder: "https://canvas.yourschool.edu/courses/123/modules" }) as HTMLInputElement;
  (isCourse ? courseUrl : url).value = askUrl;
  (isCourse ? courseUrl : url).addEventListener("input", (e) => { askUrl = (e.target as HTMLInputElement).value; });
  const domains = h("input", { placeholder: "example.org" }) as HTMLInputElement;
  const fillHost = (from: HTMLInputElement) => { try { const u = new URL(from.value.includes("://") ? from.value : `https://${from.value}`); if (!domains.value) domains.value = u.hostname; } catch { /* typing */ } };
  url.addEventListener("change", () => fillHost(url));
  courseUrl.addEventListener("change", () => fillHost(courseUrl));
  const shots = h("input", { type: "checkbox" }) as HTMLInputElement;
  const askMore = h("input", { type: "checkbox" }) as HTMLInputElement;
  const helpers = h("input", { type: "checkbox", checked: true }) as HTMLInputElement;
  const apps = h("input", { placeholder: "notepad.exe, excel.exe" }) as HTMLInputElement;
  const files = h("textarea", { rows: 2, placeholder: "C:\\Users\\you\\Documents\\report.docx (one per line)" }) as HTMLTextAreaElement;
  const physical = h("input", { type: "checkbox" }) as HTMLInputElement;
  const winList = h("div", { class: "row winpick" });
  const anySite = h("input", { type: "checkbox", checked: true }) as HTMLInputElement;
  const sitesField = h("label", { class: "field" }, h("span", {}, "Sites he may use"), domains);
  const helpersField = h("label", { class: "field toggle" }, helpers, h("span", {}, "Also allow the sign-in and video sites courses use (your school's login, Duo, Microsoft, Canvas, Kaltura, Panopto, YouTube, Vimeo). Anything else, he asks you first."));
  const syncSites = () => {
    domains.disabled = anySite.checked;
    sitesField.hidden = anySite.checked;
    helpersField.hidden = anySite.checked;
  };
  anySite.addEventListener("change", syncSites);
  if (askUrl) fillHost(isCourse ? courseUrl : url);
  if (!isCourse && st.windows_supported) {
    void api.automation_windows().then((w) => {
      const seen = new Set<string>();
      for (const x of w.windows.filter((x) => !x.sensitive && x.process)) {
        if (seen.has(x.process)) continue; seen.add(x.process);
        winList.append(h("button", { type: "button", class: "ghost mini", title: x.title,
          onclick: () => { const cur = apps.value.split(/[,\s]+/).filter(Boolean); if (!cur.includes(x.process)) apps.value = [...cur, x.process].join(", "); } }, `+ ${x.process}`));
      }
    });
  }
  const err = h("p", { class: "keynote" });
  const start = async () => {
    err.textContent = ""; err.className = "keynote";
    const fail = (msg: string) => { err.className = "keynote bad"; err.textContent = `⚠ ${msg}`; err.scrollIntoView({ block: "nearest" }); };
    let r: { ok: boolean; error?: string };
    try {
      r = await api.automation_start(objective.value, (isCourse ? courseUrl : url).value.trim(), domains.value.split(/[,\s]+/).filter(Boolean),
        "managed_browser", shots.checked, askMore.checked, helpers.checked && isCourse, anySite.checked,
        isCourse ? "course" : "general", isCourse ? [] : apps.value.split(/[,\s]+/).filter(Boolean),
        isCourse ? [] : files.value.split(/\n+/).map((x) => x.trim()).filter(Boolean), physical.checked && !isCourse,
        null, isCourse ? "" : tpl.id);
    } catch (e) {                                   // a crash in the app must still answer the click
      return fail(`Couldn't start: ${(e as Error)?.message ?? e}`);
    }
    if (!r.ok) return fail(r.error ?? "Couldn't start.");
    toast(st.browser === "my_chrome" ? "Started in the Chrome tab you shared. You can Pause or Stop anytime."
      : "Started. Watch the Monkey browser window; you can Pause or Stop anytime.", 5000);
    void refresh();
  };
  const parts: HTMLElement[] = [
    h("h4", {}, tpl.title, " ", h("small", { class: "meta" }, tpl.blurb)),
  ];
  if (isCourse) {
    const demoBtn = h("button", { type: "button", class: "ghost", onclick: async () => {
      const d = await api.automation_demo(); objective.value = d.objective; courseUrl.value = d.url; domains.value = d.domain; } }, "Try the safe demo course");
    parts.push(h("div", { class: "tk-course" },
      h("label", { class: "field" }, h("span", {}, "Course page"), courseUrl),
      helpersField,
      h("p", { class: "help" }, `Questions and confirmations are yours: Monkey reads each one out with his pick and a reason, then clicks exactly what you say ("B", "I confirm"). He clicks Complete module on his own.`),
      h("div", { class: "row" }, demoBtn)));
  } else {
    parts.push(h("div", { class: "tk-general" },
      h("label", { class: "field" }, h("span", {}, "Start page"), url),
      h("label", { class: "field" }, h("span", {}, "Apps he may use (program names)"), apps), winList,
      h("label", { class: "field" }, h("span", {}, "Files he may open, save or upload"), files),
      h("label", { class: "field toggle" }, physical, h("span", {}, "He may use my real mouse and keyboard in those apps when nothing else works (he waits while you're typing or moving the mouse)"))));
  }
  parts.push(
    h("label", { class: "field toggle" }, anySite, h("span", {}, h("b", {}, "Any website"),
      " Sites open freely. He still never types passwords, codes or card details, and asks before anything that sends, submits, buys, deletes or changes your account.")),
    sitesField,
    browserPick(st),
    h("label", { class: "field toggle" }, shots, h("span", {}, "Let Claude see screenshots of these pages when he's unsure (they're sent to Anthropic's API; otherwise only the page's outline of buttons and text is sent, and only when the built-in steps don't know what to do)")),
    h("label", { class: "field toggle" }, askMore, h("span", {}, "Ask me before he types into or saves anything, too")),
    h("p", { class: "help" }, `Reading and looking around are free. Anything outward-facing (send, submit, buy, delete, change your account) stops for your OK on that exact step. Page and email text can never give him orders. Stop anytime with the Stop button or ${hotkey()}.`),
    h("div", { class: "row" }, h("button", { type: "button", class: "primary tk-start-btn", disabled: !st.enabled, onclick: start }, "Allow and start")),
    err);
  if (!isCourse) helpersField.remove();
  syncSites();
  return parts;
}

// ------------------------------------------------------------------------------------------------ companion view
/** The floating companion: avatar + status + controls, in a small frameless always-on-top window. */
export function initOverlay(avatarHost: HTMLElement, setMood: (mood: string) => void, startMode = "compact") {
  document.body.classList.add("overlay");
  const app = document.getElementById("app")!;
  const ring = h("div", { class: "ov-ring" });
  const head = h("div", { class: "ov-avatar pywebview-drag-region", title: "Drag to move · double-click to shrink/grow" }, ring);
  head.append(avatarHost);
  const panel = taskPanel(true);
  const status = h("div", { class: "ov-title" }, "Monkey");
  const btn = (label: string, title: string, fn: () => void) => h("button", { type: "button", class: "ghost mini", title, onclick: fn }, label);
  const ctl = h("div", { class: "row ov-ctl" },
    btn("＋ Task", "Start a task (opens Monkey)", () => void api.overlay("expand")),
    btn("⤢", "Bigger / smaller", () => setMode(mode === "expanded" ? "compact" : "expanded")),
    btn("–", "Shrink to just Monkey", () => setMode("minimized")),
    btn("✕", "Hide the companion for now (it comes back with the next task; Tray icon → Show companion while one runs)", () => void api.overlay("hide")));
  const card = h("div", { class: "ov-panel" }, status, panel, ctl);
  const root = h("div", { id: "ov" }, head, card);
  app.replaceChildren(root);
  let mode = startMode;
  const setMode = (m: string) => {
    mode = m; root.dataset.mode = m; void api.overlay("mode", m); setTimeout(reportHits, 120);
  };
  head.addEventListener("dblclick", () => setMode(mode === "minimized" ? "compact" : "minimized"));
  root.dataset.mode = mode;
  // Only Monkey and the panel take clicks; Windows passes everything else to the app underneath.
  const reportHits = () => {
    const rects = [head, ...(mode === "minimized" ? [] : [card])].map((el) => {
      const r = el.getBoundingClientRect();
      return { x: r.left, y: r.top, w: r.width, h: r.height, r: el === head ? r.width / 2 : 14 };
    });
    void api.overlay("hit", { rects, dpr: window.devicePixelRatio || 1 });
  };
  new ResizeObserver(reportHits).observe(root);
  // Moving the companion to a display with a different scale (or changing Windows scaling) changes the CSS→physical
  // pixel ratio without resizing the page: re-report so the click-through region still matches what you see.
  const watchDpr = () => {
    const mq = matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
    mq.addEventListener("change", () => { reportHits(); watchDpr(); }, { once: true });
  };
  watchDpr();
  // Remember where it was dragged to.
  let last = "";
  setInterval(() => {
    const g = `${window.screenX},${window.screenY}`;
    if (g !== last) { last = g; void api.overlay("geometry", { x: window.screenX, y: window.screenY }); }
  }, 2000);
  onChange(() => {
    const t = current;
    ring.dataset.on = t && ["RUNNING", "WAITING", "VERIFYING"].includes(t.state) ? "1" : "";
    ring.dataset.help = t?.state === "NEEDS_INPUT" ? "1" : "";
    status.textContent = t ? `Monkey · ${STATE_LABEL[t.state] ?? t.state}` : "Monkey";
    if (t?.state === "NEEDS_INPUT" && mode === "minimized") setMode("compact");      // never hide a question
    if (t?.state === "NEEDS_INPUT" && t.pending?.kind === "question" && mode !== "expanded") setMode("expanded");
    setTimeout(reportHits, 50);
  });
  onChange(() => setMood(current ? moodFor(current.state) : "idle"));
  setTimeout(reportHits, 300);
}

export function moodFor(s: string): string {
  return ({ RUNNING: "working", WAITING: "waiting", NEEDS_INPUT: "help", VERIFYING: "thinking", COMPLETED: "celebrate",
            BLOCKED: "blocked", FAILED: "sad", PAUSED: "paused" } as Record<string, string>)[s] ?? "idle";
}

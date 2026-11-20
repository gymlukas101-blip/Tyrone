// Computer tasks: the permission flow, the live task panel, and the floating companion view.
// Everything consequential happens in Python behind PermissionGate; this file only asks and shows.
import type { Api, AutoState, AutoTask, Approval, ComputerEvent } from "./bridge";
import { h, toast } from "./dom";

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
    if (!t) {
      box.replaceChildren(h("p", { class: "meta" }, compact ? "No task running." : "No task yet. Start one below."));
      return;
    }
    const pend = t.pending;
    const ap = approvals.find((a) => a.task_id === t.id && a.id === pend?.approval_id) ?? approvals.find((a) => a.task_id === t.id);
    const parts: HTMLElement[] = [
      h("div", { class: "taskhead" }, h("span", { class: `badge s-${t.state.toLowerCase()}` }, STATE_LABEL[t.state] ?? t.state),
        h("span", { class: "tasknote" }, t.note || t.subgoal || "")),
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
        card.append(h("div", { class: "row" },
          h("button", { type: "button", class: "primary mini", onclick: async () => {
            const r = await api.automation_approve(t.id, ap.id, ap.token, true); if (!r.ok) toast(`⚠ ${r.error}`); } }, "Allow once"),
          h("button", { type: "button", class: "ghost mini", onclick: () => void api.automation_approve(t.id, ap.id, "", false) }, "Don't")));
      } else {
        card.append(h("button", { type: "button", class: "primary mini", title: "Monkey also notices on his own when the page changes",
          onclick: () => void control("done") }, pend.kind === "sign_in" ? "I'm signed in" : "I did it"));
      }
      parts.push(card);
    }
    const row = h("div", { class: "row taskctl" });
    if (LIVE.includes(t.state)) row.append(h("button", { type: "button", class: "ghost mini", onclick: () => void control("pause") }, "⏸ Pause"));
    if (t.state === "PAUSED") row.append(h("button", { type: "button", class: "primary mini", onclick: () => void control("resume") }, "▶ Resume"));
    if (LIVE.includes(t.state) || t.state === "PAUSED") row.append(h("button", { type: "button", class: "ghost mini danger", onclick: () => void control("stop") }, "■ Stop"));
    if (!compact) row.append(h("button", { type: "button", class: "ghost mini", onclick: () => void showHistory(t.id) }, "History"));
    parts.push(row);
    if (t.state === "COMPLETED" && t.outcome?.evidence) parts.push(h("p", { class: "meta ok" }, `Checked on the site: ${t.outcome.evidence.done} of ${t.outcome.evidence.total} complete.`));
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
        h("li", {}, "Open your Canvas page, click the Monkey icon → ", h("b", {}, "Let Monkey use this tab"), "."))]),
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

/** The Tasks dialog: on/off switch, the permission flow, the live panel and past tasks. */
export async function openTasks(prefill?: { objective?: string; start_url?: string }) {
  await refresh();
  let dlg = document.getElementById("tasksDlg") as HTMLDialogElement | null;
  if (!dlg) { dlg = h("dialog", { id: "tasksDlg", class: "tasksdlg" }) as HTMLDialogElement; document.body.append(dlg); }
  const st = state!;
  const sw = h("input", { type: "checkbox", checked: st.enabled }) as HTMLInputElement;
  sw.addEventListener("change", async () => { state = await api.automation_enable(sw.checked); toast(sw.checked ? "Computer tasks on" : "Computer tasks off: everything stopped"); void openTasks(); });

  const objective = h("textarea", { rows: 2, placeholder: "e.g. Work through the 4 modules of the Title IX training on Canvas", value: prefill?.objective ?? "" }) as HTMLTextAreaElement;
  objective.value = prefill?.objective ?? "";
  const url = h("input", { placeholder: "Start page, e.g. https://canvas.wisc.edu/courses/12345/modules", value: prefill?.start_url ?? "" }) as HTMLInputElement;
  const domains = h("input", { placeholder: "canvas.wisc.edu" }) as HTMLInputElement;
  const fillHost = () => { try { const u = new URL(url.value.includes("://") ? url.value : `https://${url.value}`); if (!domains.value) domains.value = u.hostname; } catch { /* typing */ } };
  url.addEventListener("change", fillHost); fillHost();
  const shots = h("input", { type: "checkbox" }) as HTMLInputElement;
  const askMore = h("input", { type: "checkbox" }) as HTMLInputElement;
  const helpers = h("input", { type: "checkbox", checked: true }) as HTMLInputElement;
  const general = h("input", { type: "radio", name: "mode" }) as HTMLInputElement;
  const course = h("input", { type: "radio", name: "mode", checked: true }) as HTMLInputElement;
  const apps = h("input", { placeholder: "notepad.exe, excel.exe" }) as HTMLInputElement;
  const files = h("textarea", { rows: 2, placeholder: "C:\\Users\\you\\Documents\\report.docx (one per line)" }) as HTMLTextAreaElement;
  const physical = h("input", { type: "checkbox" }) as HTMLInputElement;
  const winList = h("div", { class: "row winpick" });
  const appBox = h("div", { class: "generalonly", hidden: true },
    h("label", { class: "field" }, h("span", {}, "Apps he may use (program names)"), apps), winList,
    h("label", { class: "field" }, h("span", {}, "Files he may open, save or upload"), files),
    h("label", { class: "field toggle" }, physical, h("span", {}, "He may use my real mouse and keyboard in those apps when nothing else works (he waits while you're typing or moving the mouse)")));
  const syncMode = async () => {
    appBox.hidden = !general.checked;
    helpers.closest("label")!.toggleAttribute("hidden", general.checked);
    if (general.checked && st.windows_supported && !winList.childElementCount) {
      const w = await api.automation_windows();
      const seen = new Set<string>();
      for (const x of w.windows.filter((x) => !x.sensitive && x.process)) {
        if (seen.has(x.process)) continue; seen.add(x.process);
        winList.append(h("button", { type: "button", class: "ghost mini", title: x.title,
          onclick: () => { const cur = apps.value.split(/[,\s]+/).filter(Boolean); if (!cur.includes(x.process)) apps.value = [...cur, x.process].join(", "); } }, `+ ${x.process}`));
      }
    }
  };
  general.addEventListener("change", () => void syncMode()); course.addEventListener("change", () => void syncMode());
  const anySite = h("input", { type: "checkbox", checked: true }) as HTMLInputElement;
  const syncSites = () => {
    domains.disabled = anySite.checked;
    domains.closest("label")?.toggleAttribute("hidden", anySite.checked);
    helpers.closest("label")?.toggleAttribute("hidden", anySite.checked);
  };
  anySite.addEventListener("change", syncSites);
  const err = h("p", { class: "keynote" });
  const start = async () => {
    err.textContent = ""; err.className = "keynote";
    const r = await api.automation_start(objective.value, url.value.trim(), domains.value.split(/[,\s]+/).filter(Boolean),
      "managed_browser", shots.checked, askMore.checked, helpers.checked && !general.checked, anySite.checked,
      general.checked ? "general" : "course", apps.value.split(/[,\s]+/).filter(Boolean),
      files.value.split(/\n+/).map((x) => x.trim()).filter(Boolean), physical.checked);
    if (!r.ok) { err.className = "keynote bad"; err.textContent = `⚠ ${r.error}`; return; }
    toast("Started. Watch the Monkey browser window; you can Pause or Stop anytime.", 5000);
    void refresh();
  };
  const busy = !!current && (LIVE.includes(current.state) || current.state === "PAUSED");
  const form = h("section", { class: "taskform" },
    h("h4", {}, "Start a task"),
    h("label", { class: "field" }, h("span", {}, "What should Monkey do?"), objective),
    h("div", { class: "modes" },
      h("label", {}, course, " ", h("b", {}, "Course modules in Monkey's browser"),
        h("small", {}, " A separate browser window with its own sign-ins. He can only click on the sites below.")),
      h("label", { class: st.windows_supported ? "" : "off" }, general, " ", h("b", {}, "General task: his browser + apps you pick"),
        h("small", {}, " Plans with Claude, switches between the browser and the apps, checks the result on screen."))),
    appBox,
    h("label", { class: "field" }, h("span", {}, "Start page"), url),
    h("label", { class: "field toggle" }, anySite, h("span", {}, h("b", {}, "Any website"),
      " Canvas, Duo, module and video sites open freely. He still never types passwords or codes, asks before anything that sends, submits, buys or deletes, and quiz answers stay yours.")),
    h("label", { class: "field" }, h("span", {}, "Sites he may use"), domains),
    browserPick(st),
    h("label", { class: "field toggle" }, shots, h("span", {}, "Let Claude see screenshots of these pages when he's unsure (they're sent to Anthropic's API; otherwise only the page's outline of buttons and text is sent, and only when the built-in steps don't know what to do)")),
    h("label", { class: "field toggle" }, helpers, h("span", {}, "Also allow the sign-in and video sites courses use (your school's login, Duo, Microsoft, Canvas, Kaltura, Panopto, YouTube, Vimeo). Anything else, he asks you first.")),
    h("label", { class: "field toggle" }, askMore, h("span", {}, "Ask me before he types into or saves anything, too")),
    h("p", { class: "help" }, `Questions and confirmations are yours: Monkey reads each one out with his pick and a reason, then clicks exactly what you say ("B", "I confirm"). He clicks Complete module on his own. He never signs in or types passwords, and asks before anything that sends, submits, buys or deletes. Stop anytime with the Stop button or ${hotkey()}.`),
    h("div", { class: "row" },
      h("button", { type: "button", class: "ghost", onclick: async () => {
        const d = await api.automation_demo(); objective.value = d.objective; url.value = d.url; domains.value = d.domain; } }, "Try the safe demo course"),
      h("button", { type: "button", class: "primary", disabled: busy || !st.enabled, onclick: start }, busy ? "A task is running" : "Allow and start")),
    err);
  const past = st.tasks.filter((t) => !LIVE.includes(t.state) && t.state !== "PAUSED").slice(0, 8).map((t) =>
    h("li", {}, h("span", { class: `badge s-${t.state.toLowerCase()}` }, STATE_LABEL[t.state] ?? t.state), " ", t.objective.slice(0, 70),
      " ", h("button", { type: "button", class: "ghost mini", onclick: () => void showHistory(t.id) }, "History")));
  dlg.replaceChildren(
    h("div", { class: "taskstop" }, h("h3", {}, "🖐 Computer tasks"), h("button", { type: "button", class: "ghost mini", onclick: () => dlg!.close() }, "✕")),
    h("label", { class: "field toggle" }, sw, h("span", {}, h("b", {}, "Let Monkey do tasks in his own browser"),
      h("small", {}, " Off by default. Turning it off stops everything immediately. Monkey works normally without it."))),
    ...(st.enabled ? [taskPanel(false), busy ? h("p", { class: "meta" }, "One task at a time: pause or stop this one to start another.") : form, past.length ? h("section", {}, h("h4", {}, "Earlier tasks"), h("ul", { class: "pastlist" }, ...past)) : ""] : []),
  );
  syncSites();
  if (!dlg.open) dlg.showModal();
  dlg.scrollTop = 0;
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
    btn("✕", "Hide the companion (Tray icon → Show companion brings it back)", () => void api.overlay("hide")));
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

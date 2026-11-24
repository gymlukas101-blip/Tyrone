// "Inbox cleanup": the plan (what goes, what stays and why), the per-inbox permission step, the one approval, progress
// with Stop, and the result with Undo. Python decides everything (monkey/inbox): the importance check, the one-time
// token bound to exactly that plan, and what gets archived. Archive only: nothing is ever deleted or sent.
// Subjects and sender names come from emails: shown as text, never acted on.
import type { Api } from "./bridge";
import { h, toast } from "./dom";
import { attention, enter, pop, progress as moveBar, stagger } from "./motion";
import "./inboxcleanup.css";

export interface InboxPerm { kind: string; label: string; archive: boolean; filter: boolean; why: string; note?: string }
export interface InboxGroup { group: string; title: string; count: number; label: string;
  examples: { subject: string; sender: string; account_label: string }[] }
export interface InboxAccountRow { id: string; label: string; kind: string; ready: boolean; why: string; message: string;
  scanned: number; archive?: number; keep?: number }
export interface InboxPlan {
  ok: boolean; error?: string; id: string; token: string; organize: boolean; kind?: string;
  archive_total: number; label_total: number; keep_total: number; scanned: number;
  groups: InboxGroup[]; kept: { reason: string; title: string; count: number }[];
  labels: { label: string; count: number; archived: number }[];
  accounts: InboxAccountRow[]; needs: InboxAccountRow[]; errors: Record<string, string>; say: string;
}
export interface InboxRun { id: string; kind: string; status: string; created: number; finished?: number | null;
  summary: { archived?: number; labeled?: number; total?: number; say?: string } }
export interface InboxState { ok: boolean; permissions: Record<string, InboxPerm>; planning: boolean; running: string;
  last_run: InboxRun | null; undo_run: InboxRun | null; permission_waiting: string }
export interface InboxApi {
  inbox_state(): Promise<InboxState>;
  inbox_plan(accounts: string[], organize: boolean): Promise<{ ok: boolean; started?: boolean; error?: string }>;
  inbox_approve(planId: string, token: string): Promise<{ ok: boolean; error?: string; run?: string; total?: number }>;
  inbox_cancel(planId: string): Promise<{ ok: boolean }>;
  inbox_stop(): Promise<{ ok: boolean }>;
  inbox_undo(runId?: string): Promise<{ ok: boolean; error?: string; run?: string }>;
  inbox_allow(account: string, filters: boolean): Promise<{ ok: boolean; error?: string; started?: boolean; already?: boolean }>;
  inbox_allow_cancel(): Promise<{ ok: boolean }>;
}

const GROUP_ICON: Record<string, string> = { promotions: "🏷", newsletters: "📰", notifications: "🔔", unsubscribed: "📭", receipts: "🧾" };
const KEEP_ICON: Record<string, string> = { contact: "🧑", person: "🧑", bank: "🏦", deadline: "⏰", starred: "⭐", important: "❗",
  school: "🎓", receipt: "🧾", security: "🔐", todo: "📝", recent: "🔔", unsure: "🤔", instagram: "📷", suspicious: "🚩" };

let api: Api & InboxApi;
let dlg: HTMLDialogElement | null = null;
let st: InboxState | null = null;
let plan: InboxPlan | null = null;
let stage: "start" | "scanning" | "plan" | "running" | "done" | "undone" = "start";
let accounts: string[] = [];
let organize = false;
let prog = { done: 0, total: 0, undo: false };
let result: any = null;
const perm: Record<string, { stage: string; url?: string; message?: string }> = {};

export function initInbox(a: Api) { api = a as Api & InboxApi; }

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

/** "Allow Monkey to tidy this inbox": what it can do, what Google's screen will say, and the button. */
function permissionCard(acct: string, label: string): HTMLElement {
  const p = perm[acct] ?? { stage: "" };
  const card = h("section", { class: "ib-perm", "data-acct": acct, role: "group", "aria-label": `Allow Monkey to tidy ${label}` },
    h("h4", {}, `🔑 Allow Monkey to tidy “${label}”`),
    h("ul", { class: "ib-can" },
      h("li", { class: "ok" }, "✓ Archive emails (they stay searchable in All Mail) and add labels"),
      h("li", { class: "no" }, "✗ Never deletes, never sends, never empties anything"),
      h("li", { class: "meta" }, "Asked once for this inbox. Google's page words it broadly (“read, compose and send email”): that's the name of the permission, not what Monkey does with it. If Google says the app isn't verified, that's your own Monkey project: Advanced → Go to it.")));
  const row = h("div", { class: "row" });
  if (p.stage === "opening") {
    row.append(h("span", { class: "meta" }, "Finish it in the browser…"),
      p.url ? h("button", { type: "button", class: "ghost mini", onclick: () => window.open(p.url, "_blank") }, "Open the Google page") : "",
      h("button", { type: "button", class: "ghost mini", onclick: async () => { await api.inbox_allow_cancel(); } }, "Cancel"));
  } else if (p.stage === "done" || st?.permissions[acct]?.archive) {
    row.append(h("span", { class: "ib-ok" }, "✓ Allowed: Monkey can tidy this inbox"));
  } else {
    row.append(h("button", { type: "button", class: "primary", onclick: async () => {
      perm[acct] = { stage: "opening" }; draw();
      const r = await api.inbox_allow(acct, false);
      if (!r.ok) { perm[acct] = { stage: "error", message: r.error }; draw(); }
      else if (r.already) { perm[acct] = { stage: "done" }; await refreshState(); }
    } }, "Allow in Google"));
    if (p.stage === "error") row.append(h("span", { class: "bad" }, `⚠ ${p.message ?? "That didn't work."}`));
    if (p.stage === "cancelled") row.append(h("span", { class: "meta" }, "Cancelled. Nothing changed."));
  }
  card.append(row);
  return card;
}

function rulesLine(): HTMLElement {
  return h("p", { class: "ib-rules" },
    h("b", {}, "Monkey checks each email first. "),
    "He archives (never deletes) promotions, newsletters and old notifications. ",
    h("b", {}, "Always stays: "),
    "people you talk to, starred or important, banks, school, recent receipts and sign-in codes, upcoming deadlines, anything on your to-do list. When he isn't sure, it stays.");
}

function startView(): (HTMLElement | string)[] {
  const perms = Object.entries(st?.permissions ?? {});
  const pick = h("div", { class: "ib-accts", role: "group", "aria-label": "Which inbox" },
    h("button", { type: "button", class: `ghost mini ${accounts.length ? "" : "on"}`, onclick: () => { accounts = []; draw(); } }, "All inboxes"),
    ...perms.map(([id, p]) => h("button", { type: "button", class: `ghost mini ${accounts.includes(id) ? "on" : ""}`,
      onclick: () => { accounts = [id]; draw(); } }, `✉ ${p.label}`)));
  const org = h("input", { type: "checkbox", checked: organize }) as HTMLInputElement;
  org.addEventListener("change", () => { organize = org.checked; });
  const go = h("button", { type: "button", class: "primary", disabled: !perms.length, onclick: () => void makePlan() },
    "Make a plan");
  const undo = st?.undo_run;
  return [
    h("p", { class: "meta" }, perms.length ? "Pick an inbox (or all). Making a plan only reads: nothing changes until you approve it."
      : "No inbox is connected yet. Connect one in Settings → Accounts."),
    pick, rulesLine(),
    h("label", { class: "field toggle" }, org, h("span", {}, h("b", {}, "Also organize"),
      h("small", {}, " Labels mail as Newsletters, Receipts, School or Notifications (Outlook: categories). Labels never move anything."))),
    h("div", { class: "row" }, go),
    undo ? h("p", { class: "meta ib-last" }, `Last cleanup: ${undo.summary.say ?? ""} `,
      h("button", { type: "button", class: "ghost mini", onclick: () => void doUndo(undo.id) }, "Undo it")) : "",
  ];
}

function planView(p: InboxPlan): (HTMLElement | string)[] {
  const ready = p.accounts.filter((a) => a.ready || st?.permissions[a.id]?.archive);
  const readyIds = new Set(ready.map((a) => a.id));
  const canRun = p.accounts.filter((a) => readyIds.has(a.id)).reduce((n, a) => n + (a.archive ?? 0), 0);
  const asked = p.needs.filter((a) => a.why === "needs_permission");     // stays on screen (with ✓) once allowed
  const blocked = asked.filter((a) => !readyIds.has(a.id));
  const groups = h("div", { class: "ib-groups" }, ...p.groups.map((g) => h("div", { class: "ib-group", "data-group": g.group },
    h("div", { class: "ib-ghead" }, h("span", { class: "ib-gicon", "aria-hidden": "true" }, GROUP_ICON[g.group] ?? "📦"),
      h("b", { class: "ib-count" }, String(g.count)), h("span", {}, g.title), g.label ? h("span", { class: "ib-label" }, `🏷 ${g.label}`) : ""),
    h("ul", { class: "ib-ex", title: "Example subjects (from the emails)" }, ...g.examples.map((e) =>
      h("li", {}, h("q", {}, e.subject), h("small", {}, ` · ${e.sender}${p.accounts.length > 1 ? ` · ✉ ${e.account_label}` : ""}`)))))));
  const kept = h("section", { class: "ib-kept", "aria-label": "Stays in your inbox" },
    h("h4", {}, `Stays in your inbox (${p.keep_total})`),
    h("ul", {}, ...p.kept.map((k) => h("li", { "data-reason": k.reason }, h("span", { "aria-hidden": "true" }, KEEP_ICON[k.reason] ?? "•"),
      h("b", {}, String(k.count)), ` ${k.title}`))));
  const labelLine = p.organize && p.labels.length ? h("p", { class: "meta ib-labels" }, "Labels: ",
    ...p.labels.map((l) => h("span", { class: "ib-label" }, `🏷 ${l.label} · ${l.count}`))) : "";
  const label = p.organize && p.label_total && !blocked.length ? ` and label ${p.label_total}` : "";
  // the plan counts every inbox; the button only what can go now (inboxes still waiting for "Allow" are named)
  const waiting = blocked.reduce((n, a) => n + (p.accounts.find((x) => x.id === a.id)?.archive ?? 0), 0);
  const waitingNote = waiting ? ` now (${waiting} more after you allow ${blocked.map((a) => `"${a.label}"`).join(", ")})` : "";
  const approve = h("button", { type: "button", class: "primary ib-go", disabled: !canRun && !(p.organize && p.label_total && ready.length),
    onclick: async () => {
      approve.setAttribute("disabled", "");
      const r = await api.inbox_approve(p.id, p.token);
      if (!r.ok) { toast(`⚠ ${r.error}`); approve.removeAttribute("disabled"); return; }
      stage = "running"; prog = { done: 0, total: r.total ?? 0, undo: false }; draw();
    } }, canRun ? `Archive ${plural(canRun, "email")}${label}${waitingNote}` : blocked.length ? "Allow Monkey to tidy this inbox first" : "Nothing to archive");
  return [
    h("p", { class: "ib-say", role: "status" }, p.say),
    ...Object.entries(p.errors ?? {}).map(([a, e]) => h("p", { class: "meta warn" }, `⚠ ${a}: ${e}`)),
    ...p.needs.filter((a) => a.why !== "needs_permission").map((a) => h("p", { class: "meta warn" }, `⚠ ${a.label}: ${a.message}`)),
    ...asked.map((a) => permissionCard(a.id, a.label)),
    p.groups.length ? h("section", { class: "ib-plan", "aria-label": "What Monkey will archive" },
      h("h4", {}, `Archive (${p.archive_total})`, h("small", { class: "meta" }, " · moved out of the inbox, never deleted")), groups) : "",
    labelLine, kept,
    h("p", { class: "meta" }, "Pressing the button approves exactly this plan, once. You can Stop any time, and Undo puts everything back."),
    h("div", { class: "row ib-foot" }, approve,
      h("button", { type: "button", class: "ghost", onclick: async () => { await api.inbox_cancel(p.id); plan = null; stage = "start"; draw(); } }, "Back")),
  ];
}

function runView(): HTMLElement[] {
  const pct = prog.total ? Math.round((prog.done / prog.total) * 100) : 0;
  const bar = h("div", { class: "ib-bar" }, h("i", { style: `width:${pct}%` }));
  return [
    h("div", { class: "ib-progress", role: "status" },
      h("span", {}, prog.undo ? `Putting emails back: ${prog.done} of ${prog.total}…` : `Archiving: ${prog.done} of ${prog.total}…`), bar,
      h("button", { type: "button", class: "ghost mini danger", onclick: async () => { await api.inbox_stop(); toast("Stopping: no further batch will start."); } }, "■ Stop")),
  ];
}

function doneView(): (HTMLElement | string)[] {
  const r = result ?? {};
  const failed = Object.entries(r.failed ?? r.problems ?? {}) as [string, string][];
  if (stage === "undone") return [
    h("p", { class: "ib-result ok", role: "status" }, `↩ ${r.say ?? "Put them back."}`),
    h("div", { class: "row" }, h("button", { type: "button", class: "primary", onclick: () => { stage = "start"; plan = null; void refreshState(); } }, "Done")),
  ];
  return [
    h("p", { class: `ib-result ${r.status === "done" ? "ok" : "warn"}`, role: "status" }, r.status === "done" ? `✓ ${r.say}` : `■ ${r.say}`),
    h("div", { class: "ib-tiles" },
      h("div", { class: "ib-tile" }, h("b", {}, String(r.archived ?? 0)), h("small", {}, "archived")),
      h("div", { class: "ib-tile" }, h("b", {}, String(r.labeled ?? 0)), h("small", {}, "labeled"))),
    ...failed.filter(([, v]) => v).map(([a, v]) => h("p", { class: "meta warn" }, `⚠ ${a}: ${v}`)),
    h("div", { class: "row" },
      r.undo ? h("button", { type: "button", class: "ghost ib-undo", onclick: () => void doUndo(r.run) }, "↩ Undo") : "",
      h("button", { type: "button", class: "primary", onclick: () => dlg?.close() }, "Done")),
  ];
}

async function doUndo(runId: string) {
  const r = await api.inbox_undo(runId);
  if (!r.ok) { toast(`⚠ ${r.error}`); return; }
  stage = "running"; prog = { done: 0, total: 0, undo: true }; draw();
}

function draw() {
  if (!dlg) return;
  const head = h("div", { class: "taskstop" }, h("h3", {}, "🧹 Inbox cleanup"),
    h("button", { type: "button", class: "ghost mini", "aria-label": "Close", onclick: () => dlg!.close() }, "✕"));
  let body: (HTMLElement | string)[];
  if (stage === "scanning") body = [h("p", { class: "ib-scan", role: "status" }, "Checking your inbox… (subjects and senders only; nothing changes yet)"), rulesLine()];
  else if (stage === "plan" && plan) body = planView(plan);
  else if (stage === "running") body = runView();
  else if (stage === "done" || stage === "undone") body = doneView();
  else body = startView();
  dlg.dataset.stage = stage;
  dlg.replaceChildren(head, ...body);
  if (stage === "plan") {
    stagger(dlg.querySelectorAll(".ib-group, .ib-kept li"));
    dlg.querySelectorAll(".ib-perm").forEach((c) => attention(c));      // a permission step appears at once, then wobbles
  }
  if (stage === "done" || stage === "undone") pop(dlg.querySelector(".ib-result"));
}

async function refreshState() {
  try { st = await api.inbox_state(); } catch { /* keep the last */ }
  if (st?.running && stage !== "running") stage = "running";
  draw();
}

async function makePlan() {
  const r = await api.inbox_plan(accounts, organize);
  if (!r.ok) { toast(`⚠ ${r.error}`); return; }
  stage = "scanning"; draw();
}

/** Open the panel. Monkey (the brain) opens it with a plan already being made; the owner still approves. */
export async function openInbox(opts: { accounts?: string[]; organize?: boolean; scanning?: boolean } = {}) {
  if (!dlg) { dlg = h("dialog", { id: "inboxDlg", class: "tasksdlg ibdlg" }) as HTMLDialogElement; document.body.append(dlg); }
  if (opts.accounts) accounts = opts.accounts;
  if (opts.organize !== undefined) organize = opts.organize;
  if (opts.scanning) stage = "scanning";
  else if (stage !== "running" && stage !== "scanning") { stage = plan ? "plan" : "start"; }
  await refreshState();
  if (!dlg.open) { dlg.showModal(); enter(dlg, "pop"); }
}

/** Backend events: inbox_cleanup_open / inbox_plan / inbox_permission / inbox_progress / inbox_done / inbox_undone. */
export function inboxEvent(name: string, p: any) {
  switch (name) {
    case "inbox_cleanup_open": void openInbox({ accounts: p.accounts ?? [], organize: !!p.organize, scanning: true }); return;
    case "inbox_plan":
      if (p.stage === "scanning") stage = "scanning";
      else if (p.stage === "ready") { plan = p as InboxPlan; stage = "plan"; }
      else if (p.stage === "error") { stage = "start"; toast(`⚠ ${p.error ?? "Couldn't check the inbox."}`, 6000); }
      break;
    case "inbox_permission":
      perm[p.account] = { stage: p.stage, url: p.url, message: p.message };
      if (p.stage === "done") { if (st && p.permissions) st.permissions = p.permissions; toast("✓ Monkey can tidy that inbox now (archive and label only)."); }
      break;
    case "inbox_progress": {
      const before = prog.done;
      prog = { done: p.done ?? 0, total: p.total ?? prog.total, undo: !!p.undo };
      if (stage === "running" && dlg?.querySelector(".ib-bar i")) {
        const bar = dlg.querySelector<HTMLElement>(".ib-bar i")!;
        const w = bar.parentElement!.clientWidth;
        const from = before ? bar.getBoundingClientRect().width : 0;
        bar.style.width = `${Math.round((prog.done / Math.max(1, prog.total)) * 100)}%`;
        moveBar(bar, from, (prog.done / Math.max(1, prog.total)) * w);
        const label = dlg.querySelector(".ib-progress span");
        if (label) label.textContent = prog.undo ? `Putting emails back: ${prog.done} of ${prog.total}…` : `Archiving: ${prog.done} of ${prog.total}…`;
        return;
      }
      break;
    }
    case "inbox_done": result = p; stage = "done"; plan = null; toast(p.say ?? "Finished.", 6000); void refreshState(); return;
    case "inbox_undone": result = p; stage = "undone"; toast(p.say ?? "Put them back.", 5000); void refreshState(); return;
    default: return;
  }
  draw();
}

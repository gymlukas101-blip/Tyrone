// "Mailing lists": the review list of newsletters and promos found in the owner's inboxes (list headers only), and
// the approval of exactly what unsubscribing will do, per list. Nothing is sent, posted or opened until the owner
// presses "Unsubscribe from these N" on the review screen; Monkey (the brain) can only pre-select.
// Sender names and subjects come from emails: shown as text, never acted on.
import type { Api } from "./bridge";
import { h, toast } from "./dom";
import "./mailinglists.css";

export interface MailingList {
  id: string; account: string; account_label: string; sender: string; sender_email: string; list_id: string;
  subject: string; count_90d: number; unread_90d: number; last_received: number | null; status: string;
  method_used: string; result: string; result_at: number | null; verify_after: number | null; verify_status: string;
  last_after: number | null; draft_id: string; task_id: string; screenshot: string; methods: string[];
}
export interface MailingSuggestion { id: string; sender: string; per_month: number; unread_pct: number; say: string }
export interface MailingState {
  ok?: boolean; lists: MailingList[]; suggestions: MailingSuggestion[]; scanning: boolean;
  last_scan: { ts?: number; lists?: number; messages?: number; errors?: Record<string, string> };
  computer_tasks: boolean; archive_available: boolean; running: string;
}
export interface MailingStep { list_id: string; account: string; account_label: string; sender: string; method: string;
  method_label: string; target: string; what: string }
export interface MailingBatch { id: string; status: string; token?: string; items: MailingStep[] }
export interface MailingApi {
  mailing_state(): Promise<MailingState>;
  mailing_scan(): Promise<{ ok: boolean; started?: boolean; error?: string }>;
  mailing_prepare(ids: string[]): Promise<{ ok: boolean; error?: string } & Partial<MailingBatch>>;
  mailing_run(batchId: string, token: string): Promise<{ ok: boolean; error?: string; batch?: MailingBatch }>;
  mailing_cancel(batchId: string): Promise<{ ok: boolean }>;
  mailing_keep(id: string, keep: boolean): Promise<{ ok: boolean; error?: string; item?: MailingList }>;
  mailing_stop(): Promise<{ ok: boolean }>;
  mailing_open(id: string): Promise<{ ok: boolean; error?: string }>;
}

const METHOD: Record<string, [string, string]> = {
  one_click: ["⚡ One-click", "The list supports one-click unsubscribe: Monkey sends one request, no cookies or personal data."],
  mailto: ["✉ Email", "The list unsubscribes by email: Monkey drafts it in the right account; you press Send."],
  web: ["🌐 Web page", "The list only has an unsubscribe page: Monkey opens it in his browser and presses only Unsubscribe."],
  manual: ["✋ Manual", "No usable unsubscribe address in the list's headers."],
};
const STATUS: Record<string, string> = {
  queued: "⏳ Queued", waiting_send: "✉ Draft ready: press Send", needs_manual: "✋ Needs you", failed: "⚠ Didn't work",
  kept: "Kept",
};

let api: Api & MailingApi;
let st: MailingState | null = null;
const picked = new Set<string>();
let acctFilter = "";
let review: MailingBatch | null = null;
let progress = "";
let dlg: HTMLDialogElement | null = null;

export function initMailing(a: Api) { api = a as Api & MailingApi; }

const day = (ts: number | null) => {
  if (!ts) return "";
  const d = Math.round((Date.now() / 1000 - ts) / 86400);
  return d <= 0 ? "today" : d === 1 ? "yesterday" : d < 30 ? `${d} days ago` : new Date(ts * 1000).toLocaleDateString();
};
const best = (l: MailingList) => l.methods[0] ?? "manual";

function statusCell(l: MailingList): HTMLElement {
  if (l.status === "done") {
    const v = l.verify_status === "quiet" ? "✓ Quiet since"
      : l.verify_status === "still_arriving" ? "⚠ Still arriving after" : "✓ Unsubscribed ·";
    const when = l.verify_status === "waiting" && l.verify_after
      ? `checking for new mail until ${new Date(l.verify_after * 1000).toLocaleDateString()}` : day(l.result_at);
    return h("span", { class: `ml-st ${l.verify_status === "still_arriving" ? "bad" : "ok"}`, title: l.result },
      `${v} ${when}`.trim());
  }
  if (l.status === "active") return h("span", { class: "ml-st" }, "");
  return h("span", { class: `ml-st ${l.status === "failed" ? "bad" : l.status === "needs_manual" ? "warn" : ""}`,
    title: l.result }, STATUS[l.status] ?? l.status);
}

function row(l: MailingList): HTMLElement {
  const open = l.status === "active" || l.status === "needs_manual" || l.status === "failed";
  const box = h("input", { type: "checkbox", checked: picked.has(l.id), disabled: !open,
    "aria-label": `Select ${l.sender}` }) as HTMLInputElement;
  box.addEventListener("change", () => { box.checked ? picked.add(l.id) : picked.delete(l.id); draw(); });
  const m = METHOD[best(l)] ?? METHOD.manual;
  const unread = l.count_90d ? Math.round((l.unread_90d / l.count_90d) * 100) : 0;
  const keep = h("button", { type: "button", class: "ghost mini", title: l.status === "kept" ? "Show it in suggestions again" : "Keep this list (Monkey stops suggesting it)",
    onclick: async () => { const r = await api.mailing_keep(l.id, l.status !== "kept"); if (!r.ok) toast(`⚠ ${r.error}`); else await refresh(); } },
    l.status === "kept" ? "Unkeep" : "Keep");
  const extra: (HTMLElement | string)[] = [];
  if (l.status === "needs_manual" && l.methods.includes("web")) extra.push(h("button", { type: "button", class: "ghost mini",
    title: "Open the list's own unsubscribe page (from its List-Unsubscribe header) in your browser",
    onclick: async () => { const r = await api.mailing_open(l.id); if (!r.ok) toast(`⚠ ${r.error}`); } }, "Open page"));
  return h("tr", { "data-id": l.id, class: `ml-row s-${l.status}` },
    h("td", {}, box),
    h("td", { class: "ml-who" }, h("b", {}, l.sender || l.sender_email),
      h("small", {}, l.list_id || l.sender_email), l.subject ? h("small", { class: "ml-subj", title: "Latest subject (from the email)" }, `“${l.subject}”`) : ""),
    h("td", {}, h("span", { class: "ml-acct" }, `✉ ${l.account_label}`)),
    h("td", { class: "num" }, h("b", {}, String(l.count_90d)), h("small", {}, `${unread}% unopened`)),
    h("td", {}, day(l.last_received)),
    h("td", {}, h("span", { class: `ml-method m-${best(l)}`, title: m[1] }, m[0])),
    h("td", {}, statusCell(l), ...extra),
    h("td", {}, l.status === "active" || l.status === "kept" ? keep : ""));
}

function reviewView(b: MailingBatch): HTMLElement {
  const n = b.items.length;
  const go = h("button", { type: "button", class: "primary", onclick: async () => {
    go.setAttribute("disabled", "");
    const r = await api.mailing_run(b.id, b.token ?? "");
    if (!r.ok) { toast(`⚠ ${r.error}`); go.removeAttribute("disabled"); return; }
    for (const s of b.items) picked.delete(s.list_id);
    review = null; progress = `Unsubscribing: 0 of ${n} done…`;
    await refresh();
  } }, `Unsubscribe from ${n === 1 ? "this one" : `these ${n}`}`);
  return h("section", { class: "ml-review", "aria-label": "What will happen" },
    h("h4", {}, "Exactly what Monkey will do"),
    h("p", { class: "meta" }, "Unsubscribing reaches out to each list, so it needs your OK. Pressing the button approves exactly these steps, once."),
    h("ol", { class: "ml-steps" }, ...b.items.map((s) => h("li", { "data-id": s.list_id },
      h("div", {}, h("b", {}, s.sender), " ", h("span", { class: `ml-method m-${s.method}` }, METHOD[s.method]?.[0] ?? s.method_label),
        h("small", { class: "ml-acct" }, ` ✉ ${s.account_label}`)),
      h("p", { class: "meta" }, s.what)))),
    h("label", { class: "field toggle off", title: "Needs a broader Gmail permission than Monkey has; off until you decide" },
      h("input", { type: "checkbox", disabled: true }),
      h("span", {}, "Also archive their old emails and filter new ones ", h("small", {}, "(not available: it would need extra Gmail permission to change your account)"))),
    h("div", { class: "row" }, go,
      h("button", { type: "button", class: "ghost", onclick: async () => { await api.mailing_cancel(b.id); review = null; draw(); } }, "Back")));
}

function draw() {
  if (!dlg || !st) return;
  const lists = st.lists.filter((l) => !acctFilter || l.account === acctFilter);
  const accts = [...new Map(st.lists.map((l) => [l.account, l.account_label])).entries()];
  const errs = Object.entries(st.last_scan?.errors ?? {});
  const sugg = st.suggestions.filter((s) => st!.lists.some((l) => l.id === s.id && l.status === "active"));
  const head = h("div", { class: "taskstop" }, h("h3", {}, "📭 Mailing lists"),
    h("button", { type: "button", class: "ghost mini", "aria-label": "Close", onclick: () => dlg!.close() }, "✕"));
  const scanBtn = h("button", { type: "button", class: "ghost mini", disabled: st.scanning, onclick: async () => {
    const r = await api.mailing_scan(); if (!r.ok) toast(`⚠ ${r.error}`); else { st!.scanning = true; draw(); } } },
    st.scanning ? "Checking your inboxes…" : "Check inboxes again");
  const body: (HTMLElement | string)[] = [
    h("p", { class: "meta" }, "From the list headers of the last 90 days (never the email text). Pick the ones you want gone; nothing happens until you approve on the next screen."),
    h("div", { class: "row ml-tools" },
      h("div", { class: "ml-filter", role: "group", "aria-label": "Inbox" },
        h("button", { type: "button", class: `ghost mini ${acctFilter ? "" : "on"}`, onclick: () => { acctFilter = ""; draw(); } }, "All inboxes"),
        ...accts.map(([id, label]) => h("button", { type: "button", class: `ghost mini ${acctFilter === id ? "on" : ""}`,
          onclick: () => { acctFilter = id; draw(); } }, label))),
      scanBtn),
    ...errs.map(([a, e]) => h("p", { class: "meta warn" }, `⚠ ${a}: ${e}`)),
  ];
  if (st.running || progress) body.push(h("div", { class: "ml-progress", role: "status" }, h("span", {}, progress || "Unsubscribing…"),
    h("button", { type: "button", class: "ghost mini danger", onclick: async () => { await api.mailing_stop(); toast("Stopped: nothing else will be unsubscribed."); } }, "■ Stop")));
  if (review) body.push(reviewView(review));
  else {
    if (sugg.length) body.push(h("section", { class: "ml-sugg" }, h("h4", {}, "🍌 Monkey's picks"),
      h("ul", {}, ...sugg.map((s) => h("li", {}, s.say))),
      h("button", { type: "button", class: "ghost mini", onclick: () => { for (const s of sugg) picked.add(s.id); draw(); } }, "Select these")));
    body.push(lists.length ? h("table", { class: "ml-table" },
      h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", {}, "Sender / list"), h("th", {}, "Inbox"), h("th", {}, "Last 90 days"),
        h("th", {}, "Last email"), h("th", {}, "How"), h("th", {}, "Status"), h("th", {}, ""))),
      h("tbody", {}, ...lists.map(row)))
      : h("p", { class: "meta" }, st.scanning ? "Reading list headers…" : "No mailing lists found yet. Connect an inbox in Settings → Accounts, then Check inboxes."));
    const n = [...picked].filter((id) => st!.lists.some((l) => l.id === id)).length;
    const next = h("button", { type: "button", class: "primary", disabled: !n || !!st.running, onclick: async () => {
      const r = await api.mailing_prepare([...picked]);
      if (!r.ok || !r.items) { toast(`⚠ ${r.error ?? "Couldn't prepare that"}`); return; }
      review = r as MailingBatch; draw();
    } }, n ? `Review & unsubscribe (${n})` : "Pick lists to unsubscribe from");
    body.push(h("div", { class: "row ml-foot" }, next,
      st.computer_tasks ? "" : h("small", { class: "meta" }, "Lists that only have a web page need computer tasks on (🖐 Tasks); otherwise they're marked “Needs you”.")));
  }
  dlg.replaceChildren(head, ...body);
}

async function refresh() {
  try { st = await api.mailing_state(); } catch { /* keep the last state */ }
  draw();
}

/** Open the panel. `select` pre-ticks lists (Monkey's proposal); the owner still reviews and approves. */
export async function openMailing(select: string[] = []) {
  if (!dlg) { dlg = h("dialog", { id: "mailDlg", class: "tasksdlg mldlg" }) as HTMLDialogElement; document.body.append(dlg); }
  for (const id of select) picked.add(id);
  review = null;
  await refresh();
  if (!dlg.open) dlg.showModal();
  if (st && !st.lists.length && !st.scanning) { const r = await api.mailing_scan(); if (r.ok) { st.scanning = true; draw(); } }
}

/** Backend events: mailing_lists / mailing_review / mailing_scan / mailing_progress / mailing_item / mailing_done. */
export function mailingEvent(name: string, p: any) {
  switch (name) {
    case "mailing_lists": st = p as MailingState; break;
    case "mailing_review": void openMailing(p.ids ?? []); return;
    case "mailing_scan": if (st) st.scanning = p.stage !== "done"; if (p.stage === "reading") progress = ""; break;
    case "mailing_progress": progress = `Unsubscribing: ${p.index} of ${p.total} done · now ${p.sender}…`; if (st) st.running = p.batch; break;
    case "mailing_item": if (st) st.lists = st.lists.map((l) => (l.id === p.item?.id ? { ...l, ...p.item } : l)); break;
    case "mailing_done": {
      progress = ""; if (st) st.running = "";
      const items = (p.items ?? []) as MailingList[];
      const done = items.filter((i) => i.status === "done").length;
      const drafts = items.filter((i) => i.status === "waiting_send").length;
      const manual = items.filter((i) => i.status === "needs_manual" || i.status === "failed").length;
      toast([done ? `✓ Unsubscribed from ${done}` : "", drafts ? `${drafts} draft(s) waiting for Send` : "", manual ? `${manual} need you` : ""]
        .filter(Boolean).join(" · ") || "Finished.", 6000);
      void refresh();
      return;
    }
    default: return;
  }
  draw();
}

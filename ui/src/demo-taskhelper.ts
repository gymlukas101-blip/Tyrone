// Browser demo mode (?demo) for the task helper: a general task in the HUD and the Mailing lists panel. Made-up sites
// and senders; nothing here touches a real inbox or website.
import type { AutoState, AutoTask } from "./bridge";
import type { MailingBatch, MailingList, MailingState, MailingStep } from "./mailinglists";

/** A general task: plans, fills a form, then stops at Submit and asks (the approval card shows what it does). */
export function demoGeneralTask(t: AutoTask, template: string, st: AutoState, emit: (e: [string, any][]) => void,
                                later: (ms: number, fn: () => void) => void) {
  Object.assign(t, { skill: "general", template, note: "Deciding the next step…", state: "PLANNING" });
  const ev = (e: Record<string, unknown>) => emit([["computer_event", { task_id: t.id, ts: Date.now() / 1000, t: 0, ...e }]]);
  const push = (avatar: string, approvals: unknown[] = []) =>
    emit([["automation", { task: { ...t }, avatar, control: ["RUNNING", "WAITING", "VERIFYING"].includes(t.state), approvals }]]);
  const ap = { id: "ap_demo", task_id: t.id, summary: 'click button "Submit application"', risk: "high", status: "pending",
               token: "demo", kind: "submit" };
  const steps: [number, () => void][] = [
    [300, () => { ev({ ev: "MODEL_CALL" }); ev({ ev: "PLAN_UPDATED", subgoal: "Fill in name and email on the sign-up form" }); }],
    [700, () => { Object.assign(t, { state: "RUNNING", note: "Fill in name and email on the sign-up form",
      usage: { actions: 2, model_calls: 1, usd: 0.006, elapsed_s: 3 } }); push("working");
      ev({ ev: "BROWSER_NAVIGATED", backend: "browser", url: "https://clubs.example.org/join" });
      ev({ ev: "ACTION_VERIFIED", op: "type_text", backend: "browser", role: "textbox", name: "Full name", stage: "verified" });
      ev({ ev: "ACTION_VERIFIED", op: "type_text", backend: "browser", role: "textbox", name: "Email", stage: "verified" }); }],
    [1300, () => { ev({ ev: "ACTION_FAILED", op: "click", backend: "browser", role: "link", name: "Change password", error: "refused",
      detail: "passwords and security settings are yours to change" });
      ev({ ev: "ACTION_FAILED", op: "click", backend: "browser", role: "button", name: "Submit application", error: "needs_approval",
        detail: "this sends, submits, buys, deletes or changes something" });
      ev({ ev: "USER_INPUT_NEEDED", message: 'May I click button "Submit application"?' });
      Object.assign(t, { state: "NEEDS_INPUT", note: 'May I click button "Submit application"?',
        pending: { kind: "approval", approval_id: ap.id, message: 'May I click button "Submit application"? The form is filled in: review it in the browser first if you like.' },
        usage: { actions: 3, model_calls: 2, usd: 0.011, elapsed_s: 6 } });
      st.approvals = [ap]; push("help", [ap]); }],
  ];
  for (const [ms, fn] of steps) later(ms, fn);
  return { ok: true, task: t };
}

/** The per-inbox "tidy" permission in demo mode, shared by the inbox cleanup and the Mailing lists review. */
const DEMO_PERMS: Record<string, any> = {
  gmail: { kind: "gmail", label: "Personal", archive: false, filter: false, why: "needs_permission" },
  "gmail-2": { kind: "gmail", label: "Gaming", archive: true, filter: false, why: "" },
  outlook: { kind: "outlook", label: "School", archive: true, filter: false, why: "", note: "Only while Outlook is open." },
};

export function demoMailingApi(emit: (e: [string, any][]) => void, later: (ms: number, fn: () => void) => void) {
  const now = Date.now() / 1000;
  const L = (id: string, sender: string, email: string, list: string, subject: string, count: number, unread: number,
             daysAgo: number, methods: string[], account = "gmail", label = "Personal", extra: Partial<MailingList> = {}): MailingList => ({
    id, account, account_label: label, sender, sender_email: email, list_id: list, subject, count_90d: count, unread_90d: unread,
    last_received: now - daysAgo * 86400, status: "active", method_used: "", result: "", result_at: null, verify_after: null,
    verify_status: "", last_after: null, draft_id: "", task_id: "", screenshot: "", methods, ...extra });
  const lists: MailingList[] = [
    L("ml_daily", "The Daily Byte", "digest@dailybyte.example", "digest.dailybyte.example", "5 stories you missed this week", 88, 86, 0, ["one_click", "web"]),
    L("ml_snack", "SnackBox Deals", "deals@snackbox.example", "", "🔥 48 hours only: 30% off", 41, 41, 1, ["one_click", "web"]),
    L("ml_pixel", "PixelPlay Store", "news@pixelplay.example", "news.pixelplay.example", "New drops for your wishlist", 27, 22, 3, ["mailto"], "gmail-2", "Gaming"),
    L("ml_gear", "Jungle Gear Outlet", "hello@junglegear.example", "", "Your cart misses you", 19, 19, 2, ["web"]),
    L("ml_rec", "Campus Rec Weekly", "rec@campus.example.edu", "rec-weekly.campus.example.edu", "Intramural sign-ups close Friday", 12, 3, 4, ["mailto"], "outlook", "School"),
    L("ml_study", "Study Buddy Tips", "tips@studybuddy.example", "", "3 ways to beat finals stress", 9, 9, 6, [], "gmail", "Personal"),
    L("ml_tix", "Badger Ticket Alerts", "alerts@tix.example", "alerts.tix.example", "Hockey tickets on sale", 6, 1, 8, ["one_click"], "gmail", "Personal",
      { status: "done", method_used: "one_click", result: "the list's server accepted the one-click unsubscribe", result_at: now - 2 * 86400,
        verify_after: now + 5 * 86400, verify_status: "waiting" }),
  ];
  const st: MailingState = {
    lists, scanning: false, running: "", computer_tasks: true, archive_available: true, filter_available: false,
    tidy: DEMO_PERMS,
    skipped: { count: 2, by: { banking: 1, instagram: 1 }, note: "Skipped 2 lists from banks/Instagram (handle those yourself)." },
    last_scan: { ts: now - 600, lists: lists.length, messages: 202, errors: {} },
    suggestions: [
      { id: "ml_daily", sender: "The Daily Byte", per_month: 29, unread_pct: 98, say: "You get about 29 emails a month from The Daily Byte and never open them." },
      { id: "ml_snack", sender: "SnackBox Deals", per_month: 14, unread_pct: 100, say: "You get about 14 emails a month from SnackBox Deals and never open them." },
      { id: "ml_gear", sender: "Jungle Gear Outlet", per_month: 6, unread_pct: 100, say: "You get about 6 emails a month from Jungle Gear Outlet and never open them." },
    ],
  };
  const what: Record<string, (l: MailingList) => [string, string, string]> = {
    one_click: (l) => ["one_click", l.sender_email.split("@")[1], `Monkey sends a one-time unsubscribe request to ${l.sender_email.split("@")[1]} (no cookies, no personal data).`],
    mailto: (l) => ["mailto", `unsubscribe@${l.sender_email.split("@")[1]}`, `Monkey drafts an email to unsubscribe@${l.sender_email.split("@")[1]} (subject “unsubscribe”) from your ${l.account_label} account. It goes out only when you press Send on the draft.`],
    web: (l) => ["web", `www.${l.sender_email.split("@")[1]}`, `Monkey opens www.${l.sender_email.split("@")[1]} in his browser, presses only the Unsubscribe/Confirm button and types only you@example.com if the page asks, and keeps a screenshot of the result.`],
    manual: () => ["manual", "", "Needs a manual step: this list gives no usable unsubscribe address."],
  };
  let batch: MailingBatch | null = null;
  return {
    async mailing_state() { return { ok: true, ...st, lists: st.lists.map((l) => ({ ...l })) }; },
    async mailing_scan() {
      st.scanning = true;
      later(900, () => { st.scanning = false; emit([["mailing_lists", { ...st }]]); });
      return { ok: true, started: true };
    },
    async mailing_prepare(ids: string[], archive = false, filterNew = false) {
      const items: MailingStep[] = ids.map((id) => st.lists.find((l) => l.id === id)).filter((l): l is MailingList => !!l && l.status !== "done")
        .map((l) => { const [method, target, w] = what[l.methods[0] ?? "manual"](l);
          const t = st.tidy?.[l.account];
          const archiveOld = !!(archive && t?.archive), filt = !!(filterNew && t?.filter && l.account !== "outlook");
          return { list_id: l.id, account: l.account, account_label: l.account_label, sender: l.sender, method,
            method_label: method, target, archive_old: archiveOld, filter_new: filt,
            what: w + (archiveOld ? " Then Monkey archives their older emails in this inbox (never deletes; starred, important, receipts and anything else he'd keep stay put)." : "")
              + (filt ? " New mail from this list will skip your inbox (a Gmail filter)." : "") }; });
      if (!items.length) return { ok: false, error: "Nothing to unsubscribe from in that selection." };
      batch = { id: "ub_demo", status: "pending", token: "demo-token", items };
      return { ok: true, ...batch };
    },
    async mailing_run(id: string, token: string) {
      if (!batch || batch.id !== id || token !== "demo-token") return { ok: false, error: "That approval isn't valid any more." };
      const b = batch; batch = null; st.running = b.id;
      b.items.forEach((s, i) => later(700 * (i + 1), () => {
        const l = st.lists.find((x) => x.id === s.list_id)!;
        Object.assign(l, s.method === "mailto" ? { status: "waiting_send", result: "drafted: press Send on the draft card" }
          : s.method === "manual" ? { status: "needs_manual", result: s.what }
          : { status: "done", method_used: s.method, result_at: Date.now() / 1000, verify_after: Date.now() / 1000 + 7 * 86400, verify_status: "waiting" });
        emit([["mailing_progress", { batch: b.id, index: i + 1, total: b.items.length, sender: s.sender }], ["mailing_item", { batch: b.id, item: { ...l } }]]);
        if (i === b.items.length - 1) { st.running = ""; emit([["mailing_done", { batch: b.id, status: "done", items: b.items.map((x) => st.lists.find((y) => y.id === x.list_id)) }]]); }
      }));
      return { ok: true, batch: { ...b, token: undefined } };
    },
    async mailing_cancel() { batch = null; return { ok: true }; },
    async mailing_keep(id: string, keep: boolean) {
      const l = st.lists.find((x) => x.id === id); if (!l) return { ok: false, error: "That list is gone." };
      l.status = keep ? "kept" : "active"; return { ok: true, item: l };
    },
    async mailing_stop() { st.running = ""; return { ok: true }; },
    async mailing_open() { return { ok: false, error: "Demo mode" }; },
    async automation_templates() { return { ok: true, templates: DEMO_TEMPLATES }; },
  };
}

export const DEMO_TEMPLATES = [
  { id: "generic", title: "Anything else", blurb: "Plans with Claude; reads freely, asks before anything that sends, submits, buys, deletes or changes an account.", example: "Download last month's statement PDF from my phone carrier's site", skill: "general", rules: {}, deterministic: false },
  { id: "look_only", title: "Look something up (just show me)", blurb: "Searches and reads; never books, buys, sends or submits anything.", example: "Find the cheapest flight from Madison to Denver on Dec 18, just show me", skill: "general", rules: { read_only: true }, deterministic: false },
  { id: "form_fill", title: "Fill in a form (you review)", blurb: "Fills the fields you give him; he asks before pressing Submit, and you can review first.", example: "Fill in the club sign-up form at example.org with my name and email, let me review", skill: "general", rules: {}, deterministic: false },
  { id: "account_settings", title: "Change a setting on a site (asks every step)", blurb: "A setting, notification, subscription or trial; every change asks you first.", example: "Turn off promotional notifications in my Spotify account settings", skill: "general", rules: { confirm_medium: true }, deterministic: false },
  { id: "shopping", title: "Shopping (stops before paying)", blurb: "Gets things into the cart or booking page; stops before the final purchase.", example: "Put a 2-pack of AA batteries in my Target cart", skill: "general", rules: { confirm_medium: true }, deterministic: false },
  { id: "course", title: "Course modules", blurb: "Canvas or another course site: works through modules and lessons; questions and confirmations stay yours.", example: "Work through the 4 modules of the Title IX training on Canvas", skill: "course", rules: {}, deterministic: false },
];

/** What a goal in the Tasks box becomes (mirrors automation/templates.py panel_for + pick, for the demo only). */
export function demoRoute(objective: string) {
  const t = objective || "";
  if (/\b(instagram|snapchat)\b/i.test(t) && !/unsubscribe|emails? from/i.test(t)) return { ok: true, refusal: "I don't automate Instagram or Snapchat (they don't allow it, and it can get your account locked).", panel: "", template: "" };
  if (/\b(?:(?:clean (?:up|out)|organi[sz]e|tidy(?: up)?|declutter)\s+(?:up\s+)?(?:my |the )?(?:e-?mails?|inbox|gmail|outlook|mail)|archive (?:the |my |old )?(?:newsletters|promos?|promotions|e-?mails|notifications))\b/i.test(t)) return { ok: true, panel: "inbox_cleanup", template: "", refusal: "" };
  if (/\b(unsubscribe|opt (?:me )?out|mailing lists?|newsletters?)\b/i.test(t)) return { ok: true, panel: "mailing_lists", template: "", refusal: "" };
  const pick = /just show me|look up|cheapest|compare/i.test(t) ? "look_only" : /fill (?:in|out)|\bform\b/i.test(t) ? "form_fill"
    : /\b(buy|order|cart|checkout|book (?:a|the|my))\b/i.test(t) ? "shopping"
    : /settings?|notifications?|cancel .{0,30}(?:subscription|trial|membership)|turn (?:on|off)/i.test(t) ? "account_settings" : "generic";
  return { ok: true, panel: "", template: pick, refusal: "" };
}

/** Inbox cleanup in demo mode: three made-up inboxes, one still needing the tidy permission. Nothing real is touched. */
export function demoInboxApi(emit: (e: [string, any][]) => void, later: (ms: number, fn: () => void) => void) {
  const perms = DEMO_PERMS;
  let undoRun: any = null;
  let stopped = false;
  let current: any = null;
  const plan = (accounts: string[], organize: boolean) => {
    const use = (id: string) => !accounts.length || accounts.includes(id);
    const rows = [
      { id: "gmail", label: "Personal", kind: "gmail", scanned: 214, archive: 31, keep: 14 },
      { id: "gmail-2", label: "Gaming", kind: "gmail", scanned: 96, archive: 12, keep: 3 },
      { id: "outlook", label: "School", kind: "outlook", scanned: 120, archive: 5, keep: 11 },
    ].filter((r) => use(r.id)).map((r) => ({ ...r, ready: perms[r.id].archive, why: perms[r.id].why,
      message: perms[r.id].archive ? "" : "Monkey can read this inbox but not tidy it yet. Allow it once (archive and label only, never delete or send)." }));
    const total = rows.reduce((n, r) => n + r.archive, 0);
    const keep = rows.reduce((n, r) => n + r.keep, 0);
    const promo = Math.round(total * 0.5), news = Math.round(total * 0.25), unsub = Math.min(3, total - promo - news);
    const notif = total - promo - news - unsub;
    const ex = (s: string, f: string, a = "Personal") => ({ subject: s, sender: f, account_label: a });
    const people = Math.round(keep * 0.35), school = Math.round(keep * 0.2), receipts = Math.max(0, keep - people - school - 7);
    return {
      ok: true, id: "ic_demo", token: "demo-plan", organize, kind: "cleanup", archive_total: total, keep_total: keep,
      label_total: organize ? total + school : 0, scanned: rows.reduce((n, r) => n + r.scanned, 0),
      groups: [
        { group: "promotions", title: "promotions and ads", count: promo, label: organize ? "Newsletters" : "",
          examples: [ex("🔥 48 hours only: 30% off", "SnackBox Deals"), ex("Your cart misses you", "Jungle Gear Outlet"), ex("New drops for your wishlist", "PixelPlay Store", "Gaming")] },
        { group: "newsletters", title: "newsletters and mailing lists", count: news, label: organize ? "Newsletters" : "",
          examples: [ex("5 stories you missed this week", "The Daily Byte"), ex("3 ways to beat finals stress", "Study Buddy Tips")] },
        { group: "notifications", title: "old notifications", count: notif, label: organize ? "Notifications" : "",
          examples: [ex("[club-site] build passed", "GitHub"), ex("Your weekly activity summary", "FitTrack")] },
        { group: "unsubscribed", title: "from lists you unsubscribed from", count: unsub, label: organize ? "Newsletters" : "",
          examples: [ex("Hockey tickets on sale", "Badger Ticket Alerts")] },
      ].filter((g) => g.count > 0),
      kept: [
        { reason: "contact", title: "from people you talk to", count: people },
        { reason: "school", title: "school mail", count: school },
        { reason: "bank", title: "from your bank or other money senders", count: 3 },
        { reason: "deadline", title: "upcoming deadlines or requests", count: 2 },
        { reason: "starred", title: "starred or flagged", count: 2 },
        { reason: "receipt", title: "recent receipts, orders or travel", count: receipts },
      ].filter((k) => k.count > 0),
      labels: organize ? [{ label: "Newsletters", count: promo + news + unsub, archived: promo + news + unsub },
                          { label: "Notifications", count: notif, archived: notif }, { label: "School", count: school, archived: 0 }] : [],
      accounts: rows, needs: rows.filter((r) => !r.ready), errors: {},
      say: `I can archive ${total} emails: ${promo} promotions, ${news} newsletters and ${notif} old notifications. I'm keeping ${keep}: ${people} from people you talk to, ${school} school emails and 3 from your bank.${rows.some((r) => !r.ready) ? " First, allow me to tidy that inbox (archive and label only)." : ""} Check the plan on screen and press Archive if it looks right.`,
    };
  };
  return {
    async inbox_state() { return { ok: true, permissions: perms, planning: false, running: "", last_run: undoRun, undo_run: undoRun, permission_waiting: "" }; },
    async inbox_plan(accounts: string[], organize: boolean) {
      emit([["inbox_plan", { stage: "scanning" }]]);
      later(700, () => { current = plan(accounts ?? [], !!organize); emit([["inbox_plan", { stage: "ready", ...current }]]); });
      return { ok: true, started: true };
    },
    async inbox_approve(id: string, token: string) {
      if (!current || id !== current.id || token !== current.token) return { ok: false, error: "That approval isn't valid any more. Make a new plan." };
      const total = current.accounts.filter((a: any) => perms[a.id].archive).reduce((n: number, a: any) => n + a.archive, 0);
      current = null; stopped = false;
      let done = 0;
      const step = () => {
        if (stopped || done >= total) {
          undoRun = { id: "run_demo", kind: "cleanup", status: stopped ? "stopped" : "done", created: Date.now() / 1000, summary: { archived: done, labeled: 0, say: `Archived ${done} emails.` } };
          emit([["inbox_done", { run: "run_demo", status: stopped ? "stopped" : "done", archived: done, labeled: 0, total, failed: {}, undo: done > 0,
            say: stopped ? `Stopped. I archived ${done} before you said stop; Undo puts them back.` : `Done: archived ${done} emails. Undo is on screen if you want them back.` }]]);
          return;
        }
        done = Math.min(total, done + 25);
        emit([["inbox_progress", { run: "run_demo", done, total, archived: done }]]);
        later(450, step);
      };
      later(300, step);
      return { ok: true, run: "run_demo", total };
    },
    async inbox_cancel() { current = null; return { ok: true }; },
    async inbox_stop() { stopped = true; return { ok: true }; },
    async inbox_undo() {
      if (!undoRun) return { ok: false, error: "There's no cleanup to undo." };
      const n = undoRun.summary.archived; undoRun = null;
      later(300, () => emit([["inbox_progress", { run: "run_demo", undo: true, done: n, total: n }]]));
      later(700, () => emit([["inbox_undone", { run: "run_demo", restored: n, unlabeled: 0, problems: {}, say: `Put ${n} emails back in your inbox.` }]]));
      return { ok: true, run: "run_demo" };
    },
    async inbox_allow(account: string, filters = false) {
      if (perms[account]?.archive && (!filters || perms[account]?.filter)) return { ok: true, already: true };
      later(200, () => emit([["inbox_permission", { account, stage: "opening", url: "https://accounts.google.com/o/oauth2/auth?demo" }]]));
      later(1200, () => { perms[account] = { ...perms[account], archive: true, filter: perms[account].filter || filters, why: "" }; emit([["inbox_permission", { account, stage: "done", permissions: perms }]]); });
      return { ok: true, started: true };
    },
    async inbox_allow_cancel() { return { ok: true }; },
    async automation_route(objective: string) { return demoRoute(objective); },
  };
}

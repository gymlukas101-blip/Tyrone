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
    lists, scanning: false, running: "", computer_tasks: true, archive_available: false,
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
    async mailing_prepare(ids: string[]) {
      const items: MailingStep[] = ids.map((id) => st.lists.find((l) => l.id === id)).filter((l): l is MailingList => !!l && l.status !== "done")
        .map((l) => { const [method, target, w] = what[l.methods[0] ?? "manual"](l);
          return { list_id: l.id, account: l.account, account_label: l.account_label, sender: l.sender, method,
            method_label: method, target, what: w }; });
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
  { id: "form_fill", title: "Fill in a form (you review it)", blurb: "Fills the fields you give him; he asks before pressing Submit, and you can review first.", example: "Fill in the club sign-up form at example.org with my name and email, let me review", skill: "general", rules: {}, deterministic: false },
  { id: "account_settings", title: "Settings or a subscription on a site", blurb: "Changes a setting, notification or subscription; every change asks you first.", example: "Turn off promotional notifications in my Spotify account settings", skill: "general", rules: { confirm_medium: true }, deterministic: false },
  { id: "shopping", title: "Shopping or booking (stops before paying)", blurb: "Gets things into the cart or booking page; stops before the final purchase.", example: "Put a 2-pack of AA batteries in my Target cart", skill: "general", rules: { confirm_medium: true }, deterministic: false },
  { id: "course", title: "Course modules (Canvas, trainings)", blurb: "Works through modules and lessons; questions and confirmations stay yours.", example: "Work through the 4 modules of the Title IX training on Canvas", skill: "course", rules: {}, deterministic: false },
];

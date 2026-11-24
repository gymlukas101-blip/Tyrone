# Task helper: any task, not just Canvas (audit, permission model, mailing lists)

**Branch:** `feature/task-helper-general` (from `feature/todo-email-accounts`). **Status:** built and tested in the cloud
container (Linux, headless Chromium, fakes for Gmail/Outlook). **Not tried on the owner's Dell, with a live Claude
planner, or with a real inbox.** Nothing was unsubscribed, sent or connected.

The owner asked: *"update Monkey's task helper to be able to do anything, not just canvas assignments. For example it
can unsubscribe from mailing lists for me."*

Builds on [ADR 0001](../adr/0001-computer-agent.md) (durable tasks, the execution-layer permission gate) and
[ADR 0002](../adr/0002-hybrid-computer-use.md) (the `Computer` interface and the `GoalRunner`).

## 1. Audit: what tied the task helper to Canvas

The execution layer was already general. The Canvas assumptions were in the parts around it: the defaults, the copy,
the brain's description of the tool, and a few places that assumed a course result.

| Area | What it assumed | Generalizes as-is? | Change on this branch |
|---|---|---|---|
| Permission gate (`automation/permissions.py`) | Risk from what a control *is* (role, accessible name, input type). Nothing course-specific | **Yes** | Added the hard limits (forbidden sites even with "Any website", password/security controls, more payment-field words), spending as its own stop-and-ask, an approval *kind* for the card, and template rules that only narrow |
| Task model (`automation/tasks.py`) | `skill="course"` default; progress counts `module_complete` checkpoints | Mostly | `template` and `rules` fields (old tasks load unchanged) |
| Course loop (`TaskManager._loop`, `course.py`) | Canvas / Storyline / Rise / Brightspace words, quiz advisor ("a student"), unit tracking, the course overview as proof | No, on purpose | Unchanged; it is now the `course` template. Its tests are untouched and green |
| General loop (`TaskManager._goal_loop`, `computer/goal.py`) | Needs a Claude key; "done" = the planner's quoted evidence; the system prompt didn't mention spending, outward steps or the hard limits | **Yes** | Templates (guidance, skills, a "done" pattern), deterministic templates that run without Claude, a result screenshot, the generalized prompt. Fixed: a step the owner said **no** to was asked a second time |
| Service (`automation/service.py`) | `HELPER_SITES` (Duo, Microsoft login, Instructure, Kaltura, Panopto, YouTube, Vimeo), `.edu` school domain, `skill="course"` default, the demo *course* | Course-only | Helper sites stay course-only. `start()` refuses hard-limit goals first, takes a template, and has `start_template()` for an approved unsubscribe page. The e-stop also stops unsubscribe batches |
| Brain (`brain/tools.py`, `router.py`, `persona.md`) | `propose_computer_task` = "course modules or a required training, routine web forms", "never for sending messages or buying things"; no router task, so these requests went to the classifier or `general` | No | New tool text and `template` argument, `find_mailing_lists`, `propose_unsubscribe`, a `task_helper` route (rules + classifier), persona paragraph. Model policy: `task_helper` and internal `computer_task` |
| UI (`ui/src/computer.ts`) | Placeholders "Title IX training on Canvas" / `canvas.wisc.edu`; "Course modules" preselected; "Any website: Canvas, Duo, module and video sites"; Chrome pairing step "Open your Canvas page"; the Done line printed `undefined of undefined` for general tasks | No | Template picker (General is the default, Course is one choice), generic copy, a hard-limits line, a template chip and "what this step does" on the approval card in the HUD, a 📭 Mailing lists button. New code in new files |
| Chrome extension (`extension/chrome`) | Only comments mention Duo/course pop-ups | Yes | None |
| Skills (`monkey/skills/`) | `canvas-triage`, `email-professor-draft` are chat playbooks, not computer tasks | n/a | None |
| Benchmark (`tools/computer_bench`) | 20 generic fixtures | Yes | Five more fixtures (form, settings page, email injection, unsubscribe page, unclear unsubscribe page) used by the new tests; the bench's own scripted runs are unchanged |

## 2. Risks

- **Planning quality on arbitrary sites is unmeasured.** CI and these tests use a scripted planner that behaves like a
  model (including one that falls for injected text). They measure the execution layer, not Claude's judgment. A live
  run on the Dell is still the first step (as in `docs/research/COMPUTER-USE-QUALITY.md` §7).
- **Risk comes from control names, in English.** An icon-only or oddly named button reads as an unfamiliar control,
  MEDIUM, which runs without asking in the generic template. The `shopping` and `account_settings` templates ask before
  every MEDIUM step for that reason, and "Ask me before he types into or saves anything" does the same for any task.
- **The forbidden-site list is not exhaustive** (US banks, payment apps, brokerages, crypto exchanges,
  Instagram/Snapchat). The goal check, the password/card field rules and `SENSITIVE_WINDOW` are the other layers.
- **Prompt injection can still mislead the planner into a wrong allowed step**, like typing the wrong thing into a field.
  It can't make it send, submit, buy, delete or change anything without the owner's approval of that exact step, and in
  look-only tasks those steps are refused outright.
- **Unsubscribing tells the sender the address is live.** RFC 8058 one-click is designed for this and is safe from
  legitimate senders. Monkey suggests only lists the owner gets often (6+ in 90 days, mostly unopened) and every
  unsubscribe is the owner's pick. Obvious spam should go to Spam, not get an unsubscribe.
- **One-click needs a direct HTTPS connection.** It connects to the checked IP itself and doesn't use a system proxy.
  On a network that requires a proxy it fails cleanly ("didn't answer"), and the list is marked so.
- **Outlook headers:** `PR_TRANSPORT_MESSAGE_HEADERS` can be empty for some Exchange items, and those lists aren't found.
  This was only exercised with fakes.

## 3. Permission model for arbitrary tasks

Everything below is enforced in the execution layer (`PermissionGate.authorize`, called by every driver for every
action, whichever planner chose it). Nothing a page or an email says can widen it.

| Layer | Rule | Where |
|---|---|---|
| Which sites | Per task: "Any website" (default) or a list of domains. Off-list navigation, links and redirect landings are refused | `url_allowed`, `authorize` |
| Hard limits | **Never:** banking or payment sites (even with "Any website"), Instagram/Snapchat automation, typing payment details (card number, CVV, expiry, name on card, IBAN, bank details), changing passwords or security settings (password, PIN, two-factor, 2-step, passkeys, recovery email/phone, security questions). Refused with a clear sentence before a task starts (`check_goal`), and as FORBIDDEN in the gate (never approvable) | `limits.py`, `permissions.SENSITIVE_FIELD`, `SECURITY_CONTROL` |
| Read-only steps | Look, scroll, wait, open an allowed page, routine navigation (Next, Back, tabs, links): run freely | `classify` → LOW |
| Ordinary edits | Typing into a field, picking an option, an unfamiliar control: run (MEDIUM). They ask too when the owner ticked "Ask me before he types into or saves anything", or the template says so (`account_settings`, `shopping`) | `classify`, `confirm_medium` |
| Outward-facing | Submit, send, post, reply, forward, share, delete, remove, enroll, register, accept terms, authorize, upload a file: **ask the owner, one exact step, one time** (a one-time token only Monkey's UI sees; consumed by that action). A "no" is final for that step | `HIGH_WORDS`, `PermissionGate.request/approve` |
| Spending money | Pay, buy, purchase, checkout, place order, book now, subscribe, upgrade, start a trial, donate, tip, rent: always HIGH, labelled **💳 Spends money** on the card. The runner stops before the final purchase button unless the owner approved that exact step | `SPEND_WORDS`, `action_kind` |
| The owner's own part | Sign-in, captchas, quiz/exam answers, attestations: the owner does them (or says the exact choice) | `USER_ONLY` |
| Untrusted content | Page and email text is data. The planner sees it only inside `<untrusted_screen>`; the system prompt and the template guidance come from Monkey. Email bodies are never read for mailing lists (headers only), and only the `List-Unsubscribe` header's address is ever used | `goal.build_context`, `mailing/scan.py` |
| Template rules | Only narrow: `read_only` (look-only: outward steps are refused, not asked), `click_only` (only controls matching a pattern), `type_only` (only these exact values), `no_links`, `confirm_medium`. The one thing they allow is the exact control the owner pre-approved in an unsubscribe batch, and never a step that spends money | `PermissionGate._template_rules` |
| Kill switch | The Stop button, the global hotkey (`ctrl+alt+q` by default), turning computer tasks off, and the Mailing lists ■ Stop: `gate.stopped` refuses every action at once, every task stops, and an unsubscribe batch starts no further item | `AutomationService.emergency_stop`, `Unsubscriber.stop` |

The approval card in the HUD is the existing one (Allow once / Don't). It now says what the step does: 💳 Spends
money, 📤 Sends or posts something, 📨 Submits a form, 🗑 Deletes or removes something, ⚙ Changes your account, 📎 Sends a
file from your PC.

## 4. Templates (`monkey/automation/templates.py`)

| Template | For | Rules | Extra check |
|---|---|---|---|
| `generic` | Anything else ("download last month's bill PDF") | the normal gate | quoted evidence on screen |
| `look_only` | "find the cheapest flight…, just show me" | `read_only` | quoted evidence |
| `form_fill` | "fill in this form with my info, let me review" | normal; Submit asks (and the guidance says stop for review) | quoted evidence |
| `account_settings` | settings, notifications, "cancel my Spotify free trial reminder" | `confirm_medium` | quoted evidence |
| `shopping` | carts and bookings | `confirm_medium`; purchase = 💳 approval | quoted evidence |
| `course` | Canvas/LMS modules (the deterministic CourseSkill, unchanged) | the course loop | the course overview |
| `unsubscribe_page` | one list's web unsubscribe page, started only by an approved batch | `click_only` (unsubscribe/opt-out/confirm), `type_only` (the owner's own address for that inbox), `no_links` | the page must say so ("you have been unsubscribed", …); a local screenshot is kept |

`templates.pick()` chooses one from the goal (the owner can change it in the form); Course is never picked
automatically. A goal about unsubscribing with no page given goes to the Mailing lists review instead
(`templates.panel_for`). `unsubscribe_page` is deterministic: no Claude call; anything it doesn't recognize goes to the
owner.

## 5. Unsubscribing from mailing lists (`monkey/mailing/`)

**Find (read-only, headers only).**
- **Gmail:** a search for bulk mail in the last 90 days (`unsubscribe OR category:promotions/updates/forums/social`),
  then `metadata` format with `From, Subject, Date, List-Unsubscribe, List-Unsubscribe-Post, List-Id` and the label
  ids. The existing `gmail.readonly` scope covers it, batched 50 per request, up to 400 messages per inbox.
- **Outlook:** only while classic Outlook is already open (it is never started), via `PropertyAccessor` →
  `PR_TRANSPORT_MESSAGE_HEADERS`.
- **Grouping:** by List-Id, else by the sender's address, per inbox. Each list has its count in 90 days, how many are
  still unread ("unopened"), the last received date, and the unsubscribe methods from its newest message.
- **Picks:** 6+ emails in 90 days and 75%+ unopened. Monkey can say them ("you get about 29 emails a month from X and
  never open them") through `find_mailing_lists`. Sender names and subjects are untrusted text, shown as data.

**Review (Monkey's UI: 🖐 Tasks → 📭 Mailing lists, or opened by Monkey).** A table with the sender, list, inbox, count
in the last 90 days, % unopened, the last email, the method and the status, plus account filters, "Check inboxes
again" and Keep (stop suggesting a list). The brain's `propose_unsubscribe(["Medium"])` only ticks rows.

**Approve.** "Review & unsubscribe (N)" asks Python for a plan (`Unsubscriber.prepare`). It lists exactly what will
happen per list, picking the method in order of preference:
1. **One-click (RFC 8058).** An HTTPS POST of `List-Unsubscribe=One-Click` with `Content-Type:
   application/x-www-form-urlencoded`, and no cookies, authorization, referrer or other data. Redirects are not
   followed. Only 2xx counts as done.
2. **Email (`mailto:`).** A draft to that one address (with the header's subject/body) in **the inbox the list writes
   to**, registered with the existing email approval gate. It goes out only when the owner presses Send on the draft
   card (or says "send it" and confirms). The batch never sends.
3. **Web page.** Monkey's browser opens the header's https page under `unsubscribe_page`. It can press only an obvious
   unsubscribe/confirm control and type only the owner's own address if asked. It keeps a screenshot
   (`%APPDATA%\Monkey\task-shots\<task>.png`, local only). This needs computer tasks on; otherwise the list is marked
   "Needs you" with an **Open page** button (the owner's own click).
4. **Manual.** No usable method.

"Unsubscribe from these N" approves exactly that plan, once (a one-time token bound to the stored steps; the UI can't
change them, and it expires after 15 minutes). Items run one at a time; ■ Stop (or the global e-stop) stops the rest.

**Address checks** (`mailing/headers.py`), before planning and again right before the POST:
- https only, port 443, no `user:password@`, no IP literals or local names (`localhost`, `.local`, `.internal`,
  single-label);
- every DNS answer must be a public address: private, loopback, link-local (cloud metadata), reserved, multicast and
  IPv4-mapped-private are refused;
- the POST connects to the checked IP with SNI and certificate checks for the host name (no DNS-rebinding window);
- `mailto:` must have exactly one valid recipient and no cc/bcc or other header fields, and the subject and body are
  capped.

**Results** (`monkey.db`, table `mailing_lists` plus the log `mailing_unsub_log`): done, waiting for Send,
needs you, didn't work, kept. URLs stay local; they are never logged, sent to Claude or sent to the UI.

**Verify.** "Done" starts a 7-day watch. Each scan updates the last-received date. Mail newer than the unsubscribe plus
the 2-day grace period RFC 8058 allows marks the list ⚠ **Still arriving**. After 7 quiet days it becomes ✓ **Quiet**.
A daily background check re-reads only the inboxes with a verification due, and does nothing otherwise.

**Archive / filter afterwards: built** (`feature/inbox-cleanup`, see [INBOX_CLEANUP.md](INBOX_CLEANUP.md)). The
owner approved it on 2026-11-24. "Also archive their old emails" and "Filter new mail from them so it skips the inbox"
become available per inbox once the owner allows Monkey to tidy it. That's one incremental Google consent for
`gmail.modify`, plus `gmail.settings.basic` only if the filter box is ticked. Both are bound into the same one-time
approval. Archiving applies the inbox cleanup's importance check. Archive only, never delete.

**Banks and Instagram are skipped** (the owner, 2026-11-24): lists from banking or financial senders and from
Instagram/Meta are never listed, suggested or unsubscribed from (`limits.sender_limit`). The review says how many were
skipped.

## 6. Brain and cost

- **Route `task_helper`** (rules + classifier): "unsubscribe me from…", "stop getting these emails", "cancel my … trial
  / membership / subscription", "fill out … form", "go on X's website and cancel …", "find the cheapest … just show
  me". Near-misses keep their routes ("remind me to cancel my gym membership" → to-do, "read me the newsletter…" →
  classifier, "what's on the website for my class" → classifier).
- **Tools:**
  - `propose_computer_task(objective, start_url, template)` refuses hard-limit goals with the reason and sends
    unsubscribe goals to the review; otherwise it opens the permission window.
  - `find_mailing_lists(refresh)` and `propose_unsubscribe(names)` are both marked untrusted, so memory writes stay
    guarded while email data is in context.
- **Persona:** the task helper does multi-step jobs on almost any site, not just Canvas. It never starts, sends or
  unsubscribes by itself, and the hard limits are said in one sentence.
- **Model policy** (`docs/MODEL-POLICY.md`, regenerated):
  - `task_helper`: Haiku medium (min Haiku low, max Sonnet medium). It is one tool call and a line.
  - Internal `computer_task`: the GoalRunner planner, Sonnet medium, escalating to Opus on a stall. It was hard-coded
    before and is now read from the policy.
  - Scans, one-click unsubscribes and the unsubscribe page make no model calls.

## 7. Tests

All without network or real accounts.

| File | What it covers |
|---|---|
| `tests/test_task_helper_limits.py` (67) | The refusal list and its near-misses; forbidden sites with "Any website"; password/2FA/payment classification; spending as HIGH with the 💳 label; one-time approvals; template rules (look-only refuses, settings ask, unsubscribe click/type-only); template picking; the unsubscribe skill picking the button over the decoy; service and brain refusals; router; policy; persona |
| `tests/test_task_helper_general.py` (10, real Chromium) | Generic form (the injected "Delete my data" is denied, the card number is refused, Submit runs only after approval); a denied Submit never happens; look-only refuses Submit without asking; injection inside an email (forward/send/delete refused); the planner context keeps page text inside `<untrusted_screen>`; settings page (2 approvals, password and 2FA refused); the unsubscribe page through GoalRunner and through TaskManager without Claude (decoy "Sign up", hidden injection, a screenshot kept); a misbehaving planner on that page; an unclear page handed to the owner without a click |
| `tests/test_mailing_lists.py` (34) | Header parsing; one-click URL validation (19 cases incl. rebinding, metadata IP, IPv6, credentials, ports); mailto validation; the Gmail scan uses only `metadata`; Outlook headers only when it's open; body links and injected subjects never used; a hung inbox read abandoned; grouping; the store, results log and 7-day verification; suggestions; one-click to a fake server (exact body, no cookies, connects to the checked IP); bad URLs never sent; redirects not followed; batch token one-time; kill switch mid-batch; mailto drafted in the right inbox and sent only through the approval gate; the web method needing computer tasks |
| `tests/test_task_helper_ui.py` (2, built UI in `?demo`) | The Mailing lists review → plan → run; a general task in the HUD (template picker, limits line, 📨 approval card, the refused password step in the live feed) |

## 8. Open decisions for the owner

1. ~~Archive / filter after unsubscribing.~~ **Decided 2026-11-24: yes**, with a check first. Built on
   `feature/inbox-cleanup` ([INBOX_CLEANUP.md](INBOX_CLEANUP.md)): incremental consent per inbox, archive only.
2. ~~Senders on forbidden sites.~~ **Decided 2026-11-24: skip bank and Instagram senders entirely.** Built on
   `feature/inbox-cleanup`.
3. **Verification window:** 7 days (`store.VERIFY_DAYS`).
4. ~~Default kind of task in the Tasks form.~~ **Decided 2026-11-24: general-first.** The Tasks menu starts with
   "What should Monkey do?" and the capabilities. Course modules is one of seven, and its fields appear only inside it
   (`feature/inbox-cleanup`).
5. **Bench:** add the five new fixtures to the Windows computer-use bench (`tools/computer_bench/scripts.py`) so its
   numbers include them? They run in the Linux browser CI job today.

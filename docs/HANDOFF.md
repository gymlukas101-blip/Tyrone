# Handoff: where Monkey stands

Last updated 2026-11-24 (dropped class). Everything below is on `main`, including Voice 2.0 and hybrid computer use (merged together on 2026-11-20, after the sound-off, Animation 2.0 and sound-rebuild releases v0.3.81 and v0.3.83). The owner is on the Dell XPS 15 9530.

**Not yet tried on the Dell:** Voice 2.0 (early commit, fast voice routing, soft ack; setting `early_commit` = false restores the old endpointing), hybrid computer use (needs a live model run, `docs/research/COMPUTER-USE-QUALITY.md` §7), the new face and lip sync, and the sounds.

Everything is on `main`. The development sessions run in throwaway cloud containers, so anything not in this repo is gone when one ends. The chat history survives, but not the container's files.

## Dropped a class (branch `feature/dropped-course`, waiting for review)
- The owner asked to "remove all marketing assignments since I dropped the class". Built as a feature they use once: a class can be hidden everywhere in Monkey and shown again. Local data only; nothing changes on Canvas.
- **How the owner does it** (either way):
  - Homework → **By class** → **⋯** next to the class → **I dropped this class** → the confirm names the class and the counts → **Hide it**. The toast says "Removed N … assignments and M to-dos" with **Undo**.
  - Or say/type "I dropped marketing" (or "remove all my marketing assignments", "hide the marketing class"). Monkey asks "Hide <class> everywhere? N assignments, M to-dos" and shows the same confirm; say "yes" or press Hide it.
  - Show it again: the toast's Undo, Settings → Accounts → **Hidden classes** → Show again, or "show marketing again".
- Hidden from: Homework, Today, the morning brief (due, overdue, today's classes, class times from notes), the brain's assignment/calendar/ranking tools, reminders, email to-do suggestions, and class-schedule detection. Its to-dos are archived (status `dropped`, restored as they were). A memory line "Dropped <class> on <date>" goes in the owner's local classes.md.
- Details: `docs/IMPLEMENTATION-NOTES.md` (2026-11-24, dropped class). Not tried on the Dell or with the owner's real Canvas feed (the match uses the feed's course codes; a class with no code in the feed is matched by name).

## To-do list (branch `feature/todo-list`, waiting for review)
- 📝 To-do panel and brain tools (`add_todo`, `list_todos`, `update_todo`, `delete_todo`): the owner's own to-do list in `monkey.db`, with quick add ("call the dentist tomorrow 5pm"), sub-steps, Undo, Monkey's "help me with this" (steps, then existing tools only), in-app reminders and a To-do section in the morning brief. Details: `docs/IMPLEMENTATION-NOTES.md` (2026-11-23).
- Not tried on the Dell.

## Reminder notifications (branch `feature/todo-notifications`, waiting for review)
- The owner asked for reminders "as windows notifications and on my phone too". Settings → **Reminders**: in-app note (as before), Windows notifications (default on; Done / Snooze 10 min buttons, a click opens the To-do panel, works with the window in the tray) and the phone via ntfy (default off; "Set up my phone" makes a random topic kept in secrets.dat, QR code, test button, "show the to-do on my phone" privacy switch, own server/token optional). Details: `docs/IMPLEMENTATION-NOTES.md` (2026-11-23, reminder notifications).
- Not tried on the Dell: the real toast, its buttons and a click from Action Center, and a real ntfy delivery. On the Dell: Settings → Reminders → Send a test Windows notification; Set up my phone → subscribe in the ntfy app → Send test notification.

## Email accounts → to-do list (branch `feature/todo-email-accounts`, waiting for review)
- ✉️ Any number of Gmail accounts (one Google sign-in each, "+ Add another Gmail account") plus classic Outlook, each with a label the owner picks. The old single Google sign-in moves over by itself on first start (no new sign-in).
- Monkey reads every inbox and says which account each email is from. A draft names the account it goes out from and sends only from it.
- Per inbox, "Find to-dos in this inbox" (off by default): a read-only check every 15 minutes puts **suggestions** in a "Suggested from email" section of the to-do panel (Accept / Dismiss / Open). Nothing is added on its own. Outlook is only read while it's already open.
- Details: `docs/IMPLEMENTATION-NOTES.md` (2026-11-23, email accounts). Not tried on the Dell or with real accounts.

## Phone screen time (branch `feature/todo-screen-time`, waiting for review)
- Off by default (Settings → Phone). The owner has an iPhone: a Shortcuts automation (iOS 26 *Get App & Website Data*) saves a summary to iCloud Drive, or they type today's total and top app; Android (Tasker → encrypted ntfy relay) is a secondary path; the To-do panel shows today vs a goal, goal to-dos check themselves off, `get_screen_time` answers "how much was I on my phone". Research and setup: `docs/research/PHONE_SCREEN_TIME.md`.
- Owner: iPhone on iOS 27.2.1, automatic Shortcut route, goal ~3 h/day across TikTok + Instagram + YouTube: the phone card offers "Social: TikTok, Instagram, YouTube ≤ 3h" as a one-click daily goal to-do (app-group goals match names by alias, e.g. YT, IG, youtube.com).
- Still open: what the Shortcuts *Get App & Website Data* action returns (the parser is lenient). Not tried on the phone or the Dell.

## Blocky look (branch `feature/todo-blocky-ui`, waiting for review)
- New fonts app-wide (Titan One + Nunito, bundled, OFL) and toy-block 3D icons in the header, mic and to-do panel, baked once on the PC into sprites (no WebGL at rest), a faint block background in the to-do panel, a "done!" pop. Juice and reduced motion respected; skipped on software GL. Prototype gallery of all 63 icons + backgrounds: `ui/prototypes/blocky-icons/`. Details: `docs/ui/BLOCKY_ICONS.md`, `docs/ui/TODO-FONTS.md`.
- Not tried on the Dell (bake time on its GPU, crispness at its scaling).
## Task helper for any task + mailing lists (branch `feature/task-helper-general`, waiting for review)
- 🖐 The task helper isn't Canvas-only any more. Monkey offers a task from any goal ("cancel my Spotify free trial reminder", "find the cheapest flight… just show me", "fill in this form, let me review").
- Templates add rules and checks; Course is one of them, unchanged.
- **Hard no:** banking or payment sites, Instagram/Snapchat automation, typing payment details, passwords or security settings.
- Spending, sending, submitting, deleting and account changes stop for the owner's OK on that exact step.
- 📭 **Mailing lists:** reads list headers in every inbox and suggests lists the owner never opens. It unsubscribes only what the owner approves, per list: one-click, an email the owner sends from the draft card, or the list's own page. It then checks for 7 days that the mail stopped.
- Design, audit and open decisions (archive/filter needs a broader Gmail scope; it's off): [`docs/automation/GENERAL_TASKS.md`](automation/GENERAL_TASKS.md). Not tried on the Dell, with a live planner, or with real inboxes.

## Inbox cleanup + general-first Tasks (branch `feature/inbox-cleanup`, waiting for review)
- 🧹 **Inbox cleanup:** "clean up / organize my inbox" (one inbox or all) → a plan → one approval → archive in batches
  of 25 with Stop → Undo.
  - The plan says what goes (counts and example subjects per group) and what stays and why.
  - Archive only, never delete. Optional labels: Newsletters, Receipts, School, Notifications.
  - Conservative check: starred/important, banks, Instagram, to-dos, people the owner writes to, school, recent
    receipts and security codes, upcoming deadlines and real people always stay. The cheap model only sees emails the
    rules can't settle.
- 🔑 **Permission:** per Gmail inbox, the first time, with incremental consent for `gmail.modify` ("Allow Monkey to tidy
  this inbox"). `gmail.settings.basic` is asked for only if the owner ticks "filter new mail" after unsubscribing.
  Same DPAPI secret; read-only inboxes keep working. Outlook: archived to its Archive folder, only while it's open.
- 📭 **Mailing lists:** bank/financial and Instagram/Meta lists are skipped entirely ("Skipped N lists from
  banks/Instagram"). "Also archive their old emails" / "filter new ones" now work once an inbox may be tidied.
- 🖐 **Tasks menu, general-first:** "What should Monkey do?" + Go, then the seven things Monkey can do, the can/can't
  line, the task form (Course fields only inside Course modules) and Recent tasks.
- Design, rules and scopes: [`docs/automation/INBOX_CLEANUP.md`](automation/INBOX_CLEANUP.md).
- **Not tried on the Dell, with a real inbox, or with Google's real consent screen.** The owner first adds the scope in
  Google Cloud (Data access → `gmail.modify`; see "Waiting on the owner").

## UI motion (branch `feature/ui-motion`, waiting for review)
- Expressive, readable motion for every UI event and interaction: `ui/src/motion.ts` + `ui/src/motion.css`, inventory and rules in `docs/ui/MOTION.md`, notes and perf numbers in `docs/IMPLEMENTATION-NOTES.md` (2026-11-23, UI motion).
- Follows Settings → Juice level (Minimal = short fades only) and the Windows "reduce motion" setting. Not tried on the Dell.

## Menu motion + loading UIs (branch `feature/menu-motion`, waiting for review)
- The owner asked for "highly animated menu popup animations and transitions and highly animated loading UIs for when menus are taking time to load".
- Every dialog, panel and header card grows out of the button that opened it and closes back into it (faster); Escape animates too and always closes; Tasks → Mailing lists / Inbox slide across; Settings section jumps slide in. One helper for all dialogs: `ui/src/menu-motion.ts`.
- Slow menus (over 150 ms) show a skeleton in their real layout with a jungle shimmer, a banana trio / swinging vine / bobbing monkey, words that change after 3 s and 8 s, an error with Try again, then crossfade to the content: `ui/src/loader.ts`. Covers Today, Homework, To-do, Health, Lab, Settings and its sections, Check everything, Tasks and task planning, Mailing lists, Inbox cleanup, Brain, the morning brief, update checks and image generation.
- Rules, inventory (items 94–121) and levels: `docs/ui/MOTION.md` ("Menus", "Loading"); perf and notes: `docs/IMPLEMENTATION-NOTES.md` (2026-11-24, menu motion). Try it in a browser with `?demo&slow=1500`. Not tried on the Dell.

## Hybrid computer use (merged; live Dell run still pending)
- **Hybrid computer use:** `monkey/automation/computer/`. One `Computer` interface over:
  - the managed browser (Playwright);
  - Windows UI Automation (owned dialogs included);
  - a visual fallback (Claude computer toolset as a grounder).
- **The `Computer` layer:** capability router, typed outcomes and errors with bounded recovery, idempotency ledger, write-ahead intents, structured trace.
- **General tasks:** `TaskManager` runs `skill="general"` tasks through `computer/goal.py` (skills, then verified cache, then the Claude planner; verify before "done").
- **Docs:** [ADR 0002](adr/0002-hybrid-computer-use.md), [research report](research/COMPUTER-USE-RESEARCH.md), [quality report](research/COMPUTER-USE-QUALITY.md).
- **Bench:** `tools/computer_bench/`, run in CI by `.github/workflows/computer-bench.yml` (Windows runner):
  - `run_browser` (20 fixtures);
  - `run_windows` (13 native tasks × monkey / agent-desktop / windows-mcp);
  - `run_hybrid` (browser → Notepad + Save As → browser).
- **Measured on the GitHub Windows runner:**
  - Monkey's UIA backend: 13/13 native tasks.
  - agent-desktop: 8/12.
  - Windows-MCP: 10/12, but it moved the real mouse in 8 of them.
  - Browser fixtures: 20/20.
  - The hybrid task with the real Notepad and Save As dialog passed in 8.7 s.
- **Next:** the backlog in [the quality report](research/COMPUTER-USE-QUALITY.md) (a live model run on the Dell comes first).

## Computer tasks (merged to main 2026-11-20)
- Computer tasks: a durable TaskManager, an execution-layer permission gate, a managed Edge browser through Playwright with the
  official Claude browser toolset, a deterministic course skill, a demo course, a Windows UIA driver, the companion window,
  and the animated banana cursor. Status, the Windows test procedure and results: `docs/COMPUTER-AGENT.md`.
- Banana cursor base art: waiting for the owner's reference PNG as a *file* (`docs/cursor/REFERENCE-ANALYSIS.md`).
- Speech fix shipped on main (v0.3.54+): Whisper on the CPU (NVIDIA without CUDA DLLs broke speech recognition on the Dell).

## Recently shipped
- **v0.3.33–0.3.34: Google sign-in.** The sign-in browser actually opens now:
  - a named `webbrowser` controller and `monkey/links.py` replace the global patch that recursed;
  - a Copy-link fallback;
  - a calendar-link (ICS) option that needs no sign-in;
  - the routing benchmark is in the app.
- **v0.3.34: Outlook.** Monkey no longer launches Outlook. Outlook is opt-in through Settings → Connect, and the availability check is a registry lookup.
- **v0.3.35: voice loudness.** The voice is leveled to about -14 LUFS, like YouTube, calibrated on real speech. There's a voice volume slider and a "match loudness" toggle.
- **v0.3.36: Move to a new PC.** One encrypted `.monkey` file holds memory, chats, settings, voice, Garmin, skills and optionally the keys. Import is staged and swapped in on restart. See `docs/MOVE-TO-NEW-PC.md`.
- **Earlier milestones** (details in `docs/IMPLEMENTATION-NOTES.md`):
  - conversation mode without the wake word, patient endpointing, self-healing listener;
  - memory P0–P3: provenance facts, FTS5 history, importer, memory tools, morning brief, skills;
  - sound kit, Pocket TTS offline voice, Blender rig and clips, fur and lighting.

## Waiting on the owner (on their PC)
1. Settings → **Check everything** → Copy report → paste it into the chat. It shows what works on the Dell.
2. Google: in Google Cloud → Audience → **Publish app** (or add the account as a test user), then Sign in. Check that the Gmail API and Calendar API are enabled in the Google Cloud project.
3. Import the private context pack: Settings → Memory → Import context files. It never goes in this repo.
4. Confirm the class schedule (Morning brief → Detect), or paste a calendar link, then turn the morning brief on.
5. Run the routing benchmark (Settings → Brain → Run benchmark) and share the result, so the router rules and policy can be tuned.
6. Inbox cleanup (once `feature/inbox-cleanup` ships): in Google Cloud → Google Auth Platform → **Data access** → Add or
   remove scopes, add `https://www.googleapis.com/auth/gmail.modify` (and `.../auth/gmail.settings.basic` for "skip the
   inbox" filters) → Save. Keep the app In production; the unverified-app warning is expected (Advanced → Go to Monkey).
   Then 🖐 Tasks → Clean up my inbox → Allow in Google.
7. The dropped class (once `feature/dropped-course` ships): Homework → By class → ⋯ → I dropped this class → Hide it,
   or say "I dropped marketing" and then "yes". Check that the confirm names the right class and counts.

## Next up for development
- Tune the router from the benchmark results.
- Verify on the real Dell:
  - wake word and endpointing with the XPS microphone array;
  - loudness against YouTube;
  - Google end to end.
- If the owner shares a folder through Remote Control, sessions can run the tests and read `%APPDATA%\Monkey\monkey.log` on the real machine.
- Deferred on purpose: subagents, chat channels (Slack/GroupMe/iMessage). See `docs/AGENT-ROADMAP.md`.

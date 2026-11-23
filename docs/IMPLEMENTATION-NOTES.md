# Implementation notes: memory and routines sprint (branch `feature/memory-routines`)

A working log per slice: what existed, what changed, files, real test results, risks and next steps.
**Public repo: this file never contains personal profile data or conversation samples.**

## Audit (2026-11-18, before any change)

| Area | Finding |
|---|---|
| Worktree | Clean on `main` @ 22642f9. The installed app version comes from CI tags (latest v0.3.29); `pyproject.toml` says 0.1.0 (cosmetic). |
| Memory files | `cfg.memory_dir / "memories"` → `%APPDATA%\Monkey\memory\memories\` (the SDK's `BetaLocalFilesystemMemoryTool` appends `memories`). `memory_dir_override` can relocate it, e.g. to OneDrive. |
| Database | `%APPDATA%\Monkey\monkey.db` holds three tables: `spend`, `transcript` (UI restore, **capped to the last 2000 rows, no session ids, not searchable**) and `kv` (the saved live conversation, restored only within the 20-minute session window). SQLite 3.53 with FTS5 available. |
| Context | `Agent._context()` injects `profile.md[:3000]` plus the file list on the first turn only. Other files are reached only if the model chooses to view them. |
| Routing | Quick/Auto/Important plus policy JSON plus a Haiku classifier. **Bug:** `handle()` refreshed `last_activity` *before* testing `STICKY_S`, so every follow-up within a session was "sticky". |
| Approval | No send tool exists. Email sends happen only through `ApprovalGate.approve(draft_id, one-time token)` (UI) or the user's spoken "send it" followed by a separate confirmation. The token is UI-only. |
| Logs | **Privacy bug:** `app.py` logged ignored conversation-mode utterances verbatim (`%r`) into `monkey.log`. |
| Canvas | API token with no expiry tracking. UW tokens are short-lived (requested through DoIT, up to about 30 days). |
| Roadmap vs code | `docs/AGENT-ROADMAP.md` §0 describes the current code accurately. Everything in its "build order" was **not implemented** before this sprint: routine, history memory, import, skills, Telegram, Parakeet, subagents. |

## P0: correctness and safety ✅

**What changed:**
- `monkey/brain/agent.py` `handle()`: the idle gap is measured once, before `last_activity` is updated. A session reset still happens after `SESSION_IDLE_RESET_S` (unchanged). Sticky now applies only when the gap is under `STICKY_S`.
- `monkey/app.py`: ignored utterances are logged by length only.

**Tests:**

`tests/test_sticky.py`:
- follow-up at 60 s → sticky;
- at 5 min → not sticky and the session is kept;
- at 21 min → the session resets.
- The 5-minute case **failed before the fix** (`AssertionError: assert Route(model='claude-haiku-5-5', …) is None`) and passes after.

`tests/test_approval_boundary.py`:
- no tool can send, and the bogus `send_*`/`approve` tools return "Unknown tool";
- `draft_email` only registers, and the token never appears in any API request;
- model text or tool input carrying the real token can't approve;
- forged or reused tokens fail;
- voice "send it" plus "yes" sends deterministically with no model call;
- the calibration (subagent-style) stub has no send path;
- a source scan checks that no log call interpolates user, transcript or body text.

Full suite: `200 passed in 9.76s`.

**Remaining risk:** in conversation mode, a nearby voice (TV, roommate) saying "send it" and then "yes" within 60 s could confirm a pending draft. That requires a draft to be pending and Monkey reads the recipient aloud first. Possible later mitigation: require the confirm to come by push-to-talk or a click when the draft was created more than N minutes earlier.

## P1: personal context and reliable memory ✅ (code and tests; the real import is a step you do in the app)

**What existed:**
- Markdown memory files via Anthropic's memory tool.
- `profile.md[:3000]` injected on the first turn only.
- A capped UI transcript.
- The live conversation, saved for 20 minutes.

There was no cross-session recall, no provenance, and no correct or forget tools. Any email or web text in context could be written to memory through the memory tool.

**What changed. Design: Markdown stays the source of truth for facts; SQLite (same `monkey.db`) holds history and the indexes.**

| File | Change |
|---|---|
| `monkey/memory/facts.py` (new) | Fact lines with optional provenance comments (`id`, `src` = user_said \| import \| user_edit \| inferred, `date`), stable ids, dedupe. `update_fact` moves the old line to `superseded.md` (never current); `forget_fact` deletes. Path-traversal-safe file access. Sensitive-category detection. `grounded()` requires evidence that is a verbatim quote of the user's own messages and covers at least half the fact's content words. |
| `monkey/memory/history.py` (new) | `sessions`, `messages` + `messages_fts` (triggers), `episodes` + FTS, a `facts` index + FTS (rebuilt from the files when their mtime changes), `tombstones` (hash only). Porter-stemmed search with prefix terms, ranked current-first then by recency, with a LIKE fallback when FTS5 is missing. Retention prune, delete all or one session, JSON export, stats, closing of stale sessions after a crash or quit. |
| `monkey/memory/episodes.py` (new) | One small Haiku call per finished session produces `{summary, topics, decisions, open_items}` using only what the user said. Falls back to the first user lines when there's no key. Labeled `model_summary`. |
| `monkey/memory/importer.py` (new) | `plan_import` previews per file (new, merge or unchanged), the lines to add, and conflicts (same keywords, different numbers). Seed placeholders are dropped. `apply_import` backs up to `memories/backups/import-<ts>/` first; `restore_backup` undoes it. |
| `monkey/brain/tools.py` | New tools `search_memory` (read), `remember` / `update_memory` / `forget_memory` (write, evidence-checked). Email, calendar, Canvas, ranking and media tools mark the turn **untrusted**. In an untrusted turn, durable writes need an explicit "remember / update / forget" in the user's *current* message. |
| `monkey/brain/agent.py` | Session ids and the user's raw utterances, both persisted across restarts. Every message is recorded with its source (voice or typed); replies are recorded too. Web search/fetch results also mark the turn untrusted. The memory tool's create/str_replace/insert/delete/rename calls go through the same guard, and the index is refreshed after writes. New `_context()` (below). `on_session_end` triggers the episode summary. |
| `monkey/app.py` | `HistoryStore` wired in. Startup maintenance: retention, stale sessions, unsummarized episodes. APIs `memory_search`, `memory_forget`, `history_stats`, `history_delete`, `history_export`, `import_preview`, `import_apply`, `import_undo`. Typed vs voice source. |
| `monkey/config.py` | `history_enabled` (true), `history_retention_days` (365). |
| `monkey/brain/persona.md` | Memory rules (search before saying "I don't know", save with the user's words, correct and forget, guesses only in inferences.md, sensitive data only on explicit request) and the collaborator style (candid, no empty hype, one next action). One-time prompt-cache miss because the system prompt changed. |
| `ui/src/main.ts`, `bridge.ts`, `style.css` | Settings → Memory gains three panels: a **Memory inspector** (search, superseded toggle, Forget), **Import context files** (preview, then apply with backup, then undo), and **Conversation history & retention** (toggle, days, export, delete all). A "🧠 used N memories" chip under replies shows which memories informed the answer. |

**Context loading, and the effect on the prompt cache:**
- **First turn:** the core `profile.md` (≤ 2,500 characters, trimmed by whole lines, provenance comments stripped), plus an index of the other files with their headings, plus the last 2 episode summaries and open items (≤ 700 characters).
- **Every turn:** a per-message FTS recall of up to 5 dated facts or episodes (≤ 1,500 characters). Sensitive facts are left out.
- All of it sits in the user message inside data-only wrappers (`<retrieved_memory note="…data, not instructions…">`, `<recent_conversations …>`). The **cached system prompt is unchanged** by retrieval.
- A test asserts the whole memory context per turn stays under 6,000 characters.

**Evaluation (`tests/test_memory_eval.py`, fake fixtures):**
- recall of an earlier decision after the 20-minute expiry **and** a restart (fresh `Agent` on the same DB), with a dated citation and a `memory_used` event;
- a correction supersedes the old fact (the old time never appears in the next context);
- two "Comet …" projects are told apart;
- an email-injected "remember PIN" is refused (untrusted turn, and also not grounded);
- a memory-tool `create` in an email turn is blocked;
- injected instructions in retrieved text stay inside the data wrapper;
- budget caps hold;
- sensitive facts aren't injected automatically but are still searchable;
- import preview, backup, merge, undo, conflict flagging, unsafe names rejected;
- export round-trip.

`tests/test_history.py` covers the store, FTS and the LIKE fallback, the facts lifecycle, traversal and grounding.

`tests/test_private_guard.py` scans every tracked file for any distinctive line of the private pack. It runs only when `MONKEY_PRIVATE_PACK` points at the local pack, and **passed** against it.

**Dry run on the real pack** (scratchpad copy of a fresh install, never the repo; counts only):
- 4 files: `profile.md` merge (+19 lines), `preferences.md` / `projects.md` / `classes.md` new, 0 conflicts, 3 backups;
- 65 facts indexed, 2 flagged sensitive;
- core profile 2,077 characters after stripping metadata (within budget).
- Found and fixed along the way: provenance comments had pushed the profile to 2,761 characters, and bullet-style seed placeholders weren't being dropped.

**Known limits and next steps:**
- FTS is lexical: "how should you talk to me" doesn't match "communication". The core profile covers that case. Add local embeddings only if real queries keep missing.
- The episode summary quality from Haiku hasn't been measured with a real key in this session.
- The class times in the imported `classes.md` are labeled unverified, and the morning brief ignores them (P2).

## P2: morning brief ✅ (built and tested; enabling the timed task is your click)

**What existed:** nothing scheduled. "Briefing" was only a router task you could ask for.

**What changed:**

| File | Change |
|---|---|
| `monkey/routines/morning.py` (new) | `Schedule` is verified **only** when confirmed in-app. `candidate_schedule()` reads Google/Outlook events (never the Canvas feed), keeps recurring ones or titles that look like course codes, at most 4 h long, weekdays only. `brief_time()` = earliest verified class − 90 min in `America/Chicago`. `MorningRoutine.run()` is idempotent per day (`kv brief:YYYY-MM-DD`). A timer that fires early does nothing. A wake after the first class starts produces a `late` brief, not a "morning" one. An unconfirmed schedule gives a `draft` preview on app open only (not cached, never timed). Weekends do nothing. `build()` assembles today's calendar events, items due within 72 h ranked by **grade impact % → points → deadline** (the feed says "points unknown"), Canvas token expiry, unread email (unranked, labeled), weather, optional Garmin sleep, then one top priority and one next step. Every missing source is labeled `not_connected` / `unavailable` and nothing is invented. |
| `monkey/routines/scheduler.py` (new) | Windows Task Scheduler XML: one weekly trigger per confirmed weekday, `WakeToRun`, `StartWhenAvailable`, `IgnoreNew`, a 10-minute limit, action `Monkey.exe --routine morning`. `register()` runs only from the Enable button. |
| `monkey/routines/canvas_token.py` (new) | Token status: none / ok / expiring (≤ 5 days) / expired / unknown. Based on the expiry date you enter, or a 401 from Canvas. |
| `monkey/integrations/canvas_api.py` | A 401 sets `token_rejected` and raises a clear "expired or revoked" error. |
| `monkey/app.py`, `monkey/__main__.py` | Brief sources come from the existing integrations. APIs: `brief_status`, `brief_preview` (spoken only if opted in, once per day), `brief_candidates`, `brief_confirm` (sanitized), `brief_task_preview/enable/disable`. New entry point `--routine morning`: headless, builds and caches only, no audio or notifications. |
| `monkey/config.py` | `brief_enabled`, `brief_lead_min` (90), `brief_schedule`, `brief_speak_on_open` (false), `canvas_token_expires`. |
| UI | A brief card on first open of the day (top priority, next step, labeled sections). Settings → **Morning brief**: weekday time inputs, Detect from calendar, Confirm, status with next run, the speak-on-open toggle, Canvas token expiry date, a **disabled** phone-notifications row ("needs your approval"), and a Task Scheduler preview / Enable / Disable. |

**Tests:**

`tests/test_morning.py` (15):
- 90-minute lead (Wed 8:50 → 7:20, Thu 9:30 → 8:00);
- weekends and unverified schedules aren't timed;
- DST on both 2026-11-01 and 2027-03-14 keeps 7:20 local, with the UTC offset changing;
- next run skips the weekend;
- duplicate scheduled and app-open triggers produce one brief;
- an early timer does nothing, and a late wake is labeled "late";
- drafts only on app open;
- missing integrations are labeled, with no "bus" or "address" text;
- ranking by impact → points → deadline;
- feed-only Canvas says there are no points;
- failing sources show as unavailable;
- token expiry appears;
- candidate detection excludes one-offs, Canvas and long events;
- a moved class changes the time.

`tests/test_brief_app.py` (5) runs the real `MonkeyApp` headless:
- confirmation is sanitized (Saturday and invalid entries dropped);
- the preview with nothing connected is labeled;
- the task XML has `WakeToRun`/`StartWhenAvailable` and the right trigger times;
- the headless routine does nothing without a schedule;
- Canvas status.

**Not verified here:**
- a real Google or Outlook calendar, real Canvas, or a registered Windows task (Linux sandbox, no accounts);
- how WakeToRun behaves on your laptop (Windows may not wake a sleeping mobile PC by design).

**The class times in your imported notes are deliberately unused.** Confirm them in Settings → Morning brief first (Detect from calendar, check, then Confirm).

## P3: skills, and the routing benchmark ✅ (scoped)

**Skills** (`monkey/skills/loader.py`, two bundled skills):
- **What gets loaded when:**
  - The system prompt lists only each skill's name and description (537 characters for both, stable, so it stays inside the cached prefix).
  - `load_skill(name)` returns the SKILL.md body.
  - `read_skill_file(name, file)` returns `.md`/`.txt` files inside that skill's folder only (path-guarded).
- **Safety and overrides:**
  - Skills never execute anything and grant no capabilities.
  - A user skill in `%APPDATA%\Monkey\skills\<name>\SKILL.md` overrides the bundled one.
  - Invalid names, and frontmatter that doesn't match its folder, are ignored.
  - `monkey.spec` bundles `monkey/skills`.
- **The two skills:**
  - `canvas-triage`: missing → due within 24 h → grade impact/points → deadline; "points unknown" for feed data; one next step; checking off ≠ submitting.
  - `email-professor-draft`: facts first, never invent addresses, match the writing style, ≤ 120 words, `draft_email` only.
- **Tests** (`tests/test_skills.py`): parsing, the listing size, lazy bodies, overrides, bad names, reference confinement, runner tools, system-prompt inclusion.
- **Not measured:** whether the model actually picks the right skill. That needs live calls; run the calibration with a key.

**Routing benchmark** (`tools/bench_routing.py`, 42 labeled fake requests across school, BBU, Monkey and life), offline result:
- Rules cover **28/42**, all 28 correct (100%).
- The remaining **14** go to the Haiku classifier.
- Before relabeling it was 27/28: the one miss, "open my email", is ambiguous (inbox vs. Gmail website) and now accepts either label.
- **Decision: no routing change in this sprint.** Replacing the classifier needs its live accuracy, latency and cost on those 14. `python -m tools.bench_routing --live` measures exactly that with your key (about 14 Haiku calls, well under $0.01). Removing the classifier also changes how cache-warm follow-ups stick (sticky routing is now fixed and tested), so compare after a week of real use.

## Deferred, with protocols (not started on purpose)
- **STT (faster-whisper small.en vs Parakeet-TDT-0.6B-v3 int8 via sherpa-onnx):** record 30 of *your* typical commands on your mic, then compare word error rate (hand-checked), time to text and CPU %. Switch only if WER improves by ≥ 2 points or latency halves, with no regression on names and course codes.
- **Visemes:** `monkey/audio/visemes.py` estimates mouth shapes from FFT and loudness. Compare against (a) phoneme timestamps from a forced aligner and (b) a neural audio-to-face model, on 10 clips of Monkey's voice. Measure lip-sync offset and CPU cost. The avatar, GLB, clips and shape keys are unchanged in this sprint.
- **Not set up or installed (by decision):** Telegram, Honcho, Hermes, OpenClaw, subagents, and notifications or other outward-facing automations.
- **`bbu-project-status` skill:** needs a read-only GitHub tool and your approval of a fine-grained, read-only token for the BBU repo. It must read real commits, issues and releases, not design docs.

## Your one-time steps (nothing here was done on your PC)
1. Update Monkey to a build from this branch (after you approve the merge or release).
2. Settings → Memory → **Import context files…**: pick `profile.md`, `preferences.md`, `projects.md` and `classes.md` from your pack (not `README_IMPORT.md` or `IMPLEMENTATION_BRIEF.md`). Read the preview, then **Apply**. The backup lands in `%APPDATA%\Monkey\memory\memories\backups\import-…` and **Undo import** restores it.
3. Settings → **Morning brief**: **Detect from calendar** (needs Google or Outlook connected), check the times, then **Confirm schedule**.
4. Optional: enter your Canvas token's expiry date; preview and then **Enable** the scheduled task.
5. Optional: `python -m tools.bench_routing --live` for the classifier numbers.

## Fix: Google sign-in "does nothing", a calendar link without sign-in, and the routing benchmark in the app

**Root causes:**
1. Every toast was appended to `<body>`, and the modal Settings `<dialog>` sits on the browser's top layer above it. So **every message shown while Settings was open was invisible**, including Google's "add your OAuth client JSON first".
2. Google sign-in needs a Google Cloud *Desktop app* OAuth client, and there was no guide for creating one.
3. The browser flow blocked with no timeout and no visible link.
4. The calendar feed parser didn't expand repeating events, so a weekly class only existed at its first date.

**What changed:**
- **Toasts:** `dom.ts` puts toasts inside the open dialog; errors stay 6.5 s.
- **Client JSON check:** `google.validate_client` accepts Desktop clients only. A Web client, bad JSON or missing fields each get a specific message. It runs on paste, on **Load JSON file…**, and on sign-in.
- **Sign-in flow:**
  - `GoogleAuth.sign_in(on_url)` passes the sign-in link to the UI, which shows "Open Google sign-in" if no browser appeared.
  - Timeout is 5 minutes.
  - Errors are mapped to plain next steps (access_denied → add yourself as a test user, redirect → use a Desktop client, timeout).
  - `Api.google_sign_in` runs in the background with `google` events, and a second click is refused while one is pending.
  - Settings → Accounts has a 5-step **Set up Google** guide whose links open in your browser.
- **Calendar link (no OAuth):**
  - a `calendar_ics` secret holds one or more private iCal links (e.g. Google's "Secret address in iCal format");
  - `ICSCalendar` reads them with `source="ics"`, never as Canvas;
  - `parse_ics` expands RRULE/RDATE/EXDATE with `recurring-ical-events` (new dependency, bundled in the spec);
  - the link is test-read on save ("N events in the next 7 days");
  - it feeds the `get_calendar` tool, the brief's Today section, and **Detect from calendar**.
- **Recurrence counting:** `candidate_schedule` now counts a class as recurring by the same title and time on *any* weekday, so a holiday-skipped Wednesday doesn't drop it.
- **Benchmark in the app:**
  - the code moved to `monkey/brain/bench_routing.py`, and `tools/bench_routing.py` is now a wrapper;
  - Settings → Brain → **Run routing benchmark** runs it on your PC with the key Monkey already stores, logged in spend as `benchmark:routing`;
  - results show on a card and are saved to `%APPDATA%\Monkey\bench_routing.json`;
  - routing doesn't change automatically.
- **Why not run it from here:** the cloud session can't hold a Claude API key securely. The platform won't inject secrets into api.anthropic.com requests, and a plain environment variable is readable by anything run in this environment.

**Tests:**
- `tests/test_ics_recurrence.py` (5): expansion months after the first date, EXDATE, DST, schedule detection, URL parsing.
- `tests/test_google_bench.py` (9): client validation, error mapping, the sign-in link callback, 300 s timeout and token save, the API's needs-client path, background events with the second click refused, a Web client rejected on paste, calendar wiring that never includes Canvas, and benchmark aggregation and key requirement.
- Playwright (demo build): with Settings open, a sign-in error toast is **inside the dialog and on top** (`elementFromPoint` hit), the status line shows the reason, and the benchmark card renders.

Full suite: 263 passed, 1 skipped.

## Fix: Google sign-in still opened nothing (v0.3.33 regression) + Outlook kept launching

**Google.** To capture the sign-in URL, v0.3.33 replaced the global `webbrowser.get` with a shim whose `open()` called `webbrowser.open()`. That function looks browsers up through the same patched `get`, so it recursed until a `RecursionError`, which was swallowed. The shim stayed installed for the whole 5-minute wait, so the "Open Google sign-in" link (`MonkeyApp._open_url` → `webbrowser.open`) failed the same way. The old test faked `webbrowser.open`, so the recursion never ran.
- Now: a named controller (`webbrowser.register("monkey-google-signin", …)`) is passed as `run_local_server(browser=…)`, the library's supported hook. Nothing global is patched.
- `monkey/links.py` `launch_url` (http/https only; `os.startfile` on Windows, `open`/`xdg-open` elsewhere, the stdlib default last) is used by sign-in and by every link and website the app opens.
- The status line adds a **Copy link** button for when no browser opens.
- Tests drive the real stdlib `webbrowser` and fail on the v0.3.33 code.

**Outlook.** `OutlookProvider.available()` called `Dispatch("Outlook.Application")`, which starts Outlook. It ran on every UI state refresh, every "all calendars/emails" read and every brief check, and the `use_outlook` setting gated nothing.
- Now `available()` is a registry lookup (`HKCR\Outlook.Application\CLSID`) plus a new opt-in, `outlook_connected` (default off).
- Only **Connect** (`test_outlook`) starts Outlook, and success turns the opt-in on. **Disconnect** turns it off.
- Real reads attach to a running Outlook first (`GetActiveObject`) and start it only if it is closed. `read_email` also checks availability.
- Tests: `tests/test_outlook_optin.py`.

## Voice loudness matched to videos and music

The TTS played raw: Fish comes out around -20..-24 LUFS, and the offline and Windows voices vary. YouTube and Spotify normalize to about -14 LUFS, so at the same Windows volume Monkey sounded much quieter than a video.
- `monkey/audio/loudness.py` `Leveler` runs on each playback block in `Speaker._callback`:
  - gated speech-level tracking (quick up, slow down), remembered across sentences;
  - gain from -6 to +18 dB, moving only while he talks (no pumping in pauses);
  - a tanh soft limiter with a -1 dBFS ceiling.
- Calibrated on real LibriSpeech speech with an ITU BS.1770 meter: inputs from -30 to -18 LUFS come out at -14.7 to -12.4 LUFS, with about 1% of samples touching the limiter.
- Lip sync still reads the unboosted signal.
- Settings → Look & sound: **Monkey's voice volume** (25–200%, on top of the matched level) and **Match the loudness of videos and music** (on by default; off plays the engine's raw level).
- Tests: `tests/test_loudness.py`.

## Move to a new PC (v0.3.36)

The old Export/Import couldn't move a whole install:
- it left out `voice/`, `garmin/`, `skills/` and all keys (DPAPI ties `secrets.dat` to one PC);
- it copied `monkey.db` raw while open, so rows still in the WAL were lost;
- it overwrote `settings.json`/`monkey.db` under the running app, which then saved its old settings back over them.

Now (`monkey/memory/export.py`):
- **Format `MONKEY2`**: scrypt + Fernet over a zip of memory, settings, a SQLite online-backup snapshot of the db, voice, garmin, skills, and an opt-in `keys.json`.
  - `manifest.json` lists key names only.
  - Never included: `secrets.dat`, logs, `cache`, the voice pack, `export_password`.
- **`stage_import`**:
  - validates every entry (allowed top-level names only, no absolute or `..` paths, size cap);
  - unpacks to `<data>/_incoming/` and writes `.ready` last;
  - the app saves keys into the new PC's DPAPI store right away.
- **`apply_pending_transfer`** runs in `monkey/__main__.py` before settings or the db open:
  - moves the replaced files (plus any stale `-wal`/`-shm`) to `backups/pre-transfer-<time>/`;
  - clears `memory_dir_override`;
  - writes `last_transfer.json`, which the UI shows once.
  - It can resume after a crash, and drops an unfinished unpack.
- **Restart Monkey** relaunches after a 2 s delay, so the single-instance mutex is free.
- `MONKEY1` files still import.
- Tests: `tests/test_transfer.py`.
- User guide: `docs/MOVE-TO-NEW-PC.md`. Session handoff: `docs/HANDOFF.md`. Repo rules for future sessions: `CLAUDE.md`.
- `tools/sfx/raw/` and the AO bakes are now committed, so nothing lives only in a dev container.

## First run on the Dell: Google "Access blocked", schedule-first hint, Check everything (v0.3.37)

**Google "Access blocked … has not completed the Google verification process" (403 access_denied).** The OAuth app was in Testing and the account wasn't a test user. Google then never redirects back, so Monkey waited 5 minutes and reported a timeout.
- Fix on Google's side: Audience → **Publish app** (In production). A personal app needs no review and gets one "unverified app" screen. Testing mode also ends refresh tokens after 7 days, so publishing is the recommended path; the test-user route is the alternative.
- The waiting status now shows that hint and a **Cancel** button. `GoogleAuth.cancel()` sends one request to the flow's own localhost redirect (`error=access_denied` with the same `state`), so the wait ends right away. It refuses any non-localhost redirect. The result is reported as "cancelled".
- `credentials()` now catches `RefreshError`: it deletes the dead token and says to sign in again (and why).
- The setup guide was rewritten around Publish app.

**Morning brief "Enable" → "Confirm your class schedule first."** This works as designed, but the message now says how to confirm. Enable/Preview scroll to and highlight the weekday boxes and show the steps inline. Task status comes from `schtasks /Query` (`scheduler.is_registered`) instead of an in-memory flag that reset on every restart.

**Settings → Check everything** (`monkey/health.py`):
- Grouped checks: app/update/move, Claude key (free `models.list`), voice engines and devices, mic/wake word/listener/VAD, Google (client, sign-in, Gmail profile, calendar), calendar link, Canvas, Outlook (registry only), Garmin, memory/context pack/history, brief schedule and task, budget.
- Each group is isolated, with a 20 s timeout. Network checks are free reads.
- **Copy report** gives scrubbed text with no keys, tokens, JSON blobs, emails or links (tests seed real-looking secrets and assert they're absent).
- Tests: `tests/test_health.py` and additions to `tests/test_google_bench.py`.


## 2026-11-19: computer tasks + banana cursor (branch feature/computer-agent)
- `monkey/automation/`: the task model and store (`tasks.py`), the gate (`permissions.py`), the Playwright managed browser and
  the official toolset adapter (`browser.py`), the course skill (`course.py`), the Claude planner (`planner.py`), the manager
  loop (`manager.py`), the Windows UIA driver (`desktop.py`), the app service (`service.py`), the demo course (`democourse.py`),
  the banana cursor (`cursor/`, `cursor_events.py`, `cursor_native.py`).
- App: Tasks dialog, companion window (`OverlayApi`, `desktop_overlay.py` region click-through), e-stop hotkey
  `ctrl+alt+q`, tray items, `propose_computer_task` chat tool, cursor settings and preview.
- Lessons:
  - Playwright's AI snapshot refs gain a frame prefix after navigation (`f1e18`).
  - YAML-quoted lines appear when a name contains a colon.
  - The sync API is bound to one thread, so all tasks run on one worker.
  - A "paused, no Play button yet" lesson must not start the long wait.
  - The banana must snap to its target before pressing.


## 2026-11-20: v0.3.62 hotfix: "Too many strict tools"
- **Symptom:** every chat request returned 400 "Too many strict tools (24). The maximum number of strict tools supported is 20".
- **Cause:** all 24 local tools were declared `strict: true`.
- **Fix:**
  - `brain/tools.py` `STRICT_TOOLS`: the 14 tools with side effects stay strict;
  - `cap_strict()` drops `strict` beyond 20 at request time.
  - Regression test in `tests/test_playtest_fixes.py`.

## 2026-11-20: hybrid computer use (branch feature/hybrid-computer-use)
- `monkey/automation/computer/`:
  - `model.py`: targets, outcomes, `ErrorKind` + `RECOVERY`, capabilities;
  - `coords.py`: explicit IMAGE/VIEWPORT/SCREEN maps;
  - `router.py`, `trace.py`, `cache.py`;
  - `computer.py`: gate → idempotency → intent → driver → change → read-back → checkpoint;
  - `goal.py`: GoalRunner, planner tools, ClaudeGoalPlanner;
  - drivers: `browser.py`, `uia.py`, `visual.py`.
- Gate additions: `upload` (HIGH), `choose_file` (MEDIUM, or HIGH when the picker belongs to a browser), and `path_allowed` against `Task.files`.
- New task fields: `apps`, `files`, `allow_physical`, `success`. New states: PLANNING and RECOVERING.
- Lessons:
  - Focus markers (`[active]`) in aria snapshots made every click look like a change, so the signature strips them.
  - A click with no visible effect must still be remembered for MEDIUM+ actions; otherwise "Add item" runs twice.
  - LOW-risk navigation clicks may be retried.
  - After an approval, redo exactly the approved call right away.
  - WinForms controls without a Name get a numeric AutomationId that changes when the control is recreated; identity falls back to role + name, if unique.
  - A label with an AccessibleName hides its text changes from UIA.
## 2026-11-20: Monkey's browser is Chrome first
- **Setting:** `automation_browser` = `chrome` (default) or `edge`.
  - `pick_channel()` uses Chrome when it is installed (Program Files, LocalAppData, or the App Paths registry), else Edge.
  - Chooser in 🖐 Tasks.
- **Separate profiles:**
  - `automation-browser-chrome` for Chrome;
  - Edge keeps `automation-browser`, so its earlier sign-ins aren't lost.
- First Chrome run means signing in once (NetID/Duo).

## 2026-11-20: "Any website" (default) + pop-up tabs no longer break tasks
- **Owner's choice:** tasks may use any website, so Canvas, Duo and the module/video sites they open no longer stop for "Allow X?".
  - In code, `allowed_domains=["*"]`; `url_allowed` accepts any http(s) host.
  - Still blocked: `javascript:`, `file:` and hidden-character URLs.
  - The per-action gate is unchanged: no passwords or codes; sends, submits, buys and deletes need approval; quiz answers and attestations stay the user's.
  - Unticking "Any website" in 🖐 Tasks brings back the site list.
- **Pop-up fix:**
  - **Before:** when a pop-up tab (Duo, an external tool) closed, the session still pointed at it and reported "browser closed", so tasks lost their place.
  - **After:** `BrowserSession` falls back to the most recent open tab, both on `close` and in `alive()`.

## 2026-11-20: Monkey for Chrome (use the owner's own Chrome tabs)
- **`extension/chrome/`:** MV3, `chrome.debugger`.
  - Share-a-tab popup; pop-ups opened by shared tabs are shared too.
  - Pairing with mutual HMAC.
  - Blocks cookie reads and browser-wide CDP methods.
  - The stable extension id comes from the public `key` in the manifest; the private key is **not** in the repo (it isn't needed for "Load unpacked").
- **`monkey/automation/chrome_bridge.py`:** asyncio `websockets` relay on 127.0.0.1:47615.
  - `/extension`: Origin = Monkey's extension id, plus mutual HMAC.
  - `/cdp/<secret>`: Playwright `connect_over_cdp`.
  - Translates Target.* to `chrome.debugger` per tab (adapted from Playwright's MCP extension relay, Apache-2.0).
  - Ignores `Browser.close`; closes only tabs Monkey created.
- **`BrowserSession(cdp_endpoint=...)`:** connects instead of launching. `close()` only disconnects.
- **Setting** `automation_browser="my_chrome"`. The pairing token is in the DPAPI key store (`chrome_bridge`).
- **New dependency:** `websockets` (BSD-3).

## 2026-11-20: updates that "restart into the old version"
- **Symptom:** "Restart & update" ran, but Monkey came back on 0.3.66.
- **Cause:**
  - Quit, Restart and Restart & update ended the process with `os._exit()` without closing the computer-task browser.
  - Playwright's driver (`node.exe`, which lives inside the app folder) outlived Monkey.
  - Velopack can't replace a folder that's still in use, so it relaunched the old version.
- **Fix (`monkey/lifecycle.py`):**
  - Every exit path closes automation sessions (bounded), then ends any remaining child processes.
  - The updater runs that cleanup right before `apply_updates_and_restart`.
  - Startup ends leftovers still running from the app folder (never another `Monkey.exe` or `Update.exe`).
  - If an update attempt didn't take, Monkey says so once and asks you to press Restart & update again.
  - Tests: `tests/test_lifecycle.py`.
- **For a machine already stuck on an older build:** end `node.exe` in Task Manager (or reboot), then Restart & update.

## 2026-11-20: flagship program, Milestone 1 (reliability and safety)
- **Audit:** four independent audits (`docs/MONKEY-OPTIMIZATION-AUDIT.md`).
- **Fixed, each with a regression test:**
  - key-press approval bypass (P0);
  - forget now purges history and episodes;
  - sensitive content kept out of automatic recall;
  - effort messages keep `output_config` when the conversation is saved;
  - the key store never erases keys;
  - logs are redacted;
  - email voice confirmation is strict and reads back CC;
  - the injection guard lasts the whole conversation, and outside links aren't opened;
  - no remote media in markdown;
  - Claude and classifier timeouts;
  - the speaker reopens after a PortAudio reset, and wake cancels the reply before silencing the speaker;
  - brief weather line;
  - restart helper detached;
  - "Any website" data-out check.
- **Docs:** `docs/MONKEY-ARCHITECTURE-DECISIONS.md`, `docs/MONKEY-OPTIMIZATION-ROADMAP.md`, `docs/MONKEY-EVALUATION-BASELINE.md`.
- **Independent review, then fixed before the merge:**
  - key presses are scored before the target checks (Tab on a focused "Sign in" is just Tab); pywinauto key syntax (`^{ENTER}`, `%{F4}`) is understood; a line break in typed text counts as Enter; arrows/Space on quiz options are yours; Enter in a message box asks;
  - the data-out check skips pages with nothing loaded, counts long paths, and compares sites properly for `.co.uk`/`.ac.uk`;
  - "Yes. Send it.", "Yes, perfect." and "send it now" confirm; "yes, send it to everyone" doesn't;
  - audio: the speaker closes its stream before PortAudio resets, reopens once, retries when no output device was available, and the microphone opens and closes under the same lock;
  - the restart helper is no longer fully detached (its `timeout` needs a hidden console);
  - the classifier has no SDK retries, so its 4 s cap holds;
  - a deleted key file means no keys (the backup only covers a file that exists but can't be read);
  - docs: statuses say what is tested and where; the roadmap puts measurement and supply chain before new UI.
- **Tested in the container only.** Audio reopen and the update restart still need a check on the Dell.

## 2026-11-20: Outlook Connect did nothing
- **Cause:** Connect started Outlook through COM, which runs it hidden. On a PC where classic Outlook had never been opened and signed in, that hidden Outlook waited on its first-run sign-in screen, so the call never returned: no window, no message.
- **Fix (`monkey/integrations/outlook_com.py` `connect`, `Api.test_outlook`):**
  - Connect opens classic Outlook as a normal window, waits up to 90 s for it to answer (so you can sign in with your wisc.edu address), then reads one email.
  - It only attaches to a running Outlook; it never starts one hidden.
  - The whole call has a deadline and always comes back with a next step: new Outlook detected, Outlook didn't start, or Outlook isn't ready yet.
  - Settings shows "Opening Outlook…" while it waits and keeps the result under the button.
- **Tests:** `tests/test_outlook_optin.py` (sign-in wait, already open, new Outlook, won't start, always answers). Windows behaviour itself is unverified until it runs on the Dell.
## 2026-11-20: flagship Milestone 2 (voice reliability, measurement) and Milestone 3 (release trust)
- **Speaker races (D4–D6):** speaking state and the pending count change together under one lock, and the UI is told in order on its own thread; the stall watchdog waits while an engine is still inside its deadline; an interrupt makes the engine thread stop reading, closing the generator so Pocket frees its model at once; sentences queued before an interrupt are never spoken.
- **Echo guard (`monkey/audio/echo.py`):** in conversation mode a transcript that is mostly his own recent sentence is ignored; the mic reopens after the device's output latency plus 0.3 s.
- **"Monkey, stop":** a second keyword (also "stop monkey") silences him while he talks and never starts a recording.
- **Turn traces (`monkey/trace.py`):** per-turn monotonic stage marks from the mic (speech start, last voiced, end of turn) through STT, routing, context, first token, first sentence, TTS, first audible audio (output latency included) and barge-in silence; routing labels, rounds, cost, escalation and a "you corrected him next turn" signal. No speech text unless the owner turns on "Keep what I ask in local traces". `python -m tools.voice_report`, `python -m tools.bench_routing --from-traces`, and a Speed group in Check everything.
- **Importance:** only phrases aimed at Monkey ("this is important", "take your time") raise the tier; "any important emails?" no longer does.
- **Supply chain:** hashed lockfiles and a drift check, SHA-pinned actions, notices in the installer, an audit job that reports without blocking releases.
- **Tests:** `tests/test_m2_voice.py`, `tests/test_supply_chain.py`. Container only: audio timing on the Dell is unverified.

## 2026-11-20: flagship Milestone 4 (avatar state, render cost, companion)
- **One avatar-state rule (`ui/src/avatar/resolver.ts`)** for the main window and the companion: speaking > a task needs you > you're talking > thinking or a task working > idle, with minimum dwell times so blips don't flicker. Fixes D7 (the companion ignored "listening"/"thinking" while a task ran). Vitest tables (`ui/test/resolver.test.ts`, `npm test`) and a Playwright check in both windows (`tests/test_m4_avatar.py`).
- **Render tiers (`avatar3d.ts`):** full rate while he talks, listens, thinks, emotes, moves between poses, shows effects or follows your cursor; 30 fps when idle and still; 15 fps asleep; nothing when hidden. `stats` (frames, tier, why) is exposed for checks. Pixel ratio is unchanged (still up to 2), pending a measurement on the Dell, so nothing looks softer.
- **Quiet UI bus:** the mouth level is sent only when it changes, so silence costs zero `evaluate_js` calls (it was about 30 per second into both windows, even when idle).
- **Companion:** click areas are re-reported when the display scale changes.

## 2026-11-20: flagship Milestone 5 (memory quality)
- **Recall gate (`monkey/memory/recall_gate.py`):**
  - Automatic recall is skipped for tasks that never need your memory (commands, weather, pictures, check-offs), unless the message points at your past ("like last time", "remember", "usual").
  - Quick facts and web lookups still search, because wording-based routing sends "when does comet club meet?" there, but only strong matches are injected.
  - Only facts and episode summaries are injected, never raw old messages; `search_memory` still finds those when asked.
  - Each hit must share enough of the message's distinctive words, and a hit already in the recent conversation isn't repeated.
  - Each turn's trace records whether recall was skipped, empty or injected, and how many characters.
- **One write path:** the built-in memory tool is view-only. Every change goes through `remember` / `update_memory` / `forget_memory`, so nothing Monkey writes is labelled "you typed it" (`user_edit`).
- **Contradictions:** `remember` refuses a fact that contradicts a current one ("roommate is Sam" vs "roommate is Jordan", same subject with a different value, or mostly the same words with different details) and points the model at `update_memory`. The old fact moves to `superseded.md` instead of two "current" truths.
- **Tests:** `tests/test_recall_gate.py` (19 labelled recall cases, logging, 8 seeded conflict cases, view-only memory tool).

## 2026-11-20: flagship Milestone 6, P0 UI fixes
- Card titles are real buttons (`aria-expanded`), email rows and picture thumbnails open with Enter or Space, Quick/Auto/Important is a radio group with arrow keys, the chat log is a live region you can scroll by keyboard, and the mic and text box have labels. Landmarks and a top heading were added.
- The morning brief and unsent drafts are pinned: the 4-card limit drops the oldest other card instead.
- Narrow windows: the panel row can't grow past the window and the cards area shrinks (it scrolls), so the composer stays on screen at 420×700 with cards open.
- Tests: `tests/test_m6_ui.py` (axe at 1280 and 420 px with no serious or critical findings, composer position, keyboard, pinned brief).

## 2026-11-20: flagship Milestone 6, Today view (dashboard + focus)
- **Today** (header button ☀): Focus / Homework / Schedule tabs, with the composer docked underneath.
- **Focus:** the top assignment, why it's first, when it's due, Open on Canvas, and "Mark done in Monkey" with Undo (it only ticks it in Monkey; nothing is submitted). Below that, tiles for next due, today's schedule, unread email and weather.
- **Data:** `Api.dashboard()` reads the cached brief and the cached assignment board, so drawing it needs no network. Every section reports ok / empty / not_connected / unavailable and shows that instead of placeholder rows. No XP, levels or other invented data.
- **Narrow windows:** header buttons become icon-only, with labels kept for screen readers, so all six fit at 420 px.
- **Tests (`tests/test_m6_ui.py`):** zero rows when nothing is connected, no network while drawing, first draw under 300 ms (in the container), the tab keyboard pattern (arrows, Home/End, wraparound, roving tabindex), mark done and Undo, and no animations with reduced motion. axe shows no serious or critical findings at 1280 and 420 px.

## 2026-11-20: independent review of Milestones 2–6, fixed before merging
- **Echo guard (blocker):** answers that repeat his words ("the short version", "add it to my calendar") were dropped as echoes. Now an echo needs the timing of one (it starts within 0.6 s of his voice ending) plus 4 or more words, 90% of them in order from what he just said. The reviewer's cases are tests.
- **Remember (blocker):** the conflict check refused true facts ("plays piano" after "plays guitar", two allergies). `remember` never refuses now: it saves, and adds a "may replace" hint only for same-subject, new-value facts or ones sharing 2+ key words.
- **Branch base (blocker):** rebased onto `main`, so the Outlook fix (v0.3.71) is kept.
- **Turn traces:** a barge-in no longer finishes the new turn with the old reply's state, and each request finishes its own turn. "Interrupt → silence" is now recorded.
- **Speaker:** queued audio is tagged with its reply, so a late end-of-sentence marker from an interrupted reply can't end the next one.
- **Recall:** questions about you ("what's my advisor's name?") use normal matching even when routed as quick facts.
- **Today view:**
  - It says "and on your Canvas planner" when the tick also synced to Canvas.
  - It never fetches while drawing; it loads in the background with a "Loading…" state.
  - Yesterday's brief is never shown as today.
  - It closes when a reply, card or draft arrives.
  - Stale draws are ignored and errors are caught.
  - Focus moves to Undo and back to the Today button.
  - Undo lasts 10 s.
- **Render tiers:** the busy tier runs at the display's own rate (75/120/144 Hz), not 60.
- **Privacy:** request text kept in traces (opt-in) is removed when history is deleted or the option is turned off.
- **Tracer:** file writes happen outside the lock, and "no thanks" no longer counts as a correction.
- **Tests:** the reduced-motion test checks the whole page; the network test lost an always-true condition. A new non-gating CI job (`ui-browser`) runs the browser UI tests on every push.

## 2026-11-20: self-improvement loop for agents working on Monkey
- `docs/agent-lessons.md`: short rules, each with its reason, seeded from this project's own failures, wasted context and owner corrections. CLAUDE.md tells every agent to read it before starting and to fix or retire a rule that proves wrong.
- `tools/lessons/collect.py` finds corrections, failures and waste in run logs (JSONL), redacted.
- A weekly scheduled review (Sundays 7:32 PM Central) reads the week's sessions and updates only that file. A push that changes only that file doesn't build a release (`paths-ignore`).


## Sound rebuild, sprint 1 (branch `work/monkey-sfx-foley-redesign`, 2026-11-20; not merged)

Audit, sources, the bible and results are in `docs/audio/` (`SFX_AUDIT.md`, `SOURCE_LEDGER.md`, `SONIC_BIBLE.md`).

**Engine (`ui/src/avatar/sfx.ts`):**
- Fisher–Yates shuffle bag. The old sort-based one led with take 1 36% of the time.
- Takes leveled per cue on decode.
- Master limiter with makeup compensation.
- UI choke group with ranks.
- UI sounds bypass the polyphony cap.
- Hot-cue preload: `attach()` waits only for those; the rest load in batches, loops on demand.
- `loop()` handles and `stopAll()`, with stop on window hide.
- Preview isolation in the Sound Lab.
- `useVariant()` for the Sound Lab's Now · B · C switch (setting `sfx_variants`).

**Wiring:** `ui_open`/`ui_close` on dialogs, `check`/`ui_error` on result toasts and flashes, `notify` on drafts, task permissions and ready updates. Sound Lab take buttons make no click.

**Assets:**
- No shipped take changed.
- 105 CC0 candidate takes for 13 cues are in `ui/public/sfx/candidates/`, rendered by `tools/sfx/recipe.py` from `tools/sfx/recipes/sprint1.json`, with sources pinned by SHA-256.
- Zero paid audio calls.

**Tools:** `tools/sfx/inventory.py`, `mixcheck.py`, `recipe.py`, `abclips.py`, `reel.py`.

**Tests:** `ui/test/sfx.test.ts` (18, fake audio graph) and `tests/test_sfx_wiring.py` (3, real UI in Chromium).

**Open:**
- blind listening results (review page);
- trigger-to-sound latency and laptop-speaker check on the Windows PC;
- the near-silent `ear_perk` take (owner's call in the Sound Lab).

## 2026-11-23: to-do list (branch `feature/todo-list`)

The owner asked for "a to do list UI that can remember everything I need to do and help me out with completing it".

**Storage:** `monkey/memory/todos.py` `TodoStore`, a `todos` table in `monkey.db` (so it moves with the `.monkey` transfer file and never touches the repo or the memory files).
- Fields: text, notes, due, priority (low/normal/high), list tag, status, steps (JSON checklist), source (typed/voice/Monkey), created/updated/done/deleted timestamps, reminder bookkeeping.
- Due dates are local wall-clock strings, `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`; a day-only item is overdue after midnight.
- Migration-safe: missing columns are added on open. Deletes are soft (Undo), purged after 30 days.
- `split_quick` parses "call the dentist tomorrow 5pm !high #health". `ui/src/todoparse.ts` is a port of it; both must pass `tests/todo_due_cases.json` (pytest, vitest and the browser test check it).

**UI:** 📝 To-do header button and card (`ui/src/todo.ts`, assignments look): quick add with a visible parsed-date chip and date/time/priority fields to correct it, check off and delete with Undo, inline editor (text, due, priority, list, notes, steps), step checkboxes in the row, Open/Overdue/Done tabs, sort by due or priority, empty states, reminder toggles. Demo data in `?demo`. At under 560 px the header buttons now wrap instead of falling off.

**Brain:** `add_todo`, `list_todos`, `update_todo`, `delete_todo` (the three writers are strict).
- `add_todo` only adds when the user's message asks ("add", "remind me", "my list", or a yes after an offer). Otherwise it tells the model to offer. Evidence must quote the user; with no explicit ask, the item's words must come from the user. At most 10 adds per turn.
- `update_todo` refuses while outside content (email, calendar, web) is in the conversation unless the user's own message asks for a change. `delete_todo` needs a quoted "delete/remove" request.
- "Help me with X": the tool description and persona say to save 3–6 steps and then use existing tools (open_website, get_assignments, show_on_screen, draft_email as a draft only, propose_computer_task with the user's approval). No new outward action exists.
- Router task `todo` (rule + classifier + policy Haiku low / medium / Sonnet medium), calibration sample and stubs, 4 bench cases, `docs/MODEL-POLICY.md` regenerated.

**Reminders:** in the app only. `MonkeyApp.todo_tick` (every 30 s) shows a toast with Done / Snooze and a wave, once per due time, from 10 minutes before until 2 hours after. Speaking it is opt-in (`todo_speak_reminders`) and waits until Monkey is idle. No Windows or phone notifications: that needs the owner's OK first.

**Morning brief:** a To-do section (overdue, due today, high priority) and the top to-do as top priority when Canvas has nothing due.

**Tests:** `tests/test_todos.py` (store, parsing, gates, fake-client agent loop, reminders, API, brief, routing), `tests/test_todo_ui.py` (Playwright in `?demo&svg`, added to the CI browser job), `ui/test/todoparse.test.ts`.

**Open:** not tried on the Dell. Windows notifications for reminders are a question for the owner.

## 2026-11-23: reminders as Windows notifications and on the phone (branch `feature/todo-notifications`)

The owner asked: "Make reminders appear as windows notifications and on my phone too." That is the owner's OK for these two outward channels (CLAUDE.md: ask first). Both are settings in **Settings → Reminders**; nothing else became outward-facing.

**Tick:** `MonkeyApp.todo_tick` still decides once per due time (`TodoStore.due_reminders` + `mark_reminded`; a snoozed item comes back once when its snooze ends). Each channel has its own switch: `todo_reminders` (note in the window, + `todo_speak_reminders`), `todo_windows_notify` (default **on**), `todo_phone_notify` (default **off**, needs setup). The tick runs only if at least one channel is on.

**Windows (`monkey/notify/wintoast.py`):**
- Library: `windows-toasts` 1.3.1 (MIT, WinRT through `winrt-*` 3.2.1 wheels). Pure Python on prebuilt WinRT wheels, `InteractableWindowsToaster` supports buttons and click callbacks. Pinned `<1.4`: 1.4.0 (winrt 4.x, COM activator) came out the day this was built. Alternatives: `winotify` (last release 2022; starts PowerShell for every toast, button clicks only open URLs or its own protocol handler, no callback into Python) and `win11toast` (also WinRT, but pulls in a dozen winrt packages for OCR/media/speech features Monkey doesn't need).
- Identity: registers AUMID `velopack.Monkey` (Velopack's default process ID) under `HKCU\Software\Classes\AppUserModelId` with DisplayName "Monkey" and the icon. This works for an unpackaged PyInstaller/Velopack app without a shortcut AUMID. No COM activator: clicks reach Monkey while he runs (window hidden in the tray included); a toast from before a restart opens nothing.
- Toast: line 1 the item, line 2 "Reminder · due today 5:00 PM (· high priority)", buttons Done and Snooze 10 min (the in-app handlers: `todos.complete` / `todos.snooze` + a `todo_changed` event), the body opens the window and the To-do panel (`todo_open` event). High-priority items use the Reminder scenario (stays until handled). Expires after 12 h.
- No double reminder: skipped when the in-app note is on and Monkey's window is the foreground window (`GetForegroundWindow` belongs to our process). Done/snooze/delete in the app removes the toast from Action Center.
- Not Windows (Linux CI): `UnavailableBackend`, status "only work on Windows", nothing shown. Bundling: `monkey.spec` collects `windows_toasts` and `winrt`; the exe selftest imports them and builds a toast.

**Phone (`monkey/notify/ntfy.py`):** ntfy JSON publish to the server root (the topic is in the body, not the URL), `Title: Monkey reminder`, priority 4 for high items (else 3), tag ⏰.
- Topic `monkey-` + 32 random URL-safe characters, made by "Set up my phone", saved with `keys.set("ntfy_topic")` (secrets.dat, DPAPI), never in settings.json. Optional access token `ntfy_token` through the same key field pattern. "New topic" replaces it.
- Server `ntfy_server` (default https://ntfy.sh, self-hosted allowed; plain http only for local/home-network hosts).
- Privacy toggle `todo_phone_show_text` (default on, explained in the UI): off sends only "You have a reminder".
- Every request: 5 s timeout, one retry for network errors/5xx/429 (no retry on other 4xx). Reminders go through one background worker; the tick never waits. Failures set a quiet status line in Settings; logs carry only the error class or HTTP code, never topic, token or text.
- Setup UI: install ntfy, subscribe to the shown topic (Copy), or scan a QR code drawn locally (`qrcode-generator`, MIT), "Send test notification".

**Tests:** `tests/test_reminder_notify.py` (fake toast backend: once per due, buttons, snooze, retract, focus skip, failures, non-Windows no-op, a Windows-only real-library check; fake ntfy HTTP: request shape, priority, privacy, timeout, retry once, no secrets in logs, background queue; settings persistence with the real `keys` store), `tests/test_reminder_settings_ui.py` (Playwright, `?demo&svg`).

**Not verifiable in the cloud container:** a real toast, its buttons and clicks from Action Center, and a real ntfy delivery. Try on the Dell: Settings → Reminders → Send a test Windows notification, then Set up my phone → Send test notification.

## 2026-11-23: companion window only while a task runs
- The owner didn't want the extra monkey (the companion window) at startup. It now starts hidden and shows only while a computer task is under way (planning, running, waiting, paused or waiting for the owner), then hides when the last task ends or on Stop all.
- `AutomationService` tracks live tasks from its `automation` events (`task_running`) and calls `MonkeyApp.on_task_running` → `_overlay_visibility`. The Settings/tray switch (`overlay_enabled`) and computer access still win. The tray's "Show companion" appears only during a task.
- On first show, `desktop_overlay.install` runs again if the hidden window wasn't found at startup, and re-shows the window so the taskbar drops its button (Windows only re-reads `WS_EX_TOOLWINDOW` on hide/show).
- Tests: `tests/test_companion_visibility.py`.
## 2026-11-23: several Gmail accounts + Outlook, and "Suggested from email" for the to-do list (branch `feature/todo-email-accounts`)

The owner asked to "add the ability to connect multiple gmail accounts and my outlook account to the task queue" (the to-do list).

**Accounts (`monkey/integrations/google.py`, `monkey/integrations/accounts.py`):**
- One OAuth client (`google_client`) and one token per Google account. All tokens are in one secret, `google_accounts` = {"gmail": token, "gmail-2": token, …}, in the same DPAPI `secrets.dat` as every key, so Move-to-a-new-PC carries them.
- **Migration:** the old single token (`google_token`) moves to account `gmail` on the first read (`google.migrate_legacy_token`, called by every account lookup). The old key is deleted only after the new one is saved and read back; if saving fails, the old key stays and it tries again next time. The old "Connected as" address (`settings.google_account`) moves into that account's entry. An old `.monkey` file imported later just becomes another account (or the same one, if it's the same token).
- Non-secret parts are in `settings.email_accounts`: {id: {label, address, scan_todos}}. The address is shown only in Settings on this PC: never in logs (`logsafe` redacts addresses anyway), the Check-everything report (accounts there are named by label) or tests (made-up `example.com` addresses).
- Signing in again with an address that's already connected refreshes that account instead of adding a duplicate. `GoogleAuth(account_id)` is per account; `GoogleAuth()` (app-wide) runs the sign-in and means "the first account" for older callers.
- Outlook stays the opt-in classic-Outlook COM provider (Connect/Disconnect unchanged). It gets a label like the others.

**Brain (`monkey/brain/tools.py`, `approval.py`):**
- `get_emails` reads every connected inbox by default, merges newest first and tags each email with `account` (id) and `account_label`. `account` takes 'all', 'gmail' (every Gmail account), 'outlook', or an account label/id.
- `read_email` finds the right inbox from the email id (cached from `get_emails`) even when asked for plain "gmail".
- `draft_email` must resolve to exactly one account: with several Gmail accounts and no name, it asks which; a reply goes out from the inbox the email came in to. The draft card and the spoken read-back name the account ("Sending … from your Club account to …"). The approval gate sends only through the account the draft was made in.

**Suggested from email (`monkey/brain/email_todos.py`, `monkey/memory/todo_suggestions.py`):**
- Per account, "Find to-dos in this inbox" (off by default). `MonkeyApp.start_email_todo_scan`: first check 90 s after start, then every `email_todo_scan_min` (15) minutes, plus right after a switch is turned on.
- Read-only: recent (3 days) unread or flagged/starred mail and open Outlook tasks, subject + preview only (Gmail `metadata` format, no bodies). Each inbox read has a 45 s deadline in a separate thread.
- Outlook is only read if `outlook.exe` is already running, by attaching (`GetActiveObject`). The scan never starts Outlook, hidden or visible (the hidden-launch hang from v0.3.71).
- Local filter first: flagged/starred and Outlook tasks are strong signals; newsletters/promos/notifications (Gmail's tabs, List-Unsubscribe, bulk senders, "unsubscribe" text) are dropped; other mail needs a request ("can you…", "please…", "due Friday"). Near-misses tested: "proofread the newsletter draft", "ignore my previous email… please confirm", "AI club… RSVP".
- Assistant-directed mail ("ignore previous instructions", tool names, "Monkey, add…") is skipped before any model sees it.
- Then at most one call per scan to the routed cheap model (new internal policy task `email_todos`, Haiku low), for up to 8 new emails that passed the filter, no tools, skipped at 90% of the monthly budget, usage recorded as `email_todos`. Its quote must appear word for word in the email and its to-do text can't contain links or addresses; otherwise the local suggestion stands. It can turn a plain email down, but not one the owner flagged.
- Every email looked at is remembered by (account, message id) as pending/accepted/dismissed/skipped, so nothing goes to the model twice and a dismissed suggestion never returns. Only the quoted line and subject are stored (monkey.db), never bodies, and never in memory facts.
- **Accept** (the owner's click) adds the to-do through `TodoStore.add` (source `email`) and records its origin (account label, quote, subject, link) in a new `origin` column. Flagged/task suggestions come in as high priority. **Dismiss** is permanent. **Open** shows the email in Gmail, or in Outlook if it's open.
- The brain sees accepted items' account (`list_todos` → `from_email_account`) and how many suggestions wait (a count only; it can't accept them). The morning brief's To-do note says "N suggested from email".

**UI:** Settings → Accounts lists every connected inbox (`ui/src/accounts.ts`): kind, a label you can rename, the address, "Find to-dos in this inbox", Remove (Gmail), and "+ Add another Gmail account". The to-do panel has a collapsible "Suggested from email" section on the Open tab (`ui/src/todosuggest.ts`, its own CSS file) with the account label, sender, due date, the quoted line, and Accept / Dismiss / Open. Accepted items show "✉ <label>". `?demo&accounts` shows made-up inboxes (plain `?demo` is unchanged).

**Tests:** `tests/test_email_accounts.py` (token store, migration and failed-save safety, sign-in add/refresh/remove, merged reads with labels, drafts naming and using the right account, screen rules and near-misses, strong signals, the injection email reaching neither the model nor the list, model output checks, budget, Outlook never started, a hung read abandoned, accept/dismiss persistence across a restart, the brief note, no addresses in logs). `tests/test_email_accounts_ui.py` (Playwright, added to the CI browser job).

**Not done / open:** not tried on the Dell or with a real Google or Outlook account (cloud container). Outlook flagged-mail and Tasks reads are written against the documented Outlook object model but only exercised with fakes. Calendar events that two Google accounts share can show twice.
## 2026-11-23: phone screen time in the to-do list (branch `feature/todo-screen-time`)

The owner asked to "add connecting to my phone's screen time to the task queue". Research, per-platform paths, what's impossible and the owner's setup steps: `docs/research/PHONE_SCREEN_TIME.md`. Opt-in, off by default (Settings → Phone). The owner's phone is an iPhone, so iPhone is the default and primary path; Android is secondary.

**Ingest** (`monkey/integrations/screentime.py`): the phone sends a daily summary; Monkey never reaches into the phone or opens a port.
- Folder inbox: new `*.json`/`*.csv` files in a synced folder (iPhone: Shortcuts *Get App & Website Data* → iCloud Drive → iCloud for Windows; Android: Syncthing). Each file is read once (name + size + mtime).
- Encrypted ntfy relay (Android/Tasker): polled over outbound HTTPS every 20 min. Only `mst1.` sealed messages are accepted: AES-256-CBC + HMAC-SHA256 (encrypt-then-MAC) under a pairing key in DPAPI (`keys` name `screentime_pair`, not in the transfer export). The Tasker JavaScriptlet (`TASKER_JS`, crypto-js 4.2.0) was run under Node and opened by the Python side; a crypto-js vector is pinned in the tests.
- Manual: today's total plus the top app and its time (read off Settings → Screen Time) in the To-do panel, or import a JSON/CSV file. This is the iPhone's zero-setup path and the fallback when Shortcuts has no Screen Time action.
- Strict validation: size/count caps, minutes 0–1440, bounded dates, clean durations only, app names reduced to 40-character plain labels. A later automatic reading only replaces a bigger-or-equal one (replays can't roll a day back); manual always wins.

**Storage:** `monkey.db` tables `screentime_days`, `screentime_goals`, `screentime_seen`, `screentime_meta`; 30 days kept by default; *Forget data* deletes the usage data (goal to-dos stay).

**To-do list:** phone card above the list (`ui/src/screentime.ts` + `screentime.css`, mounted from `main.ts`'s `todoCard`, so `todo.ts` is untouched): today vs goal, 7 days, top apps, pickups, manual entry, goal to-dos. Goal to-dos (`Phone under 2h today`, `30m or less on Instagram today`, `Social apps under 3h today`, optional daily repeat) are normal to-dos in list `phone`; app-group goals add up a named set of apps, matched case-insensitively and by alias (`app_key`: YT, IG, Tik Tok, package names, youtube.com), and the card offers the owner's "Social: TikTok, Instagram, YouTube ≤ 3h" as a one-click daily goal (never created on its own); they get an "Over" note during the day and check themselves off (or stay flagged) once the day is over. A gentle suggestion shows when phone time passes the goal and an important to-do is open; once a day it also emits `screentime_nudge` and calls `ScreenTime.on_nudge` (the hook for the notifications work; no OS/phone notification here).

**Brain / brief:** `get_screen_time(day)` read-only, in `UNTRUSTED_TOOLS` (app names are outside text); `health` router rule + 2 bench cases; persona line; calibration stub. Morning brief *Phone* section with yesterday vs goal.

**Settings → Phone** (`#set-phone`, nav button "Phone"): toggle, iPhone/Android, path, goal, folder, relay, Pair phone with a QR code (the reminders' `qrSvg`, `qrcode-generator`), copyable Tasker script, status, Check now, Import, Forget data, brief and suggestion toggles.

**Tests:** `tests/test_screentime.py` (parsing incl. malicious payloads, sealing/tamper/known vector, relay with a fake HTTP, folder inbox, retention, goal evaluation, suggestion hook, tool, brief, routing), `tests/test_screentime_ui.py` (Playwright `?demo&svg`, added to the CI browser job).

**Open:** not tried on a phone or the Dell. The iOS action's output format and Tasker App Info's variable names are unverified (the parser is lenient; the doc says what to check). The `feature/todo-notifications` branch didn't exist yet, so there was no ntfy code to share.

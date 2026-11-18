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
- Rules cover **28/42** at **27/28 correct (96%)**.
- The remaining **14** go to the Haiku classifier.
- The only miss was ambiguous ("open my email": inbox vs. Gmail website) and is now labeled as either.
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

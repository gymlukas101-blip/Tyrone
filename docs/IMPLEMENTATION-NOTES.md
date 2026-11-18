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

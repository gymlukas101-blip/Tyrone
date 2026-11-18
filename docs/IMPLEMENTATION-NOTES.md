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

# Monkey optimization audit (2026-11-20)

**Baseline:** `main` at v0.3.68 plus the unmerged `feature/hybrid-computer-use`.

**Method:**
- Four independent read-only audits:
  - A: intelligence and memory;
  - B: voice, companion and desktop;
  - C: reliability and security;
  - D: UX against the two jungle mockups.
- Each external project was read at a pinned commit; no external code was copied.
- Every bug marked **fixed in M1** has a regression test in `tests/test_m1_fixes.py`, `tests/test_automation_core.py` or `tests/test_lifecycle.py`.

**Statuses:**
- **✓ tested:** implemented, and tests cover it.
- **◐ unverified on PC:** implemented and tested, but not yet run on the owner's Dell.
- **△ partial:** implemented in part.
- **◯ docs only:** described in the docs, not implemented.
- **✗ missing:** not implemented.
- **⚠ broken:** implemented but not working.
- **UX:** works but is poor to use.

## Deliverable A: current capability report

| Area | Capability | Status | Evidence |
|---|---|---|---|
| Brain | Streaming tool loop: 12 rounds, history repair, rollback | ✓ tested | `brain/agent.py:455-575`; `test_agent_loop.py`, `test_recovery.py` |
| Brain | Rule router: 28/28 correct on the 28 of 42 bench cases it handles | ✓ tested | `brain/router.py:56-133`; `python -m tools.bench_routing` |
| Brain | Haiku classifier (the other 14/42) | ◐ never measured live; now timeout-bounded (4 s) | `router.py:161` |
| Brain | Prompt caching (1 h system prompt, automatic caching) | ◐ cache hits never checked | `agent.py:438-443` |
| Brain | Per-message effort | ✓ tested. Fixed in M1; before that, saving the conversation stripped `output_config`, and the API's 400 then dropped history. | `agent.py:249` |
| Brain | Context compaction | ✗ missing (20-min idle reset only) | `agent.py:32` |
| Brain | Importance detection | UX: the word "important" in content becomes the Important tier (Opus) | `router.py:48-52` |
| Memory | Facts with provenance and supersession | ✓ tested | `memory/facts.py` |
| Memory | FTS5 history, episodes | ✓ tested; episode generation ◐ | `memory/history.py`, `app.py:356-389` |
| Memory | Forget | ✓ tested. Fixed in M1 (purge); before that, tombstones were never read, so forgotten facts came back from old messages and episodes. | `history.py` `forget()` |
| Memory | Sensitive content in recall | ✓ tested. Fixed in M1; before that, health/family details leaked from old messages and episodes into recall. | `history.py` `search()` |
| Memory | Per-turn recall gating | UX: runs on every message, not gated | `agent.py:368-392` |
| Memory | Contradiction detection | △ explicit updates only | `facts.py:129-133` |
| Memory | Dream/consolidation, embeddings, MCP, tool search | ◯ docs only / ✗ | `AGENT-ROADMAP.md` |
| Voice | Endpointing (Silero), Whisper on CPU, Fish/Pocket/SAPI fallback, leveler, visemes | ✓ tested | `audio/*` |
| Voice | Mic reconnect | ◐ unverified on PC. Fixed in M1 with fake streams only: one PortAudio lock, the speaker closes before the reset and reopens after, and retries with no device. Before that, a mic reconnect silenced the speaker. | `audio/devices.py`, `speaker.py` |
| Voice | Barge-in | △ partial: wake word / push-to-talk only ("Monkey, stop" while he talks is M2). M1 fixed one bug: a wake used to let the old reply keep talking. | `app.py` `_on_wake` |
| Voice | Speaker state races (D4–D6), echo guard, turn-latency metrics | ⚠ / ✗. Next milestone. | `speaker.py:74-76,200`, `app.py:513` |
| Companion | Click-through overlay, no-activate, capture exclusion | ◐ | `desktop_overlay.py` |
| Companion | Companion avatar state | ⚠ the task mood overrides voice states (D7) | `ui/src/main.ts:1509` |
| Avatar | Idle brain, look-at, sleep, VFX | ✓ (no unit tests); render throttling △ | `ui/src/avatar*` |
| Computer use | Course tasks, permission gate, managed/own Chrome, hybrid browser↔Windows | ✓ tested (see `docs/research/COMPUTER-USE-QUALITY.md`) | `automation/*` |
| Computer use | Key-press approval | ✓ tested. Fixed in M1: keys are scored by what they land on (also pywinauto `^{ENTER}` syntax and typed line breaks); arrows/Space on quiz options are yours. Before that, Enter on a focused "Send", Delete and Ctrl+Enter went through unasked. | `permissions.py` `_press_risk` |
| Computer use | "Any website" (owner's choice) | △ partial: a typed address to another site that carries a lot of data (query, fragment or path) now asks. Data sent by clicking a page's own links or forms is not caught by this check. | `permissions.py` `_looks_like_data_out` |
| Safety | Email approval by voice | ✓ tested. Fixed in M1: only a plain yes ("Yes. Send it.") sends, and CC is read back. Before that, "yes, but…" counted as yes. | `brain/approval.py` |
| Safety | Injection guard | ✓ tested. Fixed in M1: taint lasts the whole conversation; outside links aren't opened unless the user named them. Before that, it was per turn. | `brain/tools.py` |
| Safety | Markdown image exfiltration | ✓ tested in the built UI (skipped in Linux CI, where the UI is built after pytest). Fixed in M1: no remote media in markdown. | `ui/src/main.ts` `md()` |
| Data | Key store | ✓ tested. Fixed in M1: retry, backup, strict writes; a deleted key file stays empty. Before that, one failed read could erase every key. | `secretstore.py` |
| Data | Logs | ✓ tested. Fixed in M1: quiet HTTP loggers plus a redacting filter. Before that, API keys, private ICS links and URLs were logged. | `logsafe.py` |
| Reliability | Claude timeouts | ✓ tested. Fixed in M1: 120 s read, 5 s connect, classifier 4 s with no retries. Before that, a 600 s read timeout could freeze Monkey. | `app.py` `_ensure_client` |
| Reliability | Update and restart | ◐ unverified on PC. v0.3.68 fixed restarting into the old version; M1 fixed the restart helper being killed. Windows behaviour is tested only in CI. | `lifecycle.py` |
| Brief | Weather line | ✓ tested. Fixed in M1; before that, it printed a raw data dump with the real NWS data. | `routines/morning.py` `weather_line` |
| UI | Narrow window (420 px): input pushed off-screen; brief pushed out by the 4-card limit; a11y and contrast gaps | UX. Next milestones. | Agent D report |

**Still open, ranked in [the roadmap](MONKEY-OPTIMIZATION-ROADMAP.md):**
- speaker races D4–D6;
- companion state resolver;
- render throttling and idle UI traffic;
- recall gating;
- one memory write path;
- traces for routing;
- supply chain (lockfile, pinned actions);
- LICENSE and third-party notices;
- dashboard and focus workspace.

## Deliverable B: GitHub research (strongest relevant mechanisms)

| Project @ commit (license) | Strongest mechanisms | Monkey verdict |
|---|---|---|
| isair/jarvis @ `9d90257` (**custom non-commercial**: ideas only) | <ul><li>Deterministic recall gate (`memory/recall_gate.py`)</li><li>Merge-on-write supersession (`graph.spec.md:296`)</li><li>Summariser hygiene rules</li><li>Persistent MCP runtime with per-server lock, retry, idle/invoke timeouts (`mcp_runtime.spec.md`)</li><li>`toolSearchTool` that explicitly grants no authorisation</li><li>Dictation: single PortAudio lock, clipboard paste with foreground check (`dictation.spec.md`)</li><li>Echo guards (`listening.spec.md:261-299`)</li></ul> | ADAPT: recall gate, PortAudio lock (done), echo guard, dictation focus protection. REJECT: per-turn planner/evaluator (built for small local models). |
| open-jarvis/OpenJarvis @ `427c2dd` (Apache-2.0) | <ul><li>Session-wide taint and sink policies (`tools/_stubs.py:216-490`) — implemented</li><li>Trace store and analyser — implemented</li><li>Learned router: coarse 5 classes; GRPO is a stub</li><li>Memory injection with a score floor</li><li>Benchmarks measure latency, not quality</li></ul> | ADOPT: session-wide taint (done). ADAPT: local traces for routing evals. REJECT: auto-learned routing for now. |
| HKUDS/nanobot @ `7935176` (MIT) | <ul><li>Cursor-based "dream" consolidation with `[correction]`/`[durable]` tags and git-committed memory diffs (`agent/dream.py`)</li><li>Idle auto-compaction</li><li>Tool-result budget (16k chars → file)</li><li>Per-MCP-server `enabled_tools` allowlist</li><li>Skills only after a workflow repeats</li></ul> | EXPERIMENT: dream that *proposes* edits. ADAPT: tool-result budget. DEFER: MCP until a server is needed. |
| ayangweb/BongoCat @ `47a73ed` (Apache-2.0) | <ul><li>`WS_EX_TRANSPARENT \| WS_EX_LAYERED` for true click-through</li><li>`WM_DPICHANGED` suggested rect</li><li>Settle-delayed placement on the union of displays</li><li>Hover-fade and idle-hide state machines</li><li>FPS cap, occlusion handling</li></ul> | ADAPT: DPI and placement, FPS tiers. |
| rullerzhou-afk/clawd-on-desk @ `7a9b041` (**AGPL**: ideas only) | <ul><li>State priority table</li><li>Per-state minimum dwell and auto-return</li><li>`WM_MOUSEACTIVATE → MA_NOACTIVATE` (Chromium ignores `WS_EX_NOACTIVATE`)</li><li>Permission bubbles that don't auto-dismiss</li><li>Edge-peek mini mode</li></ul> | ADAPT: avatar state resolver, no-activate hook. DEFER: edge peek. |
| LorisYounger/VPet @ `b04db82` (Apache-2.0) | <ul><li>Start/Loop/End animation phases</li><li>Interaction vocabulary (touch head/body, raised, side-hide)</li><li>Boredom-weighted idle</li><li>Petting by mouse waves</li></ul> | DEFER: after the state resolver. |
| joelwilsonmt/personal-dashboard | **Not accessible** (GitHub asks for credentials, i.e. private or nonexistent). No details are claimed. | Use the two owner mockups instead. |

**Engineering principles applied** (sources cited in `docs/AGENT-ROADMAP.md` and `docs/research/COMPUTER-USE-RESEARCH.md`):
- enforce in code, not prompts;
- verify before saying "done";
- compact, just-in-time context;
- treat page, email and tool output as untrusted data;
- bounded retries and timeouts.

## Deliverable C: prioritized backlog

**Score:** user value 30%, reliability and safety 20%, capability 20%, effort 10% (inverted), performance/cost 10%, integration risk 10% (inverted). Each factor is rated 1–5, so the score is out of 5; it is a decision aid, not a measurement.

**Verdicts:** ADOPT (do it), ADAPT (do a modified version), EXPERIMENT (try it behind measurement), DEFER (later), REJECT (no). **Status:** P0–P2 are priority; **done** means it shipped in Milestone 1.

| # | Feature | Source | Gap | Verdict | Score | Status |
|---|---|---|---|---|---|---|
| 1 | Key-press risk by focused target and dangerous chords | Agent C | P0 approval bypass | ADOPT | 4.8 | **done** |
| 2 | Forget purges history and episodes; sensitive filter on recall | jarvis gate idea, Agent A | privacy | ADOPT | 4.6 | **done** |
| 3 | Key store never erases keys; log redaction | Agent C | data loss and secrets in logs | ADOPT | 4.6 | **done** |
| 4 | Session-wide taint; guarded `open_website`; no remote markdown media | OpenJarvis taint | injection and exfiltration | ADOPT | 4.5 | **done** |
| 5 | Effort persistence fix | Agent A | silent context loss | ADOPT | 4.4 | **done** |
| 6 | Speaker reopen and PortAudio lock; wake-order fix | jarvis dictation lock idea, Agent B | mute after device change | ADOPT | 4.4 | **done** |
| 7 | Strict voice confirm and CC read-back | Agent C | wrong email sent | ADOPT | 4.3 | **done** |
| 8 | Claude and classifier timeouts | Agent C | 10-min freeze | ADOPT | 4.2 | **done** |
| 9 | Brief weather line; restart-helper regression | Agents C and D | visible bugs | ADOPT | 4.0 | **done** |
| 10 | Speaker races D4–D6, echo guard, turn-latency instrumentation | jarvis, Agent B | talking over the user; stuck states | ADOPT | 4.1 | P0 next |
| 11 | Avatar state resolver (priorities, dwell, real events) for both windows | clawd ideas | D7, flicker | ADAPT | 3.9 | P1 |
| 12 | Render FPS tiers, pixel ratio ≤1.5, no idle level traffic | BongoCat, jarvis face | battery/GPU | ADOPT | 3.8 | P1 |
| 13 | Recall gate plus bm25 floor; facts/episodes only in auto-recall | jarvis, OpenJarvis | noise and tokens | ADOPT | 3.8 | P1 |
| 14 | One memory write path with contradiction check | jarvis/nanobot ideas | duplicates, `user_edit` mislabel | ADAPT | 3.6 | P1 |
| 15 | Local per-turn traces → `bench_routing --from-traces`; importance regex fix | OpenJarvis traces | unmeasured routing | ADAPT | 3.6 | P1 |
| 16 | Dashboard and Focus view with real data only (Agent D acceptance criteria) | owner mockups | no stable "today" view | ADAPT | 3.7 | P1 (after 11–12) |
| 17 | UI a11y and contrast fixes, 420 px composer | Agent D | usability | ADOPT | 3.5 | P1 |
| 18 | Supply chain: hashed lockfile, SHA-pinned actions, LICENSE and notices | Agent C | release trust, licensing | ADOPT | 3.4 | P1 |
| 19 | Companion `MA_NOACTIVATE`, DPI re-report, placement | clawd, BongoCat | focus theft | ADOPT | 3.3 | P2 (needs the Dell) |
| 20 | Hold-to-dictate into the focused app | jarvis spec | missing | EXPERIMENT | 3.0 | P2 (ask the owner: it types into apps) |
| 21 | Dream consolidation that proposes edits | nanobot | none | EXPERIMENT | 2.8 | P2 |
| 22 | MCP runtime and tool search with permission classes | jarvis, nanobot | no MCP need yet | DEFER | 2.5 | — |
| 23 | Per-turn planner/evaluator; RL routing | jarvis, OpenJarvis | built for small models / stubs | REJECT | — | — |
| 24 | Live2D/WPF mascot replacement | desktop-pet topic | would erase Monkey's identity | REJECT | — | — |

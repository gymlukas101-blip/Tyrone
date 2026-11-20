# Monkey: flagship architecture decisions (2026-11-20)

Smallest clean architecture that meets the brief. It extends what exists (pywebview `UIBus` events, `TaskManager`, `PermissionGate`, `ApprovalGate`, memory stores). No new framework.

```
 voice (listener → STT) ─┐                       ┌─ memory (facts md + FTS5 history; one write path)
 text / UI buttons ──────┼─► brain (rules → Haiku │   recall gate → facts/episodes only
                         │   classifier, 4 s cap) ┤
                         │   agent loop (12 rounds│─ tools (local; MCP later) — classified read/write/outward
                         │   Claude, timeouts)    │      outward → ApprovalGate (email) / PermissionGate (computer)
                         │                        │      untrusted content taints the whole conversation
                         └─► long jobs ──────────►└─ TaskManager (durable: SQLite tasks + checkpoints + trace)
                                                       Computer: browser (own window or your Chrome via bridge),
                                                       Windows UIA, visual fallback — every action gated + verified
            events (UIBus → evaluate_js): voice state, tool/task/approval/verification, computer_event trace
                 ├─► avatar state resolver (priority + dwell) ─► main avatar + companion
                 ├─► banana cursor (only on real input events)
                 └─► UI: chat, cards → Dashboard / Focus (real data only), task HUD, history
            evaluation: pytest + fixtures (browser 20, Windows 13, hybrid), routing bench, memory eval, Windows CI
```

## Decisions

1. **Safety is enforced in code, at the point of execution.** This covers:
   - key presses, scored by their focused target;
   - navigation that could carry data out;
   - upload and file-path scope;
   - the email voice confirm;
   - conversation-wide taint;
   - no remote media rendered from model markdown.

   Prompts only explain the rules.
2. **There is one event contract.** Events are `UIBus` named events with JSON payloads. The computer-use trace (`computer_event`, see ADR 0002) already carries `task_id` and a monotonic `t`. Avatar, cursor, HUD and dashboard subscribe to these; nothing new is added.
3. **Long jobs never run in a chat turn.** The 12-round chat loop is not raised. Durable work goes through `TaskManager`, with its pause/resume, budgets, checkpoints and restart reconciliation.
4. **Memory stays markdown plus SQLite FTS5.** There is no second store. The fixes are:
   - forget purges history and episodes;
   - recall excludes sensitive content;
   - next: a recall gate and a single write path.
5. **Routing gets measurements before learning.** Local traces will feed offline policy comparison; nothing updates routing automatically until the comparison shows it helps.
6. **Licensing.** jarvis (custom non-commercial) and clawd-on-desk (AGPL) are ideas only. Playwright relay code is adapted under Apache-2.0, with attribution in the source. A LICENSE file and third-party notices are a P1 item.
7. **Module ownership:**

   | Module | Owns |
   |---|---|
   | `monkey/brain/` | reasoning and tools |
   | `monkey/memory/` | memory |
   | `monkey/audio/` | voice, and `devices.py` owns PortAudio lifetime |
   | `monkey/automation/` | long tasks and computer use |
   | `monkey/lifecycle.py` | process lifetime |
   | `monkey/logsafe.py` | log hygiene |
   | `ui/src/` | presentation only |

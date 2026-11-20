# ADR 0002: Hybrid computer use (browser + Windows apps + visual fallback)

**Status:** accepted; first vertical slice built on `feature/hybrid-computer-use`. Builds on [ADR 0001](0001-computer-agent.md).
**Evidence:** [research report](../research/COMPUTER-USE-RESEARCH.md) and [quality report](../research/COMPUTER-USE-QUALITY.md).

## Decision

1. **One internal interface, `monkey/automation/computer/`.** The planner and the task loop never see a third-party library's types. They get:
   - **Ops:** `observe`, `find`, `click`, `double_click`, `hover`, `type_text`, `press_key`, `scroll`, `drag`, `select_option`, `upload_file`, `choose_file`, `wait_for`, `verify`, `navigate`, `select_window`, `list_windows`.
   - **Targets** (`ElementRef`) identified by what they are, with the backend, session and an explicit coordinate space.
   - **Outcomes** (`accepted → executed → changed → verified`).
   - **Typed errors**, each mapped to bounded recovery strategies.
2. **Browser engine: Monkey's direct Playwright Python API.** It keeps the existing managed Edge profile, routing allowlist, cross-frame waits and banana cursor, and adds visible-text evidence, read-back and a failure taxonomy.
   - **Rejected as runtimes:** Playwright MCP/CLI (same engine, plus a Node process), browser-use 1.x (its model-written CDP code bypasses the permission gate and it opens a DevTools port), Stagehand (Chrome extension with a debug port; its cache is cloud-only), and Skyvern (AGPL plus pin conflicts).
3. **Windows engine: Monkey's own UIA backend** (pywinauto, in-process), rebuilt on agent-desktop's ideas:
   - identity refs, refusal of ambiguous matches;
   - background-first patterns, with physical input only by opt-in and an idle user;
   - hung-window and elevated-window checks, a tree budget;
   - owned dialogs (file pickers, message boxes) of an in-scope window are in scope.

   agent-desktop and Windows-MCP are benchmarked on the same fixtures on a real Windows runner and stay replaceable behind the `Driver` interface.

   **Switch rule:** move to agent-desktop (FFI DLL or CLI) if it beats Monkey's backend on success *and* doesn't disturb the user more, over the full fixture set.

   Windows-MCP is rejected as a runtime: Python ≥3.14, telemetry on by default, physical-only input, and PowerShell/Registry tools.
4. **Visual fallback: Claude's own computer toolset, used as a grounder.** Only `left_click` is enabled. Monkey reads the coordinate and acts itself after its own checks:
   - the point must be inside the capture;
   - something must be under the point (DOM/UIA);
   - that thing must match the description;
   - the gate then decides on that target.

   It runs only when the user allowed screenshots for the task. Images are downscaled to ≤1280×800 and the mapping back is explicit (`coords.ImageMap`). No second grounding model and no OmniParser.
5. **Router:** a capability-aware order for each step.
   1. The target's own backend.
   2. A native dialog goes to UIA.
   3. Semantic backends before pixels.
   4. Visual last, and only for pointer ops.

   A backend that fails the same op twice in a task is demoted, and every switch is traced.
6. **Orchestration:** the existing `TaskManager` stays the deterministic host (states, pause/stop, budgets, approvals, restart → PAUSED). `skill="general"` tasks run `computer.goal.GoalRunner`:
   - The loop is observe → (skill | verified-cache | planner) → ≤4 calls, stopping at the first failure → verify → checkpoint.
   - The planner is `ClaudeGoalPlanner`: compact context each round, page/app content wrapped as untrusted.
   - New states: PLANNING and RECOVERING.
7. **Safety additions** (all in the execution layer):
   - `upload` and `choose_file` into a browser-owned picker are HIGH and limited to the files the user listed.
   - `choose_file` in a native app is MEDIUM.
   - The idempotency ledger refuses the same non-idempotent op from the same screen.
   - Write-ahead intents surface "may or may not have happened" after a restart.
   - Physical input requires the task's `allow_physical` and an idle user.

## Consequences

- **Gained:** a general task can now move between Monkey's browser and an allowed Windows app (and that app's Save/Open dialog) in one durable task. The course flow (ADR 0001) is unchanged.
- **Not measured without a Claude key:** model-planning quality. The benchmark measures the execution layer with a scripted planner, and the quality report says so.
- **Not verified on the user's Dell:** multi-monitor, mixed DPI and 125/150% scaling. Those runs were on GitHub's windows-latest runner at 100%.

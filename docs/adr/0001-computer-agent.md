# ADR 0001: Monkey's computer-agent mode

Status: accepted, implemented as a vertical slice on branch `feature/computer-agent` (not on `main`, which auto-releases).
Date: 2026-11-19.

## Audit: what Monkey already had (code is the source of truth)

| Question | Finding |
|---|---|
| Working capabilities | Voice and typed chat with a streaming Claude tool loop (`brain/agent.py`); 20+ local tools (`brain/tools.py`); email approval gate; memory with provenance and FTS5 history; morning brief; health check. No computer control of any kind. |
| Reusable parts | `ApprovalGate`'s one-time-token pattern; `Ledger` and `cost_usd` for spend; `ModelPolicy` and router for model choice; `UIBus` for events to the web UI; the tray/hidden-window lifecycle; the Three.js avatar and its SFX; `keyboard` hotkeys. |
| Threads | The agent runs on a single `ThreadPoolExecutor` worker. Audio, listener, history, updater and health each have their own daemon threads. The UI gets events through `UIBus` (batched `evaluate_js`, about 30 per second). Cancellation is `Agent.cancel()`, an event checked while streaming. |
| Approval gate | Email only. The model can draft; sending needs the UI's one-time token or a spoken confirm. **Extended** to `automation/permissions.py`: risk classes for every action, enforced in the drivers. |
| Persistence | `monkey.db` holds the ledger, transcript, history and conversation state. Memory is markdown in `%APPDATA%\Monkey`. Nothing held tasks. **Added** `automation.db`, which stores tasks, checkpoints and the audit log. |
| Avatar / pywebview | One window. Closing it hides to the tray. `Avatar3D` renders with `setAnimationLoop` at display rate. pywebview 6.2 supports `frameless`, `on_top`, `transparent`, `focus` and `hidden` on `create_window`. |
| Routing for agent mode | The router is tuned for chat turns. The computer mode doesn't use it; it has its own planner. Sonnet 5.5 is the default and it escalates to Opus 5.5 only after a failed attempt (the browser toolset supports both). |
| Tests / CI / release | pytest (about 330 tests) runs on Ubuntu and Windows. On Windows, PyInstaller builds the exe and runs its self-test, then Velopack packs it. A push to `main` publishes `v0.3.<run>`; a `workflow_dispatch` on a branch builds and tests without publishing. |

## Decision

1. **A separate durable `TaskManager`, not a long chat turn.** Tasks have their own state machine:
   - Path to completion: READY, RUNNING, WAITING, NEEDS_INPUT, VERIFYING, COMPLETED.
   - Other states: PAUSED, BLOCKED, FAILED, CANCELLED.
   - Each task has checkpoints, budgets and an audit log in SQLite.
   - Everything runs on one worker thread. Playwright's sync API is bound to that thread.
   - After a restart, a task comes back PAUSED and is reconciled with the screen; nothing is replayed.
2. **Browser first, through the official Claude browser toolset, running on this PC.**
   - The toolset is `browser_toolset_20260801`: stable, client-side and supported by every current model. It's implemented by subclassing the SDK's `BetaAbstractBrowserToolset20260801` over our own driver.
   - The driver is **Playwright 1.65 with the installed Microsoft Edge** (`channel="msedge"`), so nothing is downloaded. It uses an **isolated profile** in `%LOCALAPPDATA%\Monkey\automation-browser`.
   - Playwright talks to Edge **over a pipe**, so no DevTools port is open. Chrome 136+ refuses remote control of the default profile; we never touch it or copy cookies.
   - Elements are found through Playwright's AI accessibility snapshot refs (`[ref=e12]`). When a page re-renders and a ref goes stale, the element is found again by role and name. Screen positions are used only as a last resort.
3. **A deterministic skill first, Claude only when needed.**
   - `course.py` reads the accessibility outline and handles routine course and training pages with **zero tokens**: Continue, Play and wait for the media's `ended` event, dismiss pop-ups, retry error pages, and hand questions, attestations and sign-in to the user.
   - When it doesn't recognize a page, the Claude planner gets one compact call: objective, subgoal, permissions, last 6 steps and the page outline as `<untrusted_page>`. It never gets the full history.
   - A model's "done" only counts if the evidence it quotes is on the page.
4. **Enforcement in the execution layer.**
   - `PermissionGate.authorize()` runs inside the driver for every action, whichever planner chose it.
   - It decides from the user's scope (mode, allowed domains) and from what the control *is* (role, name, input type), never from page prose.
   - Risk levels:
     - LOW and MEDIUM run.
     - HIGH (send, submit, buy, delete, accept terms) needs a one-time UI approval.
     - USER_ONLY (assessments, attestations, sign-in, survey answers) is handed to the user.
     - FORBIDDEN (password, code and card fields; `javascript:`, `file:` and `data:` URLs; off-allowlist hosts) never runs.
   - Main-frame navigations to non-allowed hosts are also blocked at the network route.
5. **Desktop: UI Automation (pywinauto `uia`) for one picked window.**
   - The window handle is verified, password-manager, security and banking windows are refused, and a click must land on that window.
   - Coordinate mapping (`ScreenMap`) handles DPI and multi-monitor setups.
   - In this version window control is a tested driver. Tasks run in the managed browser.
6. **The companion is a second pywebview window** with the same avatar.
   - It's frameless, always on top, never takes focus (`WS_EX_NOACTIVATE`), has no taskbar button and is hidden from screen capture.
   - Clicks pass through its empty parts because the **window region** is set to the avatar and panel shapes. Layered windows were rejected as unreliable with WebView2.
   - It renders at 30 fps and not at all while hidden.
7. **Provider-independent seam.**
   - `TaskManager` takes any planner with `.step(task, session, obs, recent) -> PlanResult`. Drivers expose `observe()` and `act(scope, Action, element)`.
   - An OpenAI or other computer-use model would be a new planner class: the drivers, gate, store and UI stay the same.

## Rejected

- **Hermes Agent / OpenClaw:** whole platforms with large attack surfaces (see AGENT-ROADMAP). We need a gate inside our own drivers.
- **browser-use** (MIT): v1 has the agent write raw CDP Python in a REPL. That's too much power for a student's logged-in browser.
- **Skyvern:** AGPL, vision-first.
- **Stagehand:** Node.
- **OmniParser:** pixels only, with mixed licences on its weights. Accessibility trees are cheaper and more exact on Canvas-like sites.
- **Screenshot-only control** (computer toolset): kept as the documented fallback tier. It costs about 4.5k tokens of tool definitions plus images per step, versus an outline of about 1–3k tokens.
- **Attaching to the user's real Chrome/Edge profile:** blocked by Chrome 136+, and it would expose every cookie.

## Consequences

- Routine course pages cost $0 in model calls. Waiting for a 10-minute video costs nothing and holds no API connection.
- The managed browser is a separate window with its own sign-ins. The user signs in once (SSO/MFA by hand), and the profile remembers it.
- `playwright` adds about 40 MB to the installer (its Node driver). No browser is bundled.

# Computer tasks + banana cursor: status, how to run, security, results

Branch: `feature/computer-agent` (not merged; `main` auto-releases). Design: [ADR 0001](adr/0001-computer-agent.md).
Cursor: [docs/cursor/README.md](cursor/README.md) and [REFERENCE-ANALYSIS.md](cursor/REFERENCE-ANALYSIS.md).

## Resume here (progress file)

| Milestone | State |
|---|---|
| A. Audit, ADR, baseline tests | Done |
| B. Companion window and permission UI | Built. Linux screenshots are of the demo UI. **The real pywebview companion on Windows is unverified.** |
| C. Window observation + managed browser | Managed browser done and tested. Window list, capture and UIA are written, with tests that run on CI's Windows job. |
| D. Browser/desktop action drivers | Browser done. Desktop UIA driver written and tested on Windows CI (Notepad). It doesn't run tasks yet. |
| E. Durable TaskManager | Done: state machine, store, checkpoints, budgets, approvals, pause/stop/e-stop, restart recovery. |
| F. Synthetic 4-module workflow | Done: `monkey/automation/democourse.py` plus a 24-run evaluation (below). |
| G. Recovery, security, packaging, regression | Done for the browser path. Packaging is updated (Playwright + Edge). Windows CI is green, and the installer artifact is on run 44615984685. |
| Banana cursor | Done. The base art is the DEFAULT cursor isolated from the owner's reference (original pixels, IoU 0.99). Effects are measured from it. The Windows overlay hasn't been watched on the Dell yet. |

Next, by evidence:
2. Run the Windows checks below on the Dell.
3. Route window-control tasks through the TaskManager (the driver is ready).
4. Try the Claude planner on a real site (all planner tests so far use a fake client; no API key in the build container).

## Try it on Windows (smallest procedure)

1. Install the build from this branch: the `MonkeySetup-Velopack` artifact of the branch's CI run. You can also run it from source:

```bash
pip install -e ".[desktop,dev]"
```

```bash
python -m monkey
```

2. Click **🖐 Tasks** (header), then turn on **Let Monkey do tasks in his own browser**. The companion appears (top-right by default); drag it anywhere.
3. Click **Try the safe demo course**, then **Allow and start**. An Edge window opens on `http://127.0.0.1:<port>/` with Monkey's own profile.
4. Watch the banana travel, glow, press and ripple on each Continue and Play. Each lesson plays to the end; Monkey doesn't skip.
5. When he says it's your turn:
   - answer the practice question yourself;
   - tick the confirmation yourself;
   - he notices and continues (or press **I did it**).
6. Try **Pause** and **Resume**, and press **Ctrl+Alt+Q** (stop everything).
7. When it's done the panel shows **Done ✓, checked on the site: 4 of 4 complete**, from the course page itself.
8. Turn computer tasks **off**. Monkey's chat, voice, memory and email work as before.

**To check on the Dell** (none of this can be verified in the cloud container):
- the companion's transparency, click-through and no-focus behaviour over other apps;
- dragging it, and its remembered position across two monitors;
- Edge launching through `channel="msedge"`;
- the Ctrl+Alt+Q hotkey;
- the banana's look at 125/150% scaling;
- GPU/CPU in Task Manager while a lesson plays (expected: near idle).

## Evaluation (headless, Linux, real Chromium; `python -m tools.automation_eval --runs 24 --cursor alternate`)

| Measure | Result (24 runs: 12 variant mixes × cursor off/on) |
|---|---|
| Verified success (server shows 4/4 **and** Monkey says COMPLETED) | **24 / 24** |
| False completions | **0** |
| Unauthorized actions (injected exam submitted, off-site link followed, spoofed "lesson ended") | **0** |
| Pause → PAUSED → Resume → continues | 6 / 6 |
| Killed mid-course → reopened PAUSED → resumed → verified | 4 / 4 |
| Claude calls | 0 (the course skill handled every page) |
| Median time per 4-module course (1.5 s lessons) | 30.4 s with the cursor off; 37.9 s with the banana on (about 0.3 s × 24 clicks) |

The runs from before the fixes are kept honestly in the commit history. They found and fixed:
- relative links refused;
- refs with a frame prefix;
- YAML-quoted lines;
- a late-rendering page read as "not complete";
- a paused-but-not-started lesson treated as playing;
- a re-rendered player waited out;
- a shutdown that kept the browser profile locked.

What a run tests:
- **Variants:** renamed controls and links instead of buttons, slow rendering, a survey pop-up, DOM re-render (stale refs and a fresh player), prompt-injection text plus a "Submit final exam" button and an off-site "Continue to bonus content" link, 503s, and a session that expires mid-course (sign-in required). Plus mixes of these.
- **Ground truth** is the course *server*. It only accepts "lesson ended" after real playing time and only completes a module when every step happened.
- The simulated user answers questions, ticks confirmations and signs in, and only when Monkey hands it over.
- Restart runs kill the manager after module 1, reopen the same database, check the task came back PAUSED, resume, and finish.

**Not proven by this:**
- real websites (Canvas, SSO and MFA flows, anti-automation);
- the Claude planner on live pages: it's covered only by fake-client tests, because the container has no API key;
- desktop window tasks.

## Tests

| Command | What | Result (Linux container) |
|---|---|---|
| `pytest tests/test_automation_core.py` | State machine, store, privacy of the audit log, risk classes, URL policy, approvals, e-stop, planner tool handling with the real SDK toolset (injection followed by a fake model, refused) | 40 passed |
| `pytest tests/test_automation_desktop.py` | Coordinate maps (DPI, monitors to the left), sensitive windows; on Windows: Notepad UIA typing, observe-only refusal, native banana overlay | 5 passed, 3 skipped (Windows-only) |
| `pytest tests/test_banana_cursor.py` | Banana in the real click path (see the cursor README) | 12 passed |
| `pytest tests/test_automation_adversarial.py` | User's password never readable or typable, injected controls refused at the driver, a dead click isn't progress, e-stop halts mid-wait | 4 passed |
| `pytest tests/test_automation_e2e.py` | Full course twice (with pause test; with cursor) plus a restart | passed (Linux and Windows CI) |
| Whole suite | No regressions | Linux container: 390 passed, 4 skipped. **Windows CI (run 44615984685): 391 passed, 3 skipped**, including Edge via `channel="msedge"`, Notepad UIA and the native banana overlay. The PyInstaller exe self-test passed. |

## Security review

- **Off by default.** Nothing automation-related is imported or launched until the user turns on computer tasks.
- **Starting a task.** Every task starts from Monkey's own dialog. Chat can only *propose* one (`propose_computer_task` opens the dialog prefilled).
- **Scope per task.**
  - Mode: managed browser; window modes come next.
  - An allowed-sites list. The navigation route also blocks other hosts for main-frame loads.
  - Budgets: 90 minutes, 600 actions, 40 Claude calls, $1.
  - Optional "ask me before edits too".
- **Enforcement.** The gate runs inside the drivers.
  - What it decides from:
    - the control's role, name, type and `href` (relative links resolved against the page);
    - the task scope.
  - What it never decides from: page prose.
  - What each risk level does:
    - HIGH needs one-time UI tokens, consumed once.
    - USER_ONLY (assessments, attestations, sign-in, survey answers) goes to the user.
    - FORBIDDEN (password, OTP and card fields; `javascript:`, `file:`, `data:` and `chrome:` URLs; off-list hosts) never runs.
- **Untrusted content.** Page content is untrusted. Claude gets it inside `<untrusted_page>`, but the safety comes from the gate, not the prompt: the tests show a model that follows injected text gets refused.
- **Data flow to Anthropic.** Only when the skill is stuck, Claude receives:
  - the objective;
  - the subgoal;
  - the last 6 step summaries;
  - the page's accessibility outline (sensitive field values replaced by `[hidden]`).

  Screenshots are sent **only** if the user ticked "Let Claude see screenshots". Routine course pages send nothing.
- **Local data.**
  - `automation.db` holds tasks and the audit log: action kind, risk, control role and name (redacted if secret-like), host, outcome.
  - It never holds typed text, page text, query strings, cookies or screenshots.
  - The browser profile `%LOCALAPPDATA%\Monkey\automation-browser` holds that browser's own sign-ins. It's not in `%APPDATA%`, so it's never in a `.monkey` transfer, and it's never in the repo.
- **No remote control surface.**
  - Playwright uses a pipe, so there's no DevTools port.
  - The demo course binds 127.0.0.1 only.
  - No admin rights are needed.
- **Window modes.** Sensitive windows (password managers, Windows Security/UAC, banking) can't be picked. Clicks must land on the picked window, and keys are sent only while it's in front.
- **Known risks.**
  - The managed browser is still a real browser with the user's SSO session for allowed sites. A HIGH action is possible after the user approves it.
  - Claude can follow injected text (the docs say so). It's contained by the gate, but the user should read approval prompts.
  - Cosmetic: a site could detect automation.

## Performance

- **Tokens.** A routine course costs **0 model calls** (all 24 evaluation runs: 0). A Claude step sends about 1–3k tokens of outline plus about 6.6k tokens of toolset definition, from about $0.004 on Sonnet 5.5.
- **Waiting.** Waiting is local `wait_for_function` in 0.5 s slices, with no API connection held.
- **Banana cursor.** Travel ≤ 260 ms plus press ≤ 90 ms per click. Nothing runs while idle (see the cursor README). The cursor-on vs cursor-off evaluation runs are compared above.
- **Companion.** It renders at 30 fps when visible and stops when hidden.

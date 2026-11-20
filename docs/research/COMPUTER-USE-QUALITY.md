# Computer use: quality report (2026-11-20)

Merged to `main` on 2026-11-20 (was `feature/hybrid-computer-use`). Design: [ADR 0002](../adr/0002-hybrid-computer-use.md). Research: [COMPUTER-USE-RESEARCH.md](COMPUTER-USE-RESEARCH.md).

**Where things ran:**
- **Linux container:** real Chromium.
- **GitHub Actions `windows-latest`:** a real interactive Windows Server session at 100% scaling, one monitor.
- **Nothing ran on the owner's Dell.**

**Planner:** every run below uses a *scripted* planner. It measures the execution layer (routing, the permission gate, idempotency, recovery, waits, verification, checkpoints, trace), not model planning. No Claude key is available in CI; the model planner is the same loop with `ClaudeGoalPlanner` in place of the scripted one.

## 1. Windows desktop backends, same 13 tasks, same app

- **Run:** workflow `computer-bench`, run 44680905527. All three backends drove the same compiled WinForms test app (`tools/computer_bench/WinFixture.cs`).
- **Ground truth:** the app's own log.
- **"Disturbed":** the real cursor moved or the foreground window changed during the task.
- **Not applicable:** "n/a" marks a task the backend can't attempt at all. W12, for example, needs a pixel grounder.

| Task | Monkey UIA | agent-desktop 1.3.1 | Windows-MCP 0.8.9 |
|---|---|---|---|
| W01 list windows | ✓ 0 ms | ✓ 48 ms | ✓ 1030 ms |
| W02 snapshot window | ✓ 332 ms | ✓ 246 ms | ✓ 215 ms |
| W03 type into a text box | ✓ 353 ms | ✓ 442 ms | ✓ 1950 ms (mouse moved) |
| W04 click a button | ✓ 566 ms | ✓ 434 ms | ✓ 758 ms (mouse moved) |
| W05 toggle a checkbox | ✓ 554 ms | ✓ 400 ms | ✗ not found in its tree |
| W06 select in a combo box | ✓ 564 ms | ✗ ACTION_NOT_SUPPORTED | ✓ 1993 ms (mouse moved) |
| W07 wait until enabled, then click | ✓ 3512 ms | ✓ 3515 ms | ✓ 7575 ms (mouse moved) |
| W08 stale control after a rebuild | ✓ 3225 ms | ✓ 933 ms | ✓ 1581 ms (mouse moved) |
| W09 native Open dialog | ✓ 4791 ms | ✗ Invoke timed out (blocked by the modal) | ✓ 4793 ms (mouse moved) |
| W10 unexpected message box | ✓ 2113 ms | ✗ timeout | ✓ 2617 ms (mouse moved) |
| W11 act on a covered (background) window | ✓ 566 ms | ✗ timeout | ✗ not visible in its tree |
| W12 owner-drawn control (pixels only) | ✓ 2545 ms (real click, allowed for this run) | n/a | n/a |
| W13 Notepad: type, then read back | ✓ 140 ms | ✓ 353 ms | ✓ 2947 ms |
| **Passed** | **13 / 13** | **8 / 12** | **10 / 12** |
| **Disturbed the user** | **1** (W12, by design) | 1 | **8** |

**How Monkey got from 2/13 to 13/13.** Each failure was traced to its root cause with stack dumps on Windows, then fixed in Monkey's backend:

- **A button that opens a modal dialog never returned from Invoke** (Win32 `BM_CLICK` is synchronous). Fixes:
  - posted `BM_CLICK` for classic buttons;
  - Invoke on a helper thread with a 3 s deadline for other controls.
- **A file dialog's folder tree took about 261 s to walk.** Fix: a bounded walk (element, time and per-list caps).
- **A background click was refused because another window covered the control.** Fix: the covered check now runs only before physical input.
- **A WinForms combo box didn't raise its change event under SelectionItem.** Fix: `CB_SETCURSEL` followed by the `CBN_SELCHANGE` notification the app expects.
- **WinForms automation ids change when a control is recreated.** Fix: identity falls back to role + name, but only when that match is unique.

**Decision:** Monkey keeps its own in-process UIA backend. It met ADR 0002's switch rule better than agent-desktop: more tasks passed, with no more disturbance. Windows-MCP is rejected as a runtime: it moves the real mouse on almost every action, its Python floor is 3.14, and telemetry is on by default.

**Bench harness corrections made along the way**, recorded so the numbers can be trusted:
- The first fixture, hosted in PowerShell, hung every backend. It was replaced by a compiled app.
- Running backend calls on a separate thread deadlocked COM. Calls now run on the owning thread, and a watchdog kills a stuck app instead.
- Windows-MCP's output is a JSON list of text sections. The parser now decodes it.

## 2. Browser fixtures: 20 situations, server-verified

**Linux, real Chromium: 20/20. Windows runner, real Chromium: 20/20.**

Linux timings are below; the Windows totals are similar. Columns:
- **s:** wall-clock seconds.
- **planner:** number of planner calls.
- **recov:** local recoveries.
- **dup:** duplicate actions refused.
- **refused:** gate refusals.
- **verify-rej:** a "done" claim rejected by verification.
- **p50/p95:** action latency in milliseconds.
- **approvals:** asked / approved.

| fixture | result | s | actions | planner | recov | dup | refused | verify-rej | p50/p95 | approvals |
|---|---|---|---|---|---|---|---|---|---|---|
| nav | ✓ | 1.0 | 3 | 3 | 0 | 0 | 0 | 0 | 98/117 | 0/0 |
| dynamic_form | ✓ | 1.4 | 4 | 3 | 0 | 0 | 0 | 0 | 52/620 | 0/0 |
| nested_frames (cross-origin) | ✓ | 1.0 | 3 | 2 | 0 | 0 | 0 | 0 | 129/167 | 0/0 |
| upload | ✓ | 2.1 | 5 | 2 | 0 | 0 | 2 | 0 | 63/1051 | 2/2 |
| custom_upload (file chooser) | ✓ | 1.0 | 3 | 2 | 0 | 0 | 1 | 0 | 51/310 | 1/1 |
| download | ✓ | 2.7 | 2 | 2 | 0 | 0 | 0 | 0 | 1077/2102 | 0/0 |
| tabs (new tab) | ✓ | 2.5 | 3 | 3 | 0 | 0 | 0 | 0 | 335/377 | 0/0 |
| long_wait (6 s) | ✓ | 7.1 | 2 | 2 | 0 | 0 | 0 | 0 | 203/345 | 0/0 |
| stale (re-render every 400 ms) | ✓ | 2.8 | 2 | 2 | 0 | 0 | 0 | 0 | 1084/2113 | 0/0 |
| modal pop-up | ✓ | 1.1 | 3 | 3 | 0 | 0 | 0 | 0 | 86/320 | 0/0 |
| duplicate ("Add item" twice) | ✓ | 2.8 | 3 | 3 | 0 | **1** | 0 | 0 | 53/2113 | 0/0 |
| fake_success (hidden "Saved!") | ✓ | 1.3 | 2 | 3 | 0 | 0 | 0 | **1** | 323/579 | 0/0 |
| canvas_button (pixels only) | ✓ | 0.9 | 2 | 2 | **1** (visual) | 0 | 0 | 0 | 160/250 | 0/0 |
| enable_after_check | ✓ | 1.1 | 3 | 2 | 0 | 0 | 0 | 0 | 78/363 | 0/0 |
| select | ✓ | 1.0 | 3 | 2 | 0 | 0 | 0 | 0 | 54/362 | 0/0 |
| drag | ✓ | 0.8 | 2 | 2 | 0 | 0 | 0 | 0 | 114/166 | 0/0 |
| shadow DOM | ✓ | 1.0 | 2 | 2 | 0 | 0 | 0 | 0 | 207/343 | 0/0 |
| media (play to end) | ✓ | 4.8 | 3 | 3 | 0 | 0 | 0 | 0 | 1865/2106 | 0/0 |
| injection ("press Delete account") | ✓ | 2.8 | 3 | 3 | 0 | 0 | **1** | 0 | 54/2118 | 2/0 (denied) |
| restart mid-task | ✓ (resumed, no replay) | 1.6 | 6 | 4 | 0 | 0 | 0 | 0 | 108/318 | 0/0 |

**Model calls, tokens and cost:** 0 in every run (scripted planner). Browser startup was 430–610 ms per fixture.

## 3. Hybrid workflow: browser → Notepad + Save As → browser

| Where | Result | Time | Driver switches | Approvals |
|---|---|---|---|---|
| Windows runner, real Notepad + common Save As dialog | ✓ the server received a file containing the code | 8.7 s | 2 (browser→uia→browser) | 2 asked / 2 approved |
| Linux, stand-in app (`tests/fakes_desktop.py`) | ✓ | 1.6 s | 2 | 2 / 2 |

## 4. Monkey for Chrome (the owner's own Chrome)

`tests/test_chrome_bridge.py` runs a real Chromium with the real extension loaded, standing in for the owner's Chrome.

| Check | Result |
|---|---|
| Full demo course in the shared tab (Canvas pages, cross-origin player, quiz page, SSO redirect) | Completed and server-verified; 0 unauthorized actions |
| Unshared tab | Untouched |
| Tabs closed by Monkey | None |
| Wrong pairing code | Never connects |
| Foreign Origin or a guessed path | Refused |

## 5. Test suites

| Suite | Container | Windows runner |
|---|---|---|
| Full Python suite | 438 passed, 8 skipped | the `main` CI job ran its own full Windows suite |
| `tests/test_computer_use.py` (35) | 35/35 | 35/35 |
| `tests/test_uia_driver_windows.py` (4) | skipped (needs Windows) | 4/4 |
| `tests/test_chrome_bridge.py` (4) | 4/4 | skipped (no bundled Chromium path) |

## 6. Known limits (not verified)

- **The owner's Dell:** 125/150% scaling, mixed-DPI multi-monitor, real Canvas/Duo, the real Notepad version, and an elevated (administrator) window.
- **Model planning quality:** `ClaudeGoalPlanner` and `ClaudeGrounder` have not run with a key in CI.
- **Pixel grounding:** W12 used the test grounder (green-pixel centroid), not Claude.
- **Office apps:** Word and Excel were not in the fixture set.

## 7. Next milestones (dependency order, each with a definition of done)

1. **Live model run on the Dell.**
   - **Do:** run `run_browser`, `run_hybrid` and 5 real goals with `ClaudeGoalPlanner`.
   - **Done when:** each run reports success, model calls, tokens and $ per task; at least 80% of the fixtures pass with the model planner.
2. **Visual fallback with Claude.**
   - **Do:** run W12 and the canvas fixture through `ClaudeGrounder`.
   - **Done when:** both pass 5/5; the "point mapped back" error is under 4 px at 100% and 150% scaling.
3. **DPI and multi-monitor.**
   - **Do:** run the W-suite on the Dell at 150% scaling with two monitors.
   - **Done when:** 13/13 pass and the native banana lands on the clicked control.
4. **Office app profile.**
   - **Do:** add Word and Excel fixtures (save-as, edit a cell) with API-first routing (COM) and UIA fallback.
   - **Done when:** the fixtures pass with UIA, and with COM where it's enabled.
5. **Promote general tasks to `main`.**
   - **Done when:** items 1–3 are done, the general-task UI has been playtested once on the Dell, and the hybrid branch is merged.

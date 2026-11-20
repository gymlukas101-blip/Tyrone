# Computer tasks + banana cursor: status, how to run, security, results

Shipped on `main` (merged 2026-11-20). Design: [ADR 0001](adr/0001-computer-agent.md).
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

1. The installed app auto-updates to the release that has this (Settings → **Check now** to fetch it right away). You can also run it from source:

```bash
pip install -e ".[desktop,dev]"
```

```bash
python -m monkey
```

2. Click **🖐 Tasks** (header), then turn on **Let Monkey do tasks in his own browser**. The companion appears (top-right by default); drag it anywhere.
3. Click **Try the safe demo course**, then **Allow and start**. A Chrome window (Edge if Chrome isn't installed) opens on `http://127.0.0.1:<port>/` with Monkey's own profile.
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
- Chrome launching through `channel="chrome"` (Edge as the fallback);
- the Ctrl+Alt+Q hotkey;
- the banana's look at 125/150% scaling;
- GPU/CPU in Task Manager while a lesson plays (expected: near idle).

## Real modules: what's handled, and your first run

Researched from the Canvas, Kaltura, Storyline and Playwright source code (exact labels and hosts), then rebuilt as test
fixtures, so each is exercised by the evaluation.

| Real-world shape | How Monkey handles it | Test fixture |
|---|---|---|
| Canvas module items: link "Next Module Item" (text "Next ›"), button "Mark as done" → "Done", modules page with "Must view…" / "N of N Required Items" | Clicks Next and Mark as done. On the modules page, opens the first item that still says "Must view / Must mark done". Verifies completion when every module reads "N of N Required Items". | `canvas` |
| Lesson video inside an embedded **cross-origin** player (Kaltura `cdnapisec.kaltura.com`, Panopto, YouTube, Vimeo, SCORM frames) | The accessibility snapshot reaches into iframes, and clicks use the frame refs (`f1e4`). Waiting for the lesson to end checks `<video>` state in **every frame**, including shadow DOM, locally every 0.5 s. | `embed` |
| Storyline / Rise | Labels "Next (Ctrl+Alt+Period)", "NEXT LESSON", "START COURSE", "CONTINUE". Disabled means `aria-disabled` / `disabled`. Rise's `div[role=radio]` counts as a question. | covered by labels |
| Quizzes: "Take the Quiz" / "START QUIZ" (may start a timer), several questions on one page, "Submit Quiz", Canvas's `confirm()` dialogs | Asks you to say "start". Asks each question in turn (grouped by container). When all are answered, asks you to say "submit". Native dialogs are always dismissed (cancelled), never accepted. | `quizpage` |
| School sign-in: Canvas → `login.wisc.edu` → Duo (`api-*.duosecurity.com`) / Microsoft | You sign in yourself, once; the profile remembers it (Duo's own "remember me" lasts 7 days). Any site outside the allowed list makes Monkey ask "Allow X?" first, including sites reached by **redirect**. On a page whose site isn't allowed, nothing is clicked. | `sso` |
| Locked items ("hasn't been unlocked yet", "Lessons must be completed in order") | Handed to you. | — |
| End of the course with no Next button | Goes back to your start page and checks completion there. If unsure, asks you instead of claiming "done". | — |

### Your first real run (on the Dell)

1. 🖐 Tasks → turn it on.
2. Fill in:
   - **What to do:** e.g. "Finish the modules in this course".
   - **Start page:** the course's **Modules** page, e.g. `https://canvas.wisc.edu/courses/12345/modules`. That's where completion is checked.
   - Keep **"Also allow the sign-in and video sites courses use"** ticked. It adds `wisc.edu` (your NetID login), Duo, Microsoft, `instructure.com`, Kaltura, Panopto, YouTube and Vimeo.
3. Press **Allow and start**. Chrome opens with Monkey's own profile (its own window, not your normal Chrome profile). Sign in with NetID and Duo **yourself** the first time (tick "Yes, this is my device").
4. Watch the first module. When he asks, answer questions by letter, say "I confirm", "start" or "submit", or "allow" for a new site.
5. If he says "I'm not sure what to do on this page", do that one step yourself. He notices and carries on, or asks Claude (a few cents).
6. Budget per task: 4 hours, 600 actions, 40 Claude calls, $1. Pause and **Ctrl+Alt+Q** work at any time.

## Answering questions: "you say it, he clicks it"

1. When a question appears, Monkey **reads it and the options aloud**, then gives **his pick and one sentence why**. The suggestion comes from Haiku 5.5, about $0.001 per question; the question text is marked as untrusted page data.
2. A golden **"Monkey's pick" tag with the banana** appears beside that option on the page. The task panel and the companion show letter buttons, with the same badge on the pick.
3. You **say, type or click** a letter ("B", "bee", "option b" and "2" all work). Monkey clicks that option and presses Check answer.
   - If the site says it's wrong, he tells you and asks again.
   - If it's right, he moves on.
4. At a confirmation he reads the **exact statement** ("I confirm I reviewed module 2 myself"). Saying or typing **"I confirm"** ticks that box for the current module only. He then clicks **Complete module automatically**. That's a medium-risk action and runs without asking, as long as "Ask me before he types into or saves anything" is unticked, which is the default.
5. How it's enforced:
   - Your reply creates a **one-time grant for exactly that click** (that option, Check answer, that confirmation box).
   - Only Monkey's own reply handler can create one, from your voice, chat or a button in Monkey's window.
   - Page content can't create one.
   - A different option isn't covered by the grant.
   - Passwords and codes can never be granted.
   - The audit log marks these clicks "your choice".

You can still answer in the browser yourself; Monkey notices and continues.

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
    - USER_ONLY (questions, attestations, sign-in, survey answers) goes to the user. Monkey clicks one only with that user's explicit one-time choice ("B", "I confirm"); sign-in is always done by the user.
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

## General tasks: browser + Windows apps (hybrid computer use, on `main` since 2026-11-20)

1. In 🖐 **Tasks**, pick **"General task: his browser + apps you pick"**.
2. Fill in:
   - **What to do:** the objective.
   - **Start page and sites:** optional.
   - **Apps he may use:** click the `+ notepad.exe`-style buttons for open apps.
   - **Files:** the files he may open, save or upload.
   - **Real mouse and keyboard:** tick "may use my real mouse and keyboard" only if an app needs it.
3. Monkey plans with Claude a few steps at a time and works between the browser and those apps, including their Open/Save dialogs.
4. The task panel shows a live feed: which app he's in, each step, ✓ when the result was read back, ✗ and why.
5. **Rules:**
   - Uploads and sending files always ask first.
   - Only listed files can be picked.
   - He refuses to repeat an action that may already have happened.
   - "Done" only counts when the proof is on screen.
6. **Design and evidence:** [ADR 0002](adr/0002-hybrid-computer-use.md), [quality report](research/COMPUTER-USE-QUALITY.md).
## Working in your own Chrome (Monkey for Chrome extension)

Chrome (136+) won't let outside programs remote-control your everyday profile. So Monkey ships a small extension instead
(`extension/chrome/`, also inside the installed app). Monkey then works in **your real tabs, signed in as you**.

1. 🖐 Tasks → **Where Monkey works** → **My Chrome: the tabs I share**.
2. In Chrome:
   1. Open `chrome://extensions` and turn on **Developer mode**.
   2. Click **Load unpacked** and pick the folder from **Open folder** (`%LOCALAPPDATA%\Monkey\chrome-extension`, which updates never replace).
3. Click the 🍌 icon in Chrome's toolbar, paste the pairing code from Monkey, then press **Pair**.
4. On your Canvas page, click the 🍌 icon → **Let Monkey use this tab**, then start the task in Monkey.

**What he can reach:**
- Only the tabs you share, plus pop-ups they open (a Duo sign-in, a module window).
- Your other tabs are invisible to him.
- He never closes your browser or your tabs; he can only close tabs he opened.
- While he's connected, Chrome shows "Monkey for Chrome started debugging this browser". Press **Cancel** on that bar to cut him off instantly.

**Security:**
- The bridge listens only on 127.0.0.1.
- The extension and Monkey prove they hold the same pairing code in both directions (HMAC challenge-response) before anything flows. Another program can't pose as Monkey, and a web page can't connect.
- The extension itself refuses cookie reads and browser-wide changes.
- Every click still goes through Monkey's permission gate.
- **New code** in Monkey revokes the old pairing.

**Tested in the container** (`tests/test_chrome_bridge.py`): a real Chromium with the real extension loaded played your Chrome.
- The full demo course (Canvas-style pages, an embedded cross-origin player, the quiz page, an SSO redirect) completed and was verified by the course's own server.
- No unauthorized actions; the unshared tab was untouched; no tab was closed.
- A wrong pairing code and foreign origins were refused.

**Not yet tried:** your Chrome on the Dell.

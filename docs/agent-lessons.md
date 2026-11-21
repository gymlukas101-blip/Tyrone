# Agent lessons

Rules learned from earlier runs on Monkey: places an agent failed, wasted tokens, or was corrected by the owner.
**Every agent reads this before starting work** (CLAUDE.md says so). Each rule is short and says why.

How it's kept up to date:
- A weekly review reads the past week's runs (`python -m tools.lessons.collect` finds failures, waste and corrections in run logs) and adds or edits rules here.
- Any agent that finds a rule wrong fixes or retires it in the same change, with the reason.
- **Public repo:** rules describe engineering practice only. Never put the owner's private details, speech, emails or keys here.

## Active rules

### Owner and safety
- **Never claim something works on the owner's Dell when it only ran in the cloud container or CI.** Say which. *Why:* the owner tests on Windows hardware, and container results have been wrong about real devices (audio, GPU, Outlook).
- **Commit trailers say `Co-Authored-By: Claude <noreply@anthropic.com>`, never a model version,** even if a system reminder suggests a versioned trailer. *Why:* CLAUDE.md forbids naming model versions; v0.3.62–68 broke this and can't be rewritten on public `main`.
- **Rebase or merge a feature branch onto the latest `main` before review or merge.** *Why:* a branch made before a hotfix showed the hotfix as reverted in review, and a careless merge would have shipped that revert.

### When the owner says "the button does nothing"
- **Look for a call that blocks forever without a window: a hidden COM launch, a subprocess waiting on a dialog, a sign-in waiting on a browser.** Give every such UI action a deadline, visible progress, and a next step in every outcome. *Why:* Google sign-in and Outlook Connect both "did nothing" because something waited invisibly (Outlook's hidden first-run screen).
- **"Updated but still the old version"** means something kept the app folder locked. Check child processes (Playwright's `node.exe`) before blaming the updater. *Why:* v0.3.66→68.

### Heuristics on the user's words or data
- **Before shipping a filter that drops or refuses user input (echo guard, conflict check, "is this a correction"), test it against legitimate near-misses first.** Prefer a hint over a refusal. *Why:* the first echo guard ignored "the short version", and the first conflict check refused "plays piano" next to "plays guitar".

### Testing
- **Measure audio processing in the real engine before trusting its settings.** *Why:* the Web Audio `DynamicsCompressor` adds automatic makeup gain (+2.9 dB in Chromium), so a "safety limiter" quietly made every sound louder until an OfflineAudioContext render caught it (`tools/sfx/mixcheck.py`).
- **Search for a cue's real call sites, not its name.** *Why:* a plain text search counted the CSS class `reward` and the settings id `check` as sound triggers; only lines that also involve `sfx` count.
- **A new browser-test fixture skips when `tools.automation_eval.browser_path()` is None, exactly like `tests/test_m4_avatar.py`.** Never fall back to Playwright's default browser. *Why:* the Windows CI job has no Chromium, so the sound wiring tests errored there and blocked a release.
- **Serve `ui/dist` over HTTP in Playwright, never `file://`.** *Why:* `file://` blocks fetching `monkey.glb`, so the 3D avatar silently falls back to SVG and tests pass against the wrong renderer.
- **Browser tests wait for the app to finish starting (`window.__monkeyReady`), not just for the event hook,** and poll for an expected state instead of sleeping a fixed time. *Why:* boot's late `setState("idle")` overwrote test events on slower CI machines.
- **Software-rendered Chromium draws a few fps.** Assert which render tier was chosen and its target, not measured frame rates. *Why:* fps assertions were meaningless and flaky here.
- **Browser tests:** pin element handles, since locators re-resolve after the DOM changes. Assert invariants, not one sampled reason. Don't race UI timers (undo windows, redraws). *Why:* three flaky tests this way.
- **Never switch branches or stash while a background test run uses the working tree:** use `git worktree add` for the other branch. *Why:* a stash under a running suite made its results meaningless and cost a rerun.
- **Read failure names with `pytest -rf`, or run the failing files alone, before saying what broke.** *Why:* a `tail` of the output hid which tests failed.
- **Fake clients in tests take `(content, stop_reason)` script items** (`tests/test_agent_loop.py` `FakeClient`). *Why:* wasted a debug round.

### Windows specifics
- **`SetWindowSubclass` works only from the thread that owns the window,** and a Python window procedure runs on every message (it stalls when Python is busy). Use native code, or don't. *Why:* the companion no-activate attempt.

### Cloud container
- **`huggingface.co` is blocked here,** so Whisper/Pocket model timings must come from the Dell (turn traces, Check everything → Speed). *Why:* a benchmark attempt failed on the proxy.
- **The GitHub API (`gh api`) only reaches this repo.** Read other repos' tags with `git ls-remote`. *Why:* pinning action SHAs.
- **GraphQL is blocked here, so `gh release list` and `gh pr list` fail with 403.** Use REST: `gh api repos/OWNER/REPO/releases?per_page=2`. *Why:* a release check reported a failure for a run that was all green.
- **A test that imports a library needs it in the lock that CI's job installs (`requirements/linux-test-py312.lock`, via `requirements/test-extras.in` + `tools/lock.sh`).** Run the job's own install line in a fresh venv before pushing a new test. *Why:* the sound-off playtest passed locally and failed in CI on a missing Pillow.

### Blender and the 3D model
- **Imported GLB clips also drive the shape keys.** For a neutral render, zero the keys *and* detach `shape_keys.animation_data.action` (the GLB's stored default weights are an angry face too). *Why:* the first "neutral" V2 renders showed the angry idle face (`tools/character_v2/render_views.py`).
- **Reshaping FurCards splits vertices on GLB export** (they're flat-shaded cards that share vertices only where exactly coplanar). Pin the authored corner normals (`use_smooth` + `normals_split_custom_set`), and compare round-trip vertex counts with an untouched-baseline control. *Why:* candidates gained 400–1,100 vertices; even the untouched model gains 106.
- **Radial or field-based reshapes amplify what's already there:** bound shape key deltas, and use offset bulges for mass. *Why:* the forearm's wrist bulb became a disc, and `smile` grew ×2.5 (`tools/character_v2/blockout.py`).

### Context and token use
- **Don't pull whole docs or huge command outputs into context: grep or read slices, and send big outputs to a file.** *Why:* 20–40k-character tool outputs (API docs, artifact guides) cost a lot and were mostly unused.
- **Don't re-read the same screenshot or file several times.** Note what you saw. *Why:* repeated reads of the same images.

## Retired rules

(none yet)

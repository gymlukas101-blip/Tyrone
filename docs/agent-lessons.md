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
- **Blender colour-threshold tests (magenta leak tests, flat debug colours) must render with `view_transform = "Standard"` and AA off, and should first check that the background pixel is the colour they expect.** *Why:* the V2 blends use AgX, which turns a magenta background into (201, 116, 201), so `eye_poses.py`'s leak test and the first M1 mouth leak test could never fail.
- **Before a leak test's 0 counts as evidence, make it fail once in a throwaway run: hide the part that seals (`eye_poses.py --hide V2_EyeSock_L`).** Cull back faces in the count, because when the head is closed behind the opening, a missing part shows the skull interior, not background. *Why:* after the AgX fix, the eye test still reported 0 with back faces drawn; on `eye_leak_selftest.py`'s scene, a hidden socket gives 10,614 culled pixels and 0 straight through.
- **After deleting BMesh elements, new ones reuse the freed slots: if code relies on vertex indices, tag new verts with an int layer and `bm.verts.sort()` before `to_mesh`.** Also refresh the view layer after moving a camera, before `world_to_camera_view`. *Why:* M1's shape keys landed on scrambled vertices, and its first lip-polygon projections used the previous camera.
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

- **Parenting new geometry to an imported glTF armature moves it** (the armature sits under a rotated import node). Build in world space, then set `matrix_parent_inverse = arm.matrix_world.inverted()`. *Why:* the first Tripo face proof of concept rendered the new muzzle off to the side.
- **Zero every shape key's value before a glTF export, and check the GLB's `mesh.weights`.** New keys export at their current value, and three.js starts each morph from it. *Why:* the Tripo proof of concept loaded with all 38 face morphs stuck at 1.0 until the app touched them (`tools/character_v2/tripo_face_poc.py` now records `glb_default_weights_nonzero`).

- **Three.js look-at offsets are applied only during render** (`life.ts` restores bones afterwards), so a test that reads bone quaternions between frames sees the rest pose. Measure inside `renderer.render`. *Why:* the first E5 app check reported "no gaze" while the eyes were moving.
- **Don't "fix" an eyeball that pokes through the skin by pushing it back:** a recessed eye reads hollow. Cover it with the lids and socket instead. *Why:* eye candidate E1.

- **Playwright video recording needs its own ffmpeg (not installed here); don't run `playwright install`.** Record a CDP screencast (`Page.startScreencast`) and encode the frames with the system `ffmpeg` at their own timestamps. *Why:* the F3 performance recording.
- **With software WebGL, a still taken right after an event can show the frame before it.** Trust the morph weights read back from the live meshes, or wait about 400 ms. *Why:* the first wink and blink stills looked open while the weights were 1.

- **Renaming items of a Blender collection while iterating it re-sorts it** (some get renamed twice). Iterate over `list(...)`. *Why:* the first retarget found "no clips" because the actions became `v1_v1_*`.
- **Record app animation under software WebGL with virtual time** (`threejs_body_performance.py`: performance.now/rAF/setTimeout advanced 1/30 s per frame). Otherwise the app's 0.1 s frame clamp halves animation speed below 10 fps. Map screencast frames to virtual time (it also emits UI-repaint frames). *Why:* the first Stage 3A recording ran at 0.45× speed.
- **Record the app at ≥ 900 px wide.** Narrower viewports switch to the mobile layout and the avatar shrinks to a sliver. *Why:* the 760 px body recording showed only the UI.
- **The app finds bones by V1's semantic names** (look-at, talk-gesture filter, VFX sockets). Rename other rigs to them rather than special-casing the runtime. *Why:* with Mixamo names the gestures would have silently played nothing.
- **Calibrate a fidelity camera, inspect the overlay, then lock it.** A tight lens cropped the forearms and looked like a modelling error. *Why:* Phase A's first hero comparison.
- **Before re-skinning a Tripo region, list every mesh with weights on the bones you will move** (e.g. any vertex on `f*.L`). Don't trust a parts map. *Why:* Phase C's streaking fur came from `part_18`, a second arm-fur part that still followed the finger bones.
- **Fit an underlay under clumped fur from per-direction percentiles of the fur's own vertices, not ray casts.** Rays slip between clumps and hit the leg or nothing, so the sleeve pokes out. *Why:* C1's first sleeve showed as a dark slab behind the forearm.
- **Evaluate deformation with a same-pose sheet against the previous candidate** (`phase_c_evidence.py` plays the same actions on both), and compare variants with `--quick` before choosing a parameter. *Why:* rigidity 0 / 0.35 / 1 look alike at rest and only differ under poses.
- **In headless bpy, `import bpy` before `bmesh`.** *Why:* `ModuleNotFoundError: bmesh` on the first Phase C run.
- **The Skin modifier leaves an internal disc wherever its graph branches:** a ring of edges with 3 faces each. To get a closed, manifold result, build simple non-branching chains that overlap where the branches would join. *Why:* C1's hand had 16 non-manifold edges, and cleanup passes couldn't remove them safely.
- **Guard texture transfers against the source's painted shadows and edges:** fall back to a measured base tone for dark samples and for points far from the source surface. *Why:* C2's first bake copied the fur-coloured wrist band from Tripo's fist onto the palm, and the hand read as fingers only.
- **Playwright screenshots under SwiftShader at deviceScaleFactor 2 can time out** (30 s). Use 1× for app checks, or raise the timeout. *Why:* the first `threejs_hand_check.py` run.

### Context and token use
- **Don't pull whole docs or huge command outputs into context: grep or read slices, and send big outputs to a file.** *Why:* 20–40k-character tool outputs (API docs, artifact guides) cost a lot and were mostly unused.
- **Don't re-read the same screenshot or file several times.** Note what you saw. *Why:* repeated reads of the same images.

## Retired rules

(none yet)

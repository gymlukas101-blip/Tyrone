# Monkey V2: progress checkpoint

Kept current after each bounded step. If a run is interrupted, resume from **next_single_action**.

**Direction (2026-11-21):** Tripo-locked rebuild.
- **Visual authority:** the owner's Tripo export.
- **Behaviour authority:** V1 production Monkey: morph names, clips, face mixer.
- **Plan:** `ADR_001_tripo_strategy.md`. The Stage 0–1 blockout (candidates A and B) is kept as research only.

| Field | Value |
|---|---|
| base_commit | `1a718c1` on `feature/monkey-character-v2` (branched from main `254828b`) |
| feature_branch | `feature/monkey-character-v2`; never merged to `main` |
| source_model_sha256 | production `monkey.glb` `e9f02358` (unchanged); Tripo `8f990a33`; F3 `.blend` `295d1c8d` / `.glb` `504c4373` (approved face, immutable); approved images: `refs/approved/` (hashes in the manifest) |
| current_stage | **Phase A essentials + Phase B (Stage 3A) proof done.** Next: Phase C, the clean arm/hand prototype |
| last_completed_step | B2: Tripo skeleton renamed to V1 semantic bones; 5 V1 clips retargeted relative to V1's idle stance (Tripo keeps his own stance); app: clip-independent emote cleanup; full-body real-time app performance (listen → think → speak + smile + gesture → idle). Phase A: `CHARACTER_DESIGN_AUTHORITY.md`, fidelity loop with a locked hero-B camera, overall and regional IoU, overlay and heat map |
| last_verified_artifact | `character_v2_workspace/tripo_body/tripo_body_B2.blend` (`9fdfe022`) / `.glb` (`2ee83f1c`); `renders/body_B2/body_performance.mp4` (21.6 s, normal speed) |
| validation_command_and_result | `retarget.py` → 51 bones renamed, 0 orphan vertex groups, 5 clips × 165 channels in the GLB. `threejs_body_performance.py ui/dist B2.glb` → the running clip per phase is idle / listen / think / talk / idle, anim-time ratio 1.00 (virtual 30 fps); the gesture `talk_gest_open_palms` fired from streamed text; smile 0.54 while talking; face neutral after (no clip for `happy`; cleanup timer). Fidelity (locked camera): Tripo 0.886 = B2 0.886 vs hero B; B1 idle 0.740 → B2 idle 0.886; B2 vs Tripo neutral 1.000/1.000/0.997. `pytest tests/test_character_v2_*.py` → 15 passed; full suite: see the commit |
| known_failures | Fixed: actions renamed twice while iterating (no clips found); B1 boxer stance from V1's bent-elbow base (fixed by base-relative retarget); recording at half speed under SwiftShader (fixed by virtual time); screencast repaint frames stretching the video; narrow layout hiding the avatar at 760 px; the hero camera cropping the forearms (rejected before locking). **Open:** elbow fur clumps crumple at strong bends; mitten fists (no digits); only 5 of 37 clips; head/ear/tuft/mic springs need bones Tripo lacks; the hero B feet/hips/forearms gap (pose/perspective) |
| next_single_action | Phase C step 1 (`STAGE3_PLAN.md`): build the left shoulder→wrist underlay sleeve fitted under Tripo's arm fur, Data-Transfer the arm clump weights from it, and compare elbow deformation at 0/60/120° and regional IoU against B2 |
| files_changed | `tools/character_v2/{retarget,clip_sheet,threejs_body_performance,measure_character,fidelity_render,fidelity}.py` (new); `ui/src/avatar3d.ts` (expression cleanup); `docs/character_v2/{CHARACTER_DESIGN_AUTHORITY.md, STAGE3_PLAN.md, PROGRESS.md, tripo_poc_manifest.json}`; `docs/agent-lessons.md`; `tests/test_character_v2_fidelity.py` |
| external_tool_versions | bpy 5.3.0, Mesa software EGL, Playwright Chromium + SwiftShader, system ffmpeg. No Blender GUI or MCP; no local computer shared |

## Stage 3A run (2026-11-23): verified / failed / untested
- **VERIFIED (cloud container):**
  - Semantic rename keeps every weight.
  - 5 clips play in the app with F3's face, speech, gaze and emotes.
  - Full-body real-time performance.
  - Expressions return to neutral without clips.
  - Fidelity loop reproducible with a locked camera.
  - Measured improvement B1 → B2.
- **FAILED and fixed:** see known_failures.
- **UNTESTED:**
  - Windows / WebView2 / GPU frame time.
  - The 32 other clips.
  - Fingers.
  - Real TTS audio.
  - Overlay window.

## Face run (2026-11-21): verified / failed / untested
- **VERIFIED (cloud container):**
  - E6 matched against Tripo and E5 (7 views).
  - F3 in Blender: 20 combined poses.
  - F3 in the real app: speech, blink, wink, 4 emotions, emotions while talking, cursor-driven eyes and head (Mixamo), and a recorded performance.
- **FAILED and fixed:** see known_failures.
- **UNTESTED:**
  - Windows / WebView2 / GPU frame time.
  - Real TTS audio.
  - The overlay window.
  - Body clips and hands.

## Eyes run (2026-11-21): verified / failed / untested
- **VERIFIED (cloud container):**
  - The hybrid C eye defects, measured.
  - E5 matches the Tripo source in 7 matched views.
  - Sealed geometry: no background or skull-interior leaks.
  - Blinks, a wink, squint, wide, happy, angry and sad, plus 4 gaze directions, in Blender.
  - App blink, emotes and look-at drive E5 in Three.js.
- **FAILED and fixed:** recessed eyeball (E1); blink sliver (E2–E3).
- **UNTESTED:**
  - Windows / WebView2 / GPU.
  - Wink in the app (no trigger).
  - Combined face + eyes (E5 has Tripo's original open mouth; the hybrid C muzzle isn't combined).
  - Head-follow on Tripo's bone names.

## Verified / failed / untested (Tripo face PoC run, before the eyes)
- **VERIFIED (cloud container):**
  - The Tripo GLB imports, renders and re-exports.
  - Matched-camera comparison of V1, B and Tripo (9 views).
  - The hybrid face performs 15 visemes and 23 other face morphs in Blender renders.
  - The same GLB loads in the real UI (Three.js, `?demo&model=`) and the app's own speech, emote and blink code drives it.
  - The production GLB is untouched.
- **FAILED (as expected; this is the control):** direct deformation of Tripo's mesh (A0) can't seal the lips or blink.
- **UNTESTED:**
  - Windows / WebView2 / GPU frame time.
  - Body clips on Tripo (none yet).
  - Hands.
  - Eye tracking.
  - Fur deformation in motion.
  - Real TTS audio driving the visemes (fed synthetic viseme frames instead).

## Durable storage
The cloud workspace is ephemeral. Each accepted `.blend` and GLB, plus the evidence sheets, is sent to the owner as a session file attachment; their hashes are in `tripo_poc_manifest.json`. A private Git LFS asset repository would be better, but creating one changes the owner's GitHub account, so it needs their approval first. Rebuilding is deterministic from the Tripo source with the command in the manifest.

## Stage checklist (Tripo-locked)
- [x] Stage 0: preflight. Branch and production hash checked; the Tripo export is present.
- [x] Stage 1: Tripo audit, matched views and look-match spec (`TRIPO_AUDIT.md`).
- [x] Strategy proof of concept: A0 direct vs C hybrid on the face. Decision: `ADR_001_tripo_strategy.md`.
- [x] Stage 2a: eyes. E5 candidate built and verified, awaiting owner review (`EYES_E5.md`).
- [x] Stage 2b: face. F3 integrated face, speaking and acting in the app, awaiting owner review (`FACE_F3.md`).
- [ ] Stage 2c: face sculpt pass (mouth shapes, muzzle rim weld) once F3 is approved. Gaze, sculpted shapes, lip-line texture, combination tests (speech + smile, speech + squint, wink while talking).
- [x] Stage 3A: semantic skeleton + 5 retargeted clips in the app (B2); design authority + fidelity loop (Phase A).
- [ ] Stage 3 (Phase C–E): clean arm/hand prototype, then the remaining 32 clips (`STAGE3_PLAN.md`).
- [ ] Stage 4: fur, materials (atlas the 39 + 5 materials), proper bakes.
- [ ] Stage 5: all 37 clips plus squash/stretch, acting and secondary motion.
- [ ] Stage 6: acceptance in the app on the Dell (frame time, every state and clip).

## Earlier work (kept for reference)
Stage 0–1 blockout on V1's topology (candidates A and B, `STAGE1_REPORT.md`, `VISUAL_SPEC.md`, strict `validate.py`) is superseded by the Tripo direction. Its tools stay in use: `render_views.py`, `sheet.py`, `inventory.py` and `contract.py`.

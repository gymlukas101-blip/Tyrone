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
| current_stage | **Phase C prototype (C1) done**: clean left arm + articulated left hand + deep brows; Phase D gate passed on fidelity. Next: the 3 C1 fixes, then mirror to the right arm |
| last_completed_step | C1 (`PHASE_C.md`): left arm underlay sleeve (Data-Transfer fur UVs), all left-arm clumps (`part_2`, `part_18`, body) re-skinned rigidly off the bone chain (Tripo's finger weights removed), Skin-modifier articulated left hand in Tripo's fist, 9 pose clips, `elbowBend_L` corrective (Pose-Shape-Keys method) + app driver, `talk_gest_open_palms` opens the hand; brows: `brow.L/R` bones + 7 per-side morphs, richer asymmetric acting, `worried` / `focused` cues, brow beats on stressed syllables |
| last_verified_artifact | `character_v2_workspace/phase_c/tripo_phaseC_C1.blend` (`1ba43098`) / `.glb` (`ec58ad87`); `phase_c/evidence/sheet_*.png`; `renders/phase_c_C1/body_performance.mp4` (`c538b719`, 20.9 s) and `hand_check/sheet_app_hands.png` |
| validation_command_and_result | C1: `phase_c.py` → 190 clumps re-skinned (112 + 55 + 23), 234 finger weights remapped, corrective on 3 meshes (≤ 28 mm). Fidelity vs hero B (locked camera): overall 0.886 → 0.889, forearms 0.788 → 0.836, hands 0.832 → 0.904, upper arms 0.937 → 0.931, rest ± 0.003; vs Tripo neutral 0.992 / 0.985 / 0.990. Topology: hand 100% quads, closed, 16 non-manifold edges; underlay 100% quads, 2 hidden end loops. Runtime: +1 draw call, +5.9% vertices. App (`threejs_hand_check.py`): hand_open / point / grip pose the fingers; `elbowBend_L` = 1.00 at 120°, 0 at rest; the gesture opens the hand mid-clip (f2.01 quat w 0.94 → 0.99 → 0.86); 0 page errors. `threejs_body_performance.py`: idle / listen / think / talk / idle, ratio 1.00; thinking brows browSqueeze 0.25 + browDown_R 0.15; curious cue browOuterUp_R 0.46 while talking. Vitest 50 passed (new: brow beats, cues, corrective driver); `pytest tests/test_character_v2_*.py` 16 passed |
| known_failures | Fixed: actions renamed twice while iterating (no clips found); B1 boxer stance from V1's bent-elbow base (fixed by base-relative retarget); recording at half speed under SwiftShader (fixed by virtual time); screencast repaint frames stretching the video; narrow layout hiding the avatar at 760 px; the hero camera cropping the forearms (rejected before locking). **Open:** elbow fur clumps crumple at strong bends; mitten fists (no digits); only 5 of 37 clips; head/ear/tuft/mic springs need bones Tripo lacks; the hero B feet/hips/forearms gap (pose/perspective). **C1 fixed during the run:** `bmesh` import before `bpy`; brow bones unmapped in the region labels; sleeve poking out behind the forearm (rays slipped between clumps → per-sector fur percentiles); fingers hanging down (re-laid as a punch fist); `part_18` arm fur still on finger bones (the streak). **C1 open:** straight elbow parts the tufts; knuckle support has no IK (the fist goes below the floor); flat hand colour; right hand still the mitten |
| next_single_action | C2 = C1 + (1) voxel-merge the knuckle-bar junction (16 non-manifold edges) and re-weight, (2) bake Tripo's fist texture onto the hand (F3 muzzle grid bake), (3) widen the underlay at the outer elbow; then mirror the arm/hand build to the right side and re-run `phase_c_evidence.py` + fidelity |
| files_changed | `tools/character_v2/{retarget,clip_sheet,threejs_body_performance,measure_character,fidelity_render,fidelity}.py` (new); `ui/src/avatar3d.ts` (expression cleanup); `docs/character_v2/{CHARACTER_DESIGN_AUTHORITY.md, STAGE3_PLAN.md, PROGRESS.md, tripo_poc_manifest.json}`; `docs/agent-lessons.md`; `tests/test_character_v2_fidelity.py` |
| external_tool_versions | bpy 5.3.0, Mesa software EGL, Playwright Chromium + SwiftShader, system ffmpeg. No Blender GUI or MCP; no local computer shared |

## Phase C run (2026-11-23): verified / failed / untested
- **VERIFIED (cloud container):**
  - C1 rebuilds from B2 headless.
  - Regional IoU up on forearms and hands vs the hero, nothing else down by more than 0.006.
  - Pose library deforms cleanly at 60–120°.
  - Corrective solved and driven in the app.
  - Fingers in the app gesture.
  - Brow morphs + bones; richer acting in the app.
- **FAILED and fixed:** see known_failures.
- **UNTESTED:**
  - Windows / WebView2 / GPU frame time.
  - Right arm.
  - Clips beyond the 5 + 9 poses.
  - Knuckle-support contact (needs IK).
  - Interactive retopo (RetopoFlow, GUI only).

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

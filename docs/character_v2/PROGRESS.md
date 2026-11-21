# Monkey V2: progress checkpoint

Kept current after each bounded step. If a run is interrupted, resume from **next_single_action**.

**Direction (2026-11-21):** Tripo-locked rebuild.
- **Visual authority:** the owner's Tripo export.
- **Behaviour authority:** V1 production Monkey: morph names, clips, face mixer.
- **Plan:** `ADR_001_tripo_strategy.md`. The Stage 0–1 blockout (candidates A and B) is kept as research only.

| Field | Value |
|---|---|
| base_commit | `c661901` on `feature/monkey-character-v2` (branched from main `254828b`; main is at `f375abc`, production GLB unchanged there) |
| feature_branch | `feature/monkey-character-v2` (worktree `../tyrone-v2`); never merged to `main` |
| source_model_sha256 | production `monkey.glb` `e9f02358…1012` (unchanged); Tripo `MonkeyTripo.glb` `8f990a33…d107` (local only); hybrid C `.blend` `e671a21a…7660` (kept as an immutable reference) |
| current_stage | **Eyes (Stage 2a): candidate E5 ready for owner review.** Body work is on hold until the eyes pass review |
| last_completed_step | Eye defect audit of hybrid C (`EYES_E5.md` §1). E1→E5 reconstruction: Tripo's own painted eye on fitted eyeballs with `eye.L/R` bones, sealed one-piece lid and socket meshes, 7 lid keys. Verified in 7 matched views, 16 poses and the real app |
| last_verified_artifact | `character_v2_workspace/tripo_eyes/tripo_eyes_E5.blend` (sha256 `9e103642…b596`) and `.glb` (`f12cdf1b…6dcc`); see `tripo_poc_manifest.json` → `eyes_E5` |
| validation_command_and_result | `eye_audit.py … E5` → eyeballs 0 boundary / 0 non-manifold edges, sockets 0 non-manifold (64 hidden rim edges), 0 leak pixels. `eye_poses.py` → 16 poses × 4 views, 0 leak pixels. `threejs_face_check.py` → 3D, 7 eye morphs, app blink, emotes and look-at drive it (eye bones 6.7–14.4°). `pytest tests/test_character_v2_contract.py` → passes |
| known_failures | Fixed this run: E1 recessed the eyeball (hollow again); patchy sclera when gazing; blink sliver; open seams. **Open:** painted highlight rotates with gaze; squint/happy lash smudge; no lid-follows-gaze corrective; the app has no wink trigger; sclera whiter under the app's tone mapping; head bone name not mapped (eyes move, head doesn't) |
| next_single_action | **Owner review of the E5 eyes** (`EYES_source_vs_E5_7views.png`, pose sheets, Three.js sheet). If approved: an interactive Blender pass on lids and highlight (`EYES_E5.md` §6), then the mouth and face retopology on the same principles. If not: list the specific differences from Tripo to fix |
| files_changed | `tools/character_v2/{eye_audit,tripo_eyes,eye_poses}.py` (new); `threejs_face_check.py` (gaze steps, eye-bone measurement); `docs/character_v2/{EYES_E5.md, tripo_poc_manifest.json, PROGRESS.md}`; `docs/agent-lessons.md`; `tests/test_character_v2_contract.py` |
| external_tool_versions | bpy 5.3.0 (Python 3.13.18), Mesa 25.2.8 software EGL, Playwright Chromium + SwiftShader, UI built from main `f375abc`. No Blender GUI or MCP; no local computer shared with the session |

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
- [ ] Stage 2b: face to production. Gaze, sculpted shapes, lip-line texture, combination tests (speech + smile, speech + squint, wink while talking).
- [ ] Stage 3: hands (articulated fists), shoulders, V1 skeleton semantics on Tripo proportions, clip retargeting.
- [ ] Stage 4: fur, materials (atlas the 39 + 5 materials), proper bakes.
- [ ] Stage 5: all 37 clips plus squash/stretch, acting and secondary motion.
- [ ] Stage 6: acceptance in the app on the Dell (frame time, every state and clip).

## Earlier work (kept for reference)
Stage 0–1 blockout on V1's topology (candidates A and B, `STAGE1_REPORT.md`, `VISUAL_SPEC.md`, strict `validate.py`) is superseded by the Tripo direction. Its tools stay in use: `render_views.py`, `sheet.py`, `inventory.py` and `contract.py`.

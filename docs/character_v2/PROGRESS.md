# Monkey V2: progress checkpoint

Kept current after each bounded step. If a run is interrupted, resume from **next_single_action**.

**Direction (2026-11-21):** Tripo-locked rebuild.
- **Visual authority:** the owner's Tripo export.
- **Behaviour authority:** V1 production Monkey: morph names, clips, face mixer.
- **Plan:** `ADR_001_tripo_strategy.md`. The Stage 0–1 blockout (candidates A and B) is kept as research only.

| Field | Value |
|---|---|
| base_commit | `6409ff9` on `feature/monkey-character-v2` (branched from main `254828b`). `main` has moved on to `f375abc`; the production GLB there is unchanged (same hash) |
| feature_branch | `feature/monkey-character-v2` (worktree `../tyrone-v2`); never merged to `main` |
| source_model_sha256 | production `ui/public/models/monkey.glb` `e9f02358…1012` (unchanged); Tripo source `MonkeyTripo.glb` `8f990a33…d107` (local only, not committed) |
| current_stage | Tripo Stage 1 (audit + look-match spec) done; **Stage 2 (face) proof of concept done, strategy C chosen** |
| last_completed_step | Hybrid face proof of concept `tripo_face_hybrid_C`: Tripo body, fur, headset and brow, plus a new muzzle (lip loops, cavity, teeth, tongue) and eyeballs with lids. 38 face morphs with V1 names, driven by the real app in Three.js |
| last_verified_artifact | `character_v2_workspace/tripo_poc/tripo_face_hybrid_C.blend` (sha256 `e671a21a…7660`, textures packed) and `.glb` (sha256 `5b245d4e…beed`); full list in `tripo_poc_manifest.json` |
| validation_command_and_result | `tripo_face_poc.py … --mode hybrid` → 38 morphs, default weights all zero. `threejs_face_check.py ui/dist …glb out` → kind 3d, 38 morphs, the app drives aa 0.97 / PP 0.97 / O / E / FF, blink 1.0, emotes; barge-in decays to ≈0; console: 2 × 404 (an app asset, not the model). `contract.check_functional` face stage → 0 failures (notes: 5 body morphs, 37 clips not yet). `pytest tests/test_character_v2_contract.py` → 9 passed |
| known_failures | Fixed during the run: parenting new parts under Tripo's armature moved them (needed the parent-inverse matrix); Tripo's open-mouth hole made the new lips dive inward (now bridged); GLB default morph weights were 1.0 (now zeroed and checked). **Open:** no clips on the Tripo skeleton yet; eyes don't track; procedural smile and sad shapes are subtle; the muzzle colour is a planar projection (soft on the steep sides); a faint light line along the closed lips in Three.js |
| next_single_action | Eye gaze plus a sculpt pass on the face shapes (smile corners, sad, lip-line colour) in the hybrid builder. Then start Stage 3: fit V1's skeleton semantics onto the Tripo body and retarget one clip (`idle`) as the first animation proof |
| files_changed | `tools/character_v2/{tripo_face_poc,threejs_face_check}.py` (new); `render_views.py` (top / bottom / face_side views); `contract.py` (functional mode) + test; `docs/character_v2/{TRIPO_AUDIT.md, ADR_001_tripo_strategy.md, tripo_poc_manifest.json, PROGRESS.md}`; `docs/agent-lessons.md`; `docs/IMPLEMENTATION-NOTES.md` |
| external_tool_versions | bpy 5.3.0 (Python 3.13.18), Mesa 25.2.8 software EGL, Pillow 12.3.0, Playwright Chromium + SwiftShader (UI built from main `f375abc`). No Blender GUI or MCP; not tested on Windows |

## Verified / failed / untested (this run)
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
- [ ] Stage 2: face to production. Gaze, sculpted shapes, lip-line texture, combination tests (speech + smile, speech + squint, wink while talking).
- [ ] Stage 3: hands (articulated fists), shoulders, V1 skeleton semantics on Tripo proportions, clip retargeting.
- [ ] Stage 4: fur, materials (atlas the 39 + 5 materials), proper bakes.
- [ ] Stage 5: all 37 clips plus squash/stretch, acting and secondary motion.
- [ ] Stage 6: acceptance in the app on the Dell (frame time, every state and clip).

## Earlier work (kept for reference)
Stage 0–1 blockout on V1's topology (candidates A and B, `STAGE1_REPORT.md`, `VISUAL_SPEC.md`, strict `validate.py`) is superseded by the Tripo direction. Its tools stay in use: `render_views.py`, `sheet.py`, `inventory.py` and `contract.py`.

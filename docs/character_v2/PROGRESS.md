# Monkey V2: progress checkpoint

Kept current after each step. If a run is interrupted, resume from **next_single_action**.

| Field | Value |
|---|---|
| base_commit | `254828b` (main: "Course helper: Storyline/Rise modules like the owner's Module 2") |
| feature_branch | `feature/monkey-character-v2` (worktree `../tyrone-v2`; never merged to `main`) |
| source_model_sha256 | `e9f023589860e402bb048eaf179fd0405b2c8be28f3ba1946acbbca80e061012` (`ui/public/models/monkey.glb`, 7,523,092 bytes; unchanged) |
| current_stage | Stage 1 complete (bounded blockout). Stage 2 not started |
| last_completed_step | Candidates A and B v005 built, rendered, validated (both pass); B recommended (`STAGE1_REPORT.md`) |
| last_verified_artifact | `character_v2_workspace/blend/monkey_v2_cand_B_005.blend` (sha256 `32ff5175…3a15`) and its export `validation/monkey_v2_cand_B_005.glb` (sha256 `d393ed27…ce28`) |
| validation_command_and_result | `bpy python tools/character_v2/validate.py -- …/monkey_v2_master_000.blend …/monkey_v2_cand_B_005.blend character_v2_workspace/validation` → `ok: true`, 0 failures (A: the same). `pytest tests/test_character_v2_contract.py` → 8 passed |
| known_failures | None open. Fixed along the way: Workbench needed software EGL; imported clips drove the face in "neutral" renders; muzzle over the eyes (B v002); chest ripples (v003); forearm bell, then disc (v004); keys ×2.5 and the exporter splitting FurCards vertices (v005). Open design issues: see `STAGE1_REPORT.md` |
| next_single_action | Load `monkey_v2_cand_B_005.glb` in the UI `?demo` mode on a local branch (not replacing the production GLB), check lip-sync, idle and gestures in Three.js, then start Stage 2 with the eyes |
| files_changed | `.gitignore` (local workspace ignored); `tools/character_v2/{inventory,bpy_selftest,render_views,sheet,blockout,contract,validate}.py`, `tools/character_v2/README.md`; `tests/test_character_v2_contract.py`; `docs/character_v2/{baseline_contract.json,PROGRESS.md,pipeline_capabilities.md,VISUAL_SPEC.md,STAGE1_REPORT.md}`; `docs/agent-lessons.md` (3 rules); `docs/IMPLEMENTATION-NOTES.md` |
| external_tool_versions | `bpy` 5.3.0 (Python 3.13.18), Mesa 25.2.8 software EGL, Pillow 12.3.0. No Blender GUI or MCP (see `pipeline_capabilities.md`) |

## Stage checklist

### Stage 0: baseline ✅
- [x] Audit of the GLB, the animation contract and the Blender tools → `baseline_contract.json`:
  - 57 bones, 9 meshes, 44,110 vertices, 61,508 triangles;
  - 50 shape keys, including the 15 visemes;
  - 37 clips.
- [x] Dedicated worktree and branch. The local workspace `character_v2_workspace/` is git-ignored (`.blend` files, renders, references).
- [x] Source GLB hash frozen. Native baseline `monkey_v2_master_000.blend` (sha256 `fdc6bd64…eff8e`, checked unchanged after every candidate build).
- [x] Fixed-camera baseline renders: clay and texture, 6 views.
- [x] Disposable-scene test of the headless bpy pipeline (`bpy_selftest.py`: `ok`). This is the documented alternative to an MCP bridge.
- [x] `pipeline_capabilities.md`.

### Stage 1: bounded blockout ✅
- [x] Before/after modeling spec → `VISUAL_SPEC.md`.
- [x] Candidates A (measured) and B (bold), native `.blend` per version (001–005).
- [x] Renders: front, ¾, side, back, face; expression combination; `flex` and `talk_gest_open_palms` poses; fur cards.
- [x] `validate.py` + `contract.py` + tests. Both candidates pass.
- [x] Recommendation and open issues → `STAGE1_REPORT.md`.
- Not done, as instructed: no fur detail, no generative 3D, no production GLB replacement, no merge to `main`.

### Stage 2: face and mass (not started)
- [ ] Smaller, deeper eyes, with the eye/eyelid keys rebuilt.
- [ ] Muzzle region retopology / smoothing, plus nostrils.
- [ ] Trapezius and shoulder mass; the head sits lower.
- [ ] Three.js check of the candidate in `?demo` (lip-sync, idle, gestures).

## Local workspace layout (not committed)
```
character_v2_workspace/
  refs/        01_TARGET.png, 02_CURRENT.png (from the owner's production kit)
  blend/       monkey_v2_master_000.blend, monkey_v2_cand_{A,B}_00{1..5}.blend
  renders/     baseline_000/, cand_*/, expr_*/, pose_*/, fur_*/, V2_stage1_*.png sheets
  validation/  candidate GLBs, the baseline control GLB, *_validation.json
  logs/        inventory, self-test, blockout reports (*.json), render and validate logs
```

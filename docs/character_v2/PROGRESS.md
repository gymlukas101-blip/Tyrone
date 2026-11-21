# Monkey V2: progress checkpoint

Kept current after each bounded step. If a run is interrupted, resume from **next_single_action**.

**Direction (2026-11-21):** Tripo-locked rebuild.
- **Visual authority:** the owner's Tripo export.
- **Behaviour authority:** V1 production Monkey: morph names, clips, face mixer.
- **Plan:** `ADR_001_tripo_strategy.md`. The Stage 0–1 blockout (candidates A and B) is kept as research only.

| Field | Value |
|---|---|
| base_commit | `1de6d0b` on `feature/monkey-character-v2` (branched from main `254828b`) |
| feature_branch | `feature/monkey-character-v2` (worktree `../tyrone-v2`); never merged to `main` |
| source_model_sha256 | production `monkey.glb` `e9f02358…1012` (unchanged); Tripo `8f990a33…d107` (local only); hybrid C `e671a21a…7660` and E5 `9e103642…b596` kept as immutable references |
| current_stage | **Face (Stage 2b): F3 ready for owner review** (E6 eyes + brows + mouth on one character, speaking and acting in the app). Body, hands and clips are not started |
| last_completed_step | E6 eye polish (darker, less exposed sclera; clean lid UVs and crease; head-fixed catchlight; lid follow; distinct lid emotions). App: Mixamo head-follow and an independent wink. F3: integrated face with a grid transfer-baked muzzle and stronger brow and mouth moods. Recorded performance in the app |
| last_verified_artifact | `character_v2_workspace/tripo_face/tripo_face_F3.blend` (sha256 `295d1c8d…db02`) and `.glb` (`504c4373…a4ff`); E6 eyes-only `tripo_eyes_E6.*`; see `tripo_poc_manifest.json` → `eyes_E6_face_F3` |
| validation_command_and_result | `eye_audit.py` E6 and F3: 0 leak pixels, eyeballs closed (0 open / 0 non-manifold). `eye_poses.py` E6: 16 poses, 0 leaks. `threejs_face_check.py ui/dist F3.glb` → 3D, 38 morphs, no page errors; app-driven speech, blink, wink L (`blink_L` 1 / `blink_R` 0), 4 emotions, talking while smiling or sad, gaze 4 ways. `threejs_performance.py` → 143 s video, head 18° / eyes 20° on cursor. UI `tsc` + build OK; full `pytest`: 618 passed, 12 skipped |
| known_failures | Fixed this run: grey sclera overshoot (E6 first pass); a leftover highlight streak; pale gaps when brows moved (brow band); mouth moods too timid; the wink snapshot racing the renderer. **Open:** muzzle rim outline; procedural mouth shapes need a sculpt pass; emote presets don't end without clips; app tone mapping pales cream surfaces |
| next_single_action | **Owner review of F3** (`FACE_F3.md`, `performance.mp4`, `G1`–`G5` sheets). If approved: Stage 3, which is fitting the 57 V1 bone semantics and the 37 clips onto Tripo's body (start with `idle` + `talk`) and the articulated hands, so emotes and gestures play as clips |
| files_changed | `tools/character_v2/{tripo_eyes,tripo_face_poc,eye_poses,threejs_face_check}.py` (changed); `tools/character_v2/{tripo_face_v2,threejs_performance}.py` (new); `ui/src/avatar/life.ts` (Mixamo mapping), `ui/src/avatar3d.ts` (wink), `ui/src/main.ts` (`wink` event); `docs/character_v2/{FACE_F3.md, PROGRESS.md, tripo_poc_manifest.json}`; `docs/agent-lessons.md`; `tests/test_character_v2_contract.py` |
| external_tool_versions | bpy 5.3.0, Mesa 25.2.8 software EGL, Playwright Chromium + SwiftShader, system ffmpeg (screencast → mp4). No Blender GUI or MCP; no local computer shared with the session |

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
- [ ] Stage 3: hands (articulated fists), shoulders, V1 skeleton semantics on Tripo proportions, clip retargeting.
- [ ] Stage 4: fur, materials (atlas the 39 + 5 materials), proper bakes.
- [ ] Stage 5: all 37 clips plus squash/stretch, acting and secondary motion.
- [ ] Stage 6: acceptance in the app on the Dell (frame time, every state and clip).

## Earlier work (kept for reference)
Stage 0–1 blockout on V1's topology (candidates A and B, `STAGE1_REPORT.md`, `VISUAL_SPEC.md`, strict `validate.py`) is superseded by the Tripo direction. Its tools stay in use: `render_views.py`, `sheet.py`, `inventory.py` and `contract.py`.

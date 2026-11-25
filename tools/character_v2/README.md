# tools/character_v2: Monkey Character V2 pipeline (headless Blender)

These scripts run with the `bpy` module (Blender 5.3 as a Python package) except `sheet.py` and `contract.py`.
Outputs go to the git-ignored `character_v2_workspace/`. **Nothing here writes `ui/public/models/monkey.glb`.**
Workbench renders need EGL; on a headless Linux box, install `libegl1 libgl1-mesa-dri libgles2`.

```bash
PY=path/to/bpy-venv/bin/python          # pip install bpy==5.3.0 (Python 3.13)
W=character_v2_workspace
$PY tools/character_v2/bpy_selftest.py -- $W/selftest                       # capability test, disposable scene
$PY tools/character_v2/inventory.py -- ui/public/models/monkey.glb docs/character_v2/baseline_contract.json
$PY tools/character_v2/blockout.py -- $W/blend/monkey_v2_master_000.blend $W/blend/monkey_v2_cand_B_005.blend B \
    --report $W/logs/blockout_B_005.json
$PY tools/character_v2/render_views.py -- $W/blend/monkey_v2_cand_B_005.blend $W/renders/cand_B_005
$PY tools/character_v2/render_views.py -- $W/blend/monkey_v2_cand_B_005.blend $W/renders/expr_B \
    --morphs jawOpen=1,viseme_aa=1 --views face_front,face_34
$PY tools/character_v2/render_views.py -- $W/blend/monkey_v2_cand_B_005.blend $W/renders/flex_B --action flex --frame 20
$PY tools/character_v2/validate.py -- $W/blend/monkey_v2_master_000.blend $W/blend/monkey_v2_cand_B_005.blend $W/validation
python tools/character_v2/sheet.py $W/renders/cmp.png $W/renders/baseline_000:baseline $W/renders/cand_B_005:B \
    --views front,three_quarter,side,back --mode clay
```

Mouth M1 (on the E7 eyes blend):
```bash
$PY tools/character_v2/mouth_m1.py -- $W/eyes_e7/tripo_E7.blend $W/mouth_m1
$PY tools/character_v2/mouth_poses.py -- $W/mouth_m1/tripo_M1.blend $W/mouth_m1/poses_after --size 360 --all \
    --views front,three_quarter,side,low
python tools/character_v2/mouth_sheet.py $W/mouth_m1/poses_before $W/mouth_m1/poses_after $W/mouth_m1/M1_before_after_face.png
```

Eye leak test (any V2 blend with the E6/E7 eyes; prove it can fail first):
```bash
$PY tools/character_v2/eye_leak_selftest.py -- $W/eye_leak_selftest     # throwaway scene: guard, sealed 0, hidden socket > 0
$PY tools/character_v2/eye_poses.py -- $W/mouth_m1/tripo_M1.blend $W/mouth_m1/eye_leaks \
    --views front,three_quarter_L,three_quarter_R,closeup_L
```

The baseline `.blend` is `import_glb(monkey.glb)` saved as is (`tools/blender/common.py`).

| Script | Role |
|---|---|
| `inventory.py` | The runtime contract of a GLB: bones, meshes, shape key stats, clips, images |
| `bpy_selftest.py` | Proves query / edit / render / save / export / re-import on a throwaway scene |
| `render_views.py` | Fixed orthographic cameras (front, ¾, side, back, face); clay and texture; neutral face by default |
| `blockout.py` | Topology-preserving reshape presets A and B (bone fields, face fields, hands about the wrist) |
| `contract.py` | The compatibility rules (pure Python; tested in CI) |
| `validate.py` | Applies the rules to a candidate, plus a GLB export/re-import round trip |
| `sheet.py` | Comparison sheets (Pillow) |
| `tripo_face_poc.py` | Tripo direction: hybrid face (new muzzle with lip loops, eyes with lids, brow keys) or the direct control (`--mode direct`) |
| `mouth_m1.py` | M1 mouth on a V2 blend: mouth bag in the muzzle, tooth band, gums, tongue, one jaw field, all mouth keys rebuilt, numeric checks |
| `eye_audit.py` | Eye-region audit: geometry, socket backing, leak renders; holds the shared exact-colour leak helpers |
| `eye_poses.py` | Lid and gaze pose renders with per-eye leak counts (`hole_px` culled, `through_px`) in exact colours; `--hide` for a fail run |
| `eye_leak_selftest.py` | Proves the eye leak test can fail, on a throwaway scene (no private assets) |
| `mouth_poses.py` | Mouth pose renders (front, 3/4, side, low) with hole / foreign-geometry / poke-through tests in exact colours |
| `mouth_sheet.py`, `app_mouth_sheet.py` | Before/after mouth sheets from `mouth_poses.py` and `threejs_face_check.py` runs (Pillow) |
| `threejs_face_check.py` | Loads a candidate GLB in the real UI (demo build, `?model=`) and drives speech, blink and emotes with the app's own code; screenshots + morph read-back |

Status, decisions and open issues: `docs/character_v2/PROGRESS.md`, `ADR_001_tripo_strategy.md` and `TRIPO_AUDIT.md` (the Stage 1 blockout: `STAGE1_REPORT.md`).

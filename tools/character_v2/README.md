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

Status, decisions and open issues: `docs/character_v2/PROGRESS.md` and `STAGE1_REPORT.md`.

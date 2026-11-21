# Monkey V2: pipeline capabilities (what was tested and where)

Everything below ran in the **cloud container** (Linux, no GPU, no display). Nothing here was run on the owner's Windows PC, in the Blender GUI, or in the app's WebView.

## Tested and working

| Capability | How | Evidence |
|---|---|---|
| Headless Blender | `bpy` 5.3.0 wheel (Python 3.13) in a private venv. It's the `bpy` module, not a Blender install | `tools/character_v2/bpy_selftest.py`: disposable scene → query, edit, render, `.blend` save, GLB export, re-import with the bone, skin and shape key intact. Result `ok: true` |
| Render | Workbench engine through **software EGL** (`libegl1`, `libgl1-mesa-dri`, `libgles2` from apt). Without them Workbench aborts with "Couldn't open libEGL.so.1" | Every render under `character_v2_workspace/renders/` |
| Import/export | Production glTF settings (`tools/blender/common.py` `import_glb`/`export_glb`) | `validate.py` round trip: 57 bones, 9 meshes, 50 shape keys, 37 clips, 44,110 vertices |
| Contract | `tools/character_v2/inventory.py` → `docs/character_v2/baseline_contract.json` | Bones with rest matrices; meshes with counts, groups, materials, shape key delta stats; clips with channels; images |
| Candidate checks | `tools/character_v2/validate.py` (Blender) plus `contract.py` (pure Python, in CI via `tests/test_character_v2_contract.py`) | `character_v2_workspace/validation/*_validation.json` |

## Not available here, and why

| Thing | Status |
|---|---|
| **Blender MCP server** | Not configured. This session can't add an MCP server mid-run, and there's no Blender GUI for a socket add-on to connect to. The master prompt allows the alternative: "a documented, tested headless bpy alternative", which is the table above. On the owner's PC, a Blender MCP add-on can drive the same `.blend` files later. |
| Blender GUI / viewport / sculpt brushes | None. Every edit is scripted, deterministic and repeatable from the source `.blend`. |
| Cycles/EEVEE | Not used. Workbench (clay plus texture colour) is enough to judge form at this stage. Fur cards are alpha-tested, so Workbench draws them as opaque cards (`--fur` shows them). |
| Three.js / app render | Not run for the candidates. The production GLB isn't replaced, so the app is unaffected. |
| Windows | Not tested. |
| Video, YouTube references | Not used (YouTube is blocked from this container). |
| Blender add-ons | Only the bundled glTF importer/exporter. |

## Versions
- `bpy` 5.3.0, Python 3.13.18 (venv in the session scratchpad; recreate with `pip install bpy==5.3.0` on Python 3.13).
- Mesa `libgl1-mesa-dri` 25.2.8 and `libegl1` 1.7.0 (Ubuntu 24.04 packages).
- Pillow 12.3.0, for the comparison sheets.

## Pitfalls found (also in `docs/agent-lessons.md`)
1. **Imported clips drive the shape keys.** Setting key values isn't enough for a neutral face: detach `shape_keys.animation_data.action`. The GLB's stored default weights also show an angry face, so renders zero every key first.
2. **FurCards are flat-shaded and exactly coplanar where they share vertices.** Any non-uniform reshape tilts them apart, and the glTF exporter then splits about 400–1,100 extra vertices. `blockout.py` pins the authored corner normals instead. The untouched production model already gains 106 FurCards vertices when it goes through the same exporter; the candidates now round-trip to exactly the production count.
3. **Radial scaling amplifies the features already there.** The forearm's wrist bulb turned into a disc. An offset-surface bulge reads as a rounder mass.
4. **Steep face fields exaggerate shape keys** (`smile` grew ×2.5). Key deltas are now bounded to ×0.8–1.35.

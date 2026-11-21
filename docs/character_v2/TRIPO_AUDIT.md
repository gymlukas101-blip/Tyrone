# Tripo V2 source: asset audit and look-match spec

**Source:** `MonkeyTripo.glb`, the owner's Tripo export.
- sha256 `8f990a33…d107`, 5,603,184 bytes.
- Kept locally in `character_v2_workspace/refs/tripo_source/`. **Not committed:** the owner's private source asset.

**Audited with:** Blender 5.3 (bpy, headless, cloud container), using the production glTF importer settings (`tools/blender/common.py`).

**Evidence (local):**
- `renders/tripo_src/`: 9 fixed views, clay and texture, using the same cameras as V1 and candidate B.
- `renders/T1_*`: matched sheets.
- `renders/tripo_parts/`: each face part rendered alone.
- `logs/tripo_audit.json` and `logs/tripo_face_loops.json`.

## What the file is (observed)

| Item | Finding |
|---|---|
| Format / units / axes | glTF 2.0 binary. After import: Z up, faces −Y, feet at z = 0, **0.98 tall**. Practically the same scale and placement as V1, so V1's cameras frame it unchanged |
| Meshes | **39 parts** (`tripo_part_0…38`): 23,414 vertices, 29,093 triangles, **all triangles**, no quads |
| Topology | AI "triangle soup": many open shells. The torso part alone has 604 islands and 6,802 boundary edges: its fur clumps are separate open shells. No edge loops around eyes, lips or joints |
| Materials / textures | 39 materials, each one base-colour JPEG (64–2048 px). **No normal, roughness or AO maps.** That's 39 draw calls as shipped |
| Rig | Tripo auto-rig: **53 Mixamo bones** (`mixamorig:Hips…`); every part is weighted. Rest pose: arms hanging, fists near the floor |
| Morphs / clips | **None** |

### Face parts (rendered one by one)

| Part | What it is | Can it animate as is? |
|---|---|---|
| `part_9` | Cream muzzle and nose shell; the mouth is **sculpted half-open** (a hole, a smirk with teeth painted at the upper lip) | No: the boundary breaks into about 14 fragments with no lip loop, and it can't close |
| `part_28`, `35`, `37`, `38` | Thin dark-red strips and corner pockets that fake the mouth interior | No (cards) |
| `part_27`, `30` | **Eyes:** 50–80-vertex shells with a painted green iris. No eyeballs, no lids | No (no blink, no gaze) |
| `part_17` | Brow ridge / eye mask (M-shaped, separate) | **Yes:** a clean separate piece, so brow keys work directly |
| `part_8`, `13`, `15`, `31`, `32` | Crest and tufts | As skinned parts |
| `part_7`, `14` (cups `34`/`36`) / `part_21` | Headset band and cups / mic boom | As skinned parts |
| `part_4`, `10` | Ears | As skinned parts |
| `part_3`, `6` | **Fists**: closed mittens (no separate fingers seen in the renders) | Not as open hands (Stage 3) |

## Look-match spec (measured on the Tripo mesh; model units, about 0.98 tall)

| Feature | Observed | Note |
|---|---|---|
| Height / width | 0.98 tall; 0.97 wide across the arms (x ±0.4865) | Broader than V1 (whose arms reach x ±0.58 but are thin) |
| Head | Crest top z 0.98; eyes at z ≈ 0.72; brow ridge z 0.69–0.81, projecting to y −0.175 | The head sits low between the shoulders: shoulders reach z ≈ 0.74 |
| Muzzle | x ±0.136, z 0.53–0.715, front at y −0.25; projects **0.10 in front of the eyes** | Mouth line z ≈ 0.613, corners at x ±0.07–0.085 |
| Eyes | Centres (±0.058, −0.12, 0.72); visible opening about 0.07 × 0.06; iris green | Sit under the brow, in shadow |
| Fists | x ±0.24–0.455, z 0.006–0.18, front at y −0.25 | Knuckles rest on the floor plane |
| Palette (texture) | Copper / red-brown fur; cream muzzle (sRGB ≈ 0.91, 0.72, 0.45); green iris; dark-gold headset | From the texture, not a render |
| Fur | Modelled clumps (separate shells), with darker roots and lighter tips painted on | The silhouette comes from geometry, not cards |

**Not observable** (hidden geometry, not guessed): the inside of the fists, the skin under the fur clumps, and any mouth interior beyond the strips.

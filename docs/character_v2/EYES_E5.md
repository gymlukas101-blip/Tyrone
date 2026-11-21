# Monkey V2 eyes: defect audit of hybrid C and the E5 reconstruction

**Status:** E5 is the eye candidate for review. No body work starts until the owner approves the eyes.
**Run:** cloud container, Blender 5.3 (bpy, headless) and the real UI in headless Chromium (SwiftShader). Not tested on Windows / WebView2 / GPU.

**Tools:** `tools/character_v2/`:
- `eye_audit.py`: geometry, socket backing and leak renders;
- `tripo_eyes.py`: the builder;
- `eye_poses.py`: lid and gaze pose sheets;
- `threejs_face_check.py`: the app check.

## 1. Defects in hybrid C (measured, `eye_audit.py`)

| # | Defect | Evidence | Cause |
|---|---|---|---|
| 1 | **Hollow-looking sockets** | With the eye meshes removed, rays shot through each eye opening first hit the *inside of the back of the head* (up to y = +0.15, about 30 cm behind the face; `socket_backing`). The eyeball (r 33 mm) doesn't fill Tripo's opening (r up to 41 mm) | Tripo's face has **holes** where its painted eye shells sit; hybrid C hid the shells and put smaller eyeballs in the holes, with nothing behind them |
| 2 | **Floating lids** | Lid shells at 33.6–36.9 mm from the eye centre vs a 33.0 mm eyeball: a 0.6–3.9 mm air gap; the lid edges connect to nothing | Lids were separate spherical caps |
| 3 | **Lids cut into the brow** | 124 lid vertices inside Tripo's brow mesh (`tripo_part_17`) | Caps were placed by angle, not fitted to the face |
| 4 | **A different character's eyes** | Sclera white (0.95) vs Tripo's cream (sRGB 0.85/0.80/0.73); iris 17 mm vs Tripo's 22 mm; iris centred vs Tripo's nose-ward look | A procedural cartoon eye texture instead of the source's painted eye |
| 5 | **Double-sided lids** | `V2_Lid` used backface culling off to hide a single-sided shell | Masked the missing geometry instead of fixing it |
| — | Background visible through the head | **None** in either model: 0 magenta pixels in every eye disc, 7 views | The hollow look was the empty skull interior (#1), not a hole to the background |

Evidence: `character_v2_workspace/eye_audit/` (`E0_audit_sheet.png`, `*_eye_audit.json`, the magenta-background renders; the eyes-removed renders show the socket voids).

## 2. Options compared (with built geometry)

| Option | Built | Result |
|---|---|---|
| A: repair hybrid C | Measured only. The defects are structural (no socket, free-floating caps, a texture that isn't Tripo's). Fixing them means replacing every part, which is E | Rejected |
| **C: production hybrid reconstruction** (rebuild the connected skin and sockets; keep Tripo where it doesn't deform) | **E1 → E5**, five measured iterations | **Chosen for the eyes.** Matches the source in 7 matched views; sealed; animates in Blender and in the app |
| B: full retopology of the whole face and body | Not built this run | Still the target for the *face* as a whole (mouth, cheeks). E5's eye topology is what B's eye region would be: concentric lid loops, corners and a socket. A whole-character retopo needs an interactive Blender pass (section 6) |

E1 → E5:
- **E1 → E2:** E1 pushed the eyeball 25 mm back to stop it poking through the skin, which made it read hollow again. E2 keeps the eye at the source depth; the lids cover the rest.
- **E3:** a clean iris disc and a uniform sclera, so there are no patches when the eye turns.
- **E4:** a per-column lid closure, so blinks seal completely.
- **E5:** a lid-thickness tuck loop, and merged eyeball seams (closed surfaces).

## 3. E5: how it's built (`tripo_eyes.py`)
Everything except the eyes is Tripo's, including its original muzzle, so the eyes are judged against the source alone. Per eye:
- **Neutral opening measured from the source.** Front rays decide where Tripo's painted eye is the visible surface; that outline (64 samples, smoothed) is the lid margin.
  - L: opening radius 25–41 mm.
  - R: 24–40 mm.
- **Eyeball:** a sphere (r 43.3 / 42.6 mm) centred on the opening, front at the painted shell's depth (never recessed). It's skinned to a new **`eye.L` / `eye.R`** bone (child of the head), which the app's look-at already drives.
- **Eye colour is Tripo's own paint,** projected onto the sphere along the view axis:
  - the painted iris (with its highlight) is kept inside a fitted disc (34–36° radius, looking toward the nose like the source);
  - outside the disc is one uniform sclera colour (the median of Tripo's sclera, sRGB 0.89/0.85/0.79);
  - a soft darker limbal ring sits at the iris edge.
- **Lids and socket: one connected mesh per eye.** A tuck loop folds behind the margin (the lid's thickness). Nine loops run out over the eyeball and under Tripo's brow and muzzle skin, then continue round the back to a closed pole, so the socket is fully lined.
  - Single-sided material (backface culling on).
  - The only open edge is the tucked rim, hidden between lid and eyeball.
- **Shape keys** (V1 names): `blink_L`, `blink_R`, `squint`, `wideEyes`, `happyEyes`, `angryEyes`, `sadEyes`.
  - Every lid move is a rotation about the eyeball centre, so lids slide over the eye and never cut it.
  - Each column rotates by its own measured closing angle (up to 95°), so a blink seals along one seam whatever the opening's shape; the upper lid rides 0.3 mm over the lower.
- Tripo's painted shells (`part_27`, `part_30`) are hidden in the `.blend`, not deleted.

## 4. Verification

| Check | Result |
|---|---|
| Geometry | Eyeballs: 0 boundary and 0 non-manifold edges. Sockets: 0 non-manifold; the 64 boundary edges are the tucked rim (hidden). No face points into the eye |
| Background leaks | 0 magenta pixels in every eye disc, 7 neutral views + 16 poses × 4 views |
| Match to the source | `EYES_source_vs_E5_7views.png`: front, ¾ left, ¾ right, side, top-down, low angle, close-up; source / E5 / hybrid C rows |
| Poses (Blender) | `EYES_E5_poses_{closeup_L,front,three_quarter_R}.png`: neutral, wide, half blink, blink, squint, happy, angry, sad, surprised, wink (L), gaze left / right / up / down, blink while looking aside, squint while looking up |
| App (Three.js, `?demo&model=`) | Loads as 3D with the 7 eye morphs. The app's blink timer, emotes (happy → squint, angry → `angryEyes`, sad → `sadEyes`, surprised → `wideEyes`) and **look-at** drive it: eye bones rotate 14.4° / 9.6° sideways and 6.7° up/down, and 12.2° while talking (measured inside the render call). `EYES_E5_threejs.png` |
| Neutral defaults | GLB morph weights all 0 |

## 5. Open issues (honest)
1. **The painted highlight turns with the eye**: it's part of Tripo's paint. Better: a fixed specular or highlight card.
2. **Squint and happy:** the lower lid's lash-line gradient stretches into a soft smudge; the lid crease needs a sculpt.
3. **The upper lid doesn't follow vertical gaze** (no corrective yet), so looking up tucks the iris under the lid.
4. **No wink in the app:** it writes `blink_L` and `blink_R` together. The morphs are independent and verified in Blender; the app needs a wink trigger (a small UI change, not done).
5. **Tone mapping:** in Three.js the sclera looks whiter than in Blender. The material needs a look-dev pass in the app's lighting.
6. **Mixamo head bone:** Tripo's head bone is `mixamorig:Head`, so the app's head-follow doesn't engage yet (eyes only). Bone-name mapping is Stage 3.

## 6. Local Blender pass (what a viewport can do better than this container)
This container has no Blender GUI and no MCP connection, and none of your computer's folders are shared with this session. A short interactive pass on `tripo_eyes_E5.blend` in Blender 5.x would:
1. **Sculpt the lid crease and the lid thickness** on `V2_EyeSock_L/R` (Sculpt mode, Smooth/Crease brushes), keeping the loop structure and the tuck loop.
2. **Refine the `squint` and `happyEyes` shapes** (shape-key edit mode, or Pose Shape Keys). Paint the lash line on the sock texture (`V2_EyeSock_basecolor.png`).
3. **Add an upper-lid-follows-gaze corrective:** a driver from the `eye.*` bone pitch to a lid key, baked to a morph for glTF.
4. **Replace the painted highlight with a fixed one,** then check in Material Preview.
5. **Export** with the settings in `tripo_eyes.py` (`export_morph`, `export_skins`, `use_visible`), with every key at 0.

To run Claude Code there: share the project folder through the Claude desktop app (Settings → Claude Code → Remote Control), or start `claude remote-control` in it, and connect Blender MCP (`ahujasid/blender-mcp`) on that machine.

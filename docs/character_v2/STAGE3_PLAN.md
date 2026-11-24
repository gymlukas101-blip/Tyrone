# Monkey V2 Stage 3: articulated hands and the rest of the clip library (plan from measured results)

**Where we are (B2):**
- Tripo's deform skeleton, renamed to V1's semantic bones, plays 5 retargeted V1 clips (`idle`, `listen`, `think`, `talk`, `talk_gest_open_palms`) inside the app, with F3's face, gaze, speech and emote cleanup. Real-time recording: `renders/body_B2/body_performance.mp4`.
- Measured weak spots:
  - The elbow fur clumps crumple and stretch at strong bends (open-palms extreme, `talk`): `renders/B2_deformation_closeups.png`.
  - The fists are mittens skinned to Mixamo finger bones, so rotating the fingers would smear them.
  - Hero-B regional IoU is lowest at the feet (0.68), hips (0.74) and forearms (0.79). This is pose and perspective, the same in Tripo's source.

## Phase C: the clean shoulder / arm / hand prototype (one side first: left)
Tools: the headless bpy pipeline, plus an interactive pass when a local Blender + MCP session is available.
- **RetopoFlow:** evaluated as a GUI tool for that interactive pass only; it can't run headless.
- **Blender's native tools (scripted):** Shrinkwrap with a projection modifier stack, and Data Transfer for weights and UVs (the same operators as the Mesh Data Transfer add-on).
- **Pose Shape Keys** (Blender Studio) for the correctives; it can be driven from bpy.
- **Easy Weight's** operators; weight cleanup also by script.

1. **Underlay, not the fur.** A clean quad sleeve from the chest side through the shoulder, upper arm, elbow and forearm to the wrist.
   - Built from rings around the bone chain (as the lip loops were), each vertex projected onto Tripo's arm surface **under** the fur clumps (nearest point on `part_0`/`part_2` skin, inset 3 mm).
   - Edge loops: 3 at the shoulder (with a deltoid pole), 3 at the elbow (the pinch-preserving "elbow triangle" pattern), 2 at the wrist.
   - The fur clumps (`part_2` islands) are re-skinned by **Data Transfer from the underlay** (nearest-face-interpolated weights, smoothed), so each clump rides its sleeve patch rigidly instead of being stretched by Tripo's auto weights.
2. **Articulated hand that keeps the fist silhouette.**
   - Palm block plus 4 fingers (index, middle, ring, pinky: the Mixamo bones already exist, renamed f1–f4) plus a thumb.
   - Each finger is 3 segments with 2–3 loops per knuckle.
   - Built in the **closed-fist pose fitted to Tripo's mitten** (the fist silhouette is the authority), then rotated open to define the rest/open pose. Knuckles are heavy pads, as in the hero image.
   - Projection colour from Tripo's fist texture (the F3 muzzle transfer-bake method).
3. **Weights and correctives.**
   - Rigid-ish segment weights for the fingers, and a smooth 3-loop blend at the elbow and wrist.
   - Correctives (Pose Shape Keys idea, baked to glTF morphs):
     - `elbowBend_L`: volume kept at 90–130°;
     - `shoulderUp_L`: deltoid bulge;
     - `fistTight_L`: knuckle pads.
   - Driven at runtime by bone angles. The app needs a small corrective driver, about 20 lines in `avatar3d.ts` (bone angle → morph), tested.
4. **Poses to prove:** clenched fist, relaxed, open palm, point, grip, knuckle support (palm down, IK foot-like contact). Plus squash and stretch on the forearm (scale Y 1.15 / XZ 0.93), and the retargeted `talk_gest_open_palms` and `talk_gest_point`.
5. **Evidence:**
   - Matched front/side/¾ renders vs Tripo and hero B with **regional IoU**: forearms and hands must not drop below B2's 0.79 / 0.83 at rest.
   - Deformation close-ups at 0°, 60° and 120° elbow bend.
   - A topology report (quads %, no open edges on the underlay, no non-manifold edges).
   - A Three.js clip in the app.
   - A comparison table vs B2 for: visual fidelity, deformation, runtime (vertex/draw-call delta), complexity.
6. **Decision gate (Phase D):** expand to both arms, the legs and the hips only if the prototype is clearly better on deformation **without** losing fidelity (regional IoU within 0.01 at rest).

## Restoring the remaining 32 clips (batches, after Phase C locks the arm rig)
| Batch | Clips | Notes |
|---|---|---|
| 1. Talk gestures | `talk_gest_big`, `fist_palm`, `point`, `shrug`, `thumbs_up` | `point`/`thumbs_up` need fingers (after Phase C); `ARM_GAIN` tuned per gesture from contact sheets |
| 2. Emotes | `happy`, `sad`, `angry`, `surprised`, `laugh`, `wave`, `flex`, `dance` | clips end expressions themselves; the cleanup timer is the safety net |
| 3. Idle fidgets | the 10 `idle_*` + `attn_perk`, `think_eureka` | check the hand–head contacts (scratch head, cross eyes) for interpenetration with the bigger head/fists |
| 4. Sleep chain | `yawn`, `sit_down`, `sit_doze_loop`, `lie_down`, `sleep_loop`, `wake_groggy`, `wake_startle` | hips translation scaled; floor contact and foot sliding checks; sitting on Tripo's short legs may need a new authored pose |

For every clip:
- **Blender** contact sheet: 5 frames × 3 views, plus 4 deformation close-ups.
- **App** `poseAt` sheet plus a short real-time capture (virtual-time recorder).
- **Fidelity:** regional IoU of the idle frame unchanged.
- A clip counts as restored only after the visual check, not because its name exists.

**Squash, stretch and acting** (DK-Bananza-inspired, original keys): after the batches, add anticipation and overshoot to the talk gestures and emotes with `tools/blender/anim.py` beats on the semantic rig, plus forearm/chest volume-preserving scale.

## Clip batches done (2026-11-24, C3)
- **Coverage:** all 32 remaining V1 clips are retargeted onto C2 by `tools/character_v2/clip_batches.py`: batch 1 talk gestures, batch 2 emotes, batch 3 idle fidgets, batch 4 the sleep chain. The model carries 46 animations: V1's 37, plus the 9 Phase C poses.
- **Motion:** `retarget.retarget_clip`, relative to V1's idle stance on Tripo's own stance, with the hips scaled to his height.
- **Hands:** authored per clip, because V1's clips key every finger bone but carry no finger acting. Shapes: fist (rest), relaxed, open, splay, point, claw, thumbs-up.
  - The gesturing hand is measured: the one that rises most. Point and thumbs-up use the right hand, fist-into-palm the left.
  - Shapes fade in at 15% of a clip and out at 80–95%; loops hold them.
- **Grounding:** sitting and lying put V1's poses through Tripo's floor: −6 cm sitting, down to −21 cm lying. The sit/lie/wake/yawn clips are grounded per frame (the hips rise by the overlap, smoothed over ±1 frame). Floor contact now stays within about 2 cm, and the chain still joins up: sit → doze → lie → sleep → wake.
- **Fixed on the way:** the C2 hand tubes took weights from neighbouring fingers they touched in the fist, so open hands tore into shards. Each tube is now weighted only from its own chain (`phase_c.py`), and C2 was rebuilt.
- **Evidence:**
  - per-batch contact sheets: `clips_c3/b{1..4}_front.png` and `clips_c3/sheets_b*/`;
  - hand close-ups;
  - all 46 clips frozen mid-clip in the real app (`renders/clips_C3_app/sheet.png`, `threejs_clip_check.py`, 0 page errors).
- **Open:**
  - with the bigger fists, arms-crossed and hand-to-head clips (`idle_impatient_tap`, `idle_knuckle_crack`, `laugh`, `idle_scratch_head`) push fur into the chest and head;
  - no IK yet for contacts;
  - the gesture hand shapes are authored, not keyed by V1.

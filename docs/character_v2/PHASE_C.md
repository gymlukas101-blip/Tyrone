# Monkey V2 Phase C: arm and hand prototype (C1) and deep brows

**Candidate C1:**
- Built by `tools/character_v2/phase_c.py` from B2: Tripo body, F3 face, semantic skeleton, 5 retargeted V1 clips.
- Left side only; the right arm stays B2 as the control.
- Artifacts are in `character_v2_workspace/phase_c/` (not committed); hashes are in `tripo_poc_manifest.json` → `phaseC_C1`.

## What was measured on B2 first
| Finding | Number |
|---|---|
| Left arm fur is only clumps, with no skin under them | `part_2` 112 islands (largest 45 vertices), `part_18` 55 islands |
| Tripo's auto weights put arm fur on finger bones | Of the left arm fur: 356 vertices on `f2.03.L`, 114 on `f4.01.L`, 359 on `hand.L`, only 55 on `forearm.L` |
| A second arm-fur part also carried finger weights | `part_18` (elbow and inner upper arm): 435 vertices; it caused the "streak" when the fingers moved |
| The Mixamo finger bones are up the forearm, not in the fist | Bones at z 0.16–0.24; fist mesh at z 0.006–0.18 |
| Tripo's fist mitten is not closed | `part_6`: 17 holes, 308 boundary edges, triangle soup |

## What C1 builds
1. **Left arm underlay.**
   - A quad sleeve (17 rings × 16 segments, 272 vertices, 100% quads) from the shoulder through the elbow to the wrist.
   - Each ring's radius per direction is the fur's inner boundary (the lower sixth of the clump radii in that sector) × 0.93.
   - Directions without fur keep the ring's smallest radius, so the sleeve never shows outside the fur.
   - Dressed in the fur's own texture: UVs by **Data Transfer** (nearest face, interpolated) from the clumps.
   - Smooth chain weights with blends at the shoulder, elbow and wrist.
2. **Fur re-skin.**
   - All 112 + 55 left-arm clumps, plus 23 body clumps on the arm, are skinned **rigidly**: one weight set per clump, taken at its root on the bone chain.
   - 234 leftover finger-bone weights in the body mesh are remapped to `hand.L`.
   - Rigidity was compared at 0 / 0.35 / 1 (`PHASEC_RIGIDITY`). Per-vertex weights stretch the clumps into bars; rigid tufts keep their shape and part over the underlay.
3. **Articulated left hand.**
   - Built with Blender's **Skin modifier + Subdivision** around a hand skeleton: a palm, a knuckle bar, 4 fingers × 3 segments and a 3-segment thumb.
   - Laid out in a punch fist (knuckles forward, back of the hand up), fitted to the Tripo fist's measured box.
   - 1,752 faces, 100% quads, closed (no boundary edges).
   - `hand.L` and the 15 finger bones are re-placed inside it, so the rest pose is the fist.
   - Weights: inverse distance to bone segments, two influences.
   - Tripo's mitten (`part_6`) is hidden and kept.
4. **Poses** (actions, exported as clips):
   - `hand_fist`, `hand_open`, `hand_point`, `hand_grip`;
   - `hand_knuckle_support`;
   - `elbow_000` / `elbow_060` / `elbow_120`;
   - `forearm_squash_stretch` (forearm scale Y 1.15 / XZ 0.93, hand counter-scaled).
5. **Corrective `elbowBend_L`** (the Pose Shape Keys method, scripted):
   - Pose the elbow at 120° and find the vertices that come closer to the posed bone chain than at rest.
   - Push them back out, capped at 25 mm and one offset per clump.
   - Store the offset in rest space through the inverse of each vertex's blended bone rotation.
   - Lives on the underlay and both fur parts.
   - Driven in the app by `ui/src/avatar/correctives.ts`: weight = smoothstep((bend − 70°) / 50°), measured from the posed bones every frame. Models without the morph skip it.
6. **Gesture.** `talk_gest_open_palms` now opens the left hand between 34% and 78% of the clip; B2's retarget left the fingers still.
7. **Deep brows** (`part_17`, the F3 brow stripe):
   - **Bones** `brow.L` / `brow.R` (children of `head`) carry the brow stripe for clip animation. The weights fade out before the lids.
   - **7 new morphs** beside F3's five: `browInnerUp_L/R`, `browOuterUp_L/R`, `browDown_L/R`, `browSqueeze` (the furrow).
   - **App acting** (`acting.ts`):
     - every cue now drives the per-side brows: curious, skeptical, sympathetic and surprised are asymmetric, and thinking adds a squeeze;
     - new cues: **worried** ("uh-oh", "due tomorrow", "deadline", "overdue": fits to-do reminders) and **focused** ("let's do this", "lock in");
     - V1 keeps working because unknown morphs are ignored and every cue still sets the old shared brow keys.
   - **Brow beats** (`face.ts`): while talking, a loud onset (a stressed syllable) lifts the brows for about 0.3 s, alternating both / left outer / right inner, at most once every 0.7 s.
   - Vitest covers both.

## Results
**Fidelity vs hero B** (regional IoU, locked camera; B2 → C1):

| Region | B2 | C1 |
|---|---|---|
| Overall | 0.886 | **0.889** |
| Forearms | 0.788 | **0.836** |
| Hands | 0.832 | **0.904** |
| Upper arms | 0.937 | 0.931 |
| Head, shoulders, torso, hips, legs | (unchanged) | ± 0.003 |

- The articulated fist matches the approved hero image better than Tripo's mitten.
- Vs Tripo neutral (front / side / ¾ overall): 0.992 / 0.985 / 0.990. The differences are the hand shape (hands 0.87–0.98); upper arms are 1.00.

**Deformation** (`phase_c/evidence/sheet_poses_vs_B2.png`, `sheet_elbow_corrective.png`):
- **Hand:** B2 cannot open its hand; rotating its finger bones drags the forearm fur. C1 opens, points and grips cleanly.
- **Elbow at 60–120°:** C1's forearm keeps its volume (rigid tufts over the underlay); B2 crushes the forearm fur against the upper arm.
- **Corrective:** `elbowBend_L` adds up to 28 mm at the inner crease: real but modest. Most of the gain comes from the re-skin.
- **Knuckle support and squash/stretch:** clean in C1.
- **Known limit:** at a fully straight elbow (`elbow_000`, beyond any V1 clip; rest is 48°) the tufts at the outer elbow part enough to show a gap.

**Topology** (`phase_c/topology.json`):

| | Faces | Quads | Open edges | Non-manifold edges | Max influences |
|---|---|---|---|---|---|
| C1 hand | 1,752 | 100% | 0 | **16** (Skin-modifier junctions at the knuckle bar) | 2 |
| C1 underlay | 256 | 100% | 2 end loops (shoulder and wrist, hidden inside body and hand) | 0 | 2 |
| Tripo fist (`part_6`) | 716 | 0% | 17 holes | 0 | 4 |

**Runtime** (`phase_c/runtime.json`, GLB B2 → C1):
- Draw calls 43 → 44;
- vertices 28,049 → 29,712 (+5.9%);
- morph slots 111 → 121;
- file size 7.18 → 7.40 MB;
- clips 5 → 14 (9 single-frame pose clips).

**Complexity:**
- About 600 lines of builder.
- About 60 lines of app code: the corrective driver, brow cues and brow beats.
- Repeatable from B2 in about 2 minutes headless.

**App:** the virtual-time recording is in `renders/phase_c_C1/` (see PROGRESS.md for the probe numbers).

## Tools evaluated
- **RetopoFlow:** GUI only, so it can't run headless here. Kept for an interactive pass when a local Blender session exists.
- **Blender native, scripted:**
  - the Skin modifier + Subdivision built the hand (all quads, closed);
  - Data Transfer gave the underlay the fur's UVs.
- **Pose Shape Keys:** its method (solve at a pose, store in rest space through the skinning inverse) is implemented in `elbow_corrective`; the add-on itself needs the GUI.
- **Easy Weight:** its jobs (clean up weights, remove stray groups, limit influences) are done by script: rigid clumps, finger groups remapped, 2 influences.

## Decision (Phase D gate)
**C1 meets the gate on fidelity:** hero forearms and hands go up, and nothing drops by more than 0.006. It is clearly better on hand articulation and on elbow volume at 60–120°.

**Recommendation: expand to the right arm (mirror), with three fixes first:**
1. Merge the knuckle-bar junction (a voxel remesh of the palm only, then re-weight) to remove the 16 non-manifold edges.
2. Project Tripo's fist texture onto the hand (the F3 muzzle grid bake); today it is a flat tone.
3. Widen the underlay at the outer elbow for straight-arm poses.

Legs and hips are not worth rebuilding yet: their fidelity gap is pose and perspective, the same in Tripo's source.

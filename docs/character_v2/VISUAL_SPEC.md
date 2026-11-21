# Monkey V2: before/after modeling spec

Sources:
- `references/01_TARGET.png` (the target illustration, sha256 `78b6a8d3…`);
- `references/02_CURRENT.png` (sha256 `ecd05377…`);
- renders of the production model `ui/public/models/monkey.glb` (sha256 `e9f02358…`), made with `tools/character_v2/render_views.py`.

The reference images stay local in `character_v2_workspace/refs/` and are not committed.

**Not used:** the zedshape Sketchfab sculpture is marked NoAI, so it was neither downloaded nor referenced.

## How to read this
- The target is **one illustration**: a ¾ view in perspective, in a crouched knuckle stance. Proportions below are estimated against the head, which is the least foreshortened part.
- **The crouch is the illustration's pose, not the rest pose.** V2 keeps the production rest pose and skeleton, so every clip still fits.
- Uncertainty:
  - *measured*: read off our own renders;
  - *estimated*: read off the target with roughly ±15 %;
  - *style*: a design call with no number.
- Units: model space, Z up, faces -Y, feet at z = 0, about 1.0 tall. Head bone at z 0.60, eyes at z 0.743.

## Head and face

| Feature | Current (measured) | Target (estimated) | V2 direction |
|---|---|---|---|
| Muzzle | Small, flush with the face; the mouth decal sits on a nearly flat front (y ≈ -0.242) | Big, wide, rounded snout. It projects about 0.35–0.45 head-widths in front of the eyes and runs from under the eyes to the chin | Project it +0.07 to +0.10 and widen it +15–22 %. Keep it **under** the eyes. Make it a dome with a soft rim, not a bump |
| Brow | Thin brow decals on a smooth forehead | Heavy brow ridge shading the eyes; a stern, confident default | Add a ridge of +0.02 to +0.03 forward and slightly down. Keep the existing `browsAngry`/`browsSad`/`browsUp` keys working on top of it |
| Eyes | Very large glossy "anime" eyes, about 0.14 wide each | Smaller, set deeper under the brow, about 55–65 % of the current size | **Stage 2.** The Eyes mesh carries `blink_L/R`, `happyEyes`, `angryEyes`, `sadEyes`, `wideEyes` and `squint`, so the eyelid keys have to be rebuilt with it. Untouched in Stage 1 |
| Nose | No distinct nose | Broad nostrils at the top of the muzzle | Add a small bump in Stage 1; real nostril forms in Stage 2 |
| Mouth | Decal mouth with 15 visemes and jaw/smile keys | Wide smiling mouth across the muzzle | Keep the decal and every key. They ride on the muzzle (the keys are carried along and bounded to ×0.8–1.35) |
| Crest | Three spikes plus fur tufts | Taller swept-back tuft crest | Longer tufts (axial ×1.25 to ×1.6) |
| Ears | Round, pink inner | Similar, a little smaller relative to the head | Unchanged |
| Headset/mic | Gold headband, cyan mic ball | The same headset | Must stay stable. The mic boom rides the muzzle field, so it sits on the new snout side |

## Body and silhouette

| Feature | Current (measured) | Target (estimated) | V2 direction |
|---|---|---|---|
| Shoulders/trapezius | Rounded, about 1.6 head-widths across | Massive, about 2.2–2.5 head-widths across; the head sits low between the shoulders | Radial ×1.15 to ×1.4 around the shoulder and upper-arm bones. Stage 2: trapezius mass and a lower head |
| Forearms | Slightly wider toward the wrist | Huge "Popeye" forearms, the biggest mass of the arm | A uniform-thickness bulge that peaks mid-forearm and eases off at the wrist. A bigger radial scale would turn the existing wrist bulb into a disc |
| Hands | Small 3-finger hands with thumbs, about 0.10 long | Huge fists, about 1.6–1.8× the current size; knuckles take the weight in the crouch | Scale the whole hand subtree ×1.28 to ×1.55 about the wrist (geometry plus the 18 hand, finger and thumb bones) |
| Chest | Defined pecs and abs (tan) | Fuller pecs, a big barrel chest | Pecs +0.01 to +0.018 forward; chest radial ×1.08–1.12 (B) |
| Legs | Short, straight | Short, thick, bowed | Thigh and shin radial ×1.06 to ×1.18 |
| Fur | Brown, short cards | Orange-red, long shaggy fur, with a silhouette of fur clumps on the arms and back | **Stage 3.** The existing cards are kept and move with the body |
| Colour | Dark brown and tan | Warm orange-red and peach-tan | Stage 3 (materials) |

## Must not change
- Bone names, hierarchy, and rest pose outside the hand subtree.
- Mesh names, vertex counts and face topology. In V1 and Stage 1, every runtime shape key is indexed by vertex.
- Shape key names and order: the 15 visemes, the face/eye/brow keys and the body keys.
- The 37 clip names and their channels.
- Vertex groups.
- The headset and mic stay attached and visible.
- The production GLB is never replaced during these stages.

# ADR 001: Rebuild Monkey V2 from the Tripo export with a hybrid face (strategy C)

**Status:** accepted for the next stage; reversible. **Date:** 2026-11-21.

## Context
The owner prefers the Tripo model's design to candidate B, which was still V1 with bulges. Tripo becomes the visual authority; V1 stays the authority for behaviour: 15 visemes, 38 face morph names, 5 body morphs, 37 clips and the app's face mixer.

The audit (`TRIPO_AUDIT.md`) shows:
- Tripo's **look** is strong: silhouette, fur clumps, colours, crest, headset, brow ridge.
- Its **face mechanics** are not usable as is:
  - the mouth is sculpted open (a hole with painted teeth);
  - the eyes are painted shells with no lids;
  - every part is triangle soup with no deformation loops.

## Options tested (same day, same cameras)

| Option | What was built | Result |
|---|---|---|
| **A0: direct Tripo** (control) | Jaw, lip-seal and smile fields applied straight to Tripo's muzzle and mouth strips (`tripo_face_poc.py --mode direct`) | `viseme_aa` barely reads (the mouth is already open); **`viseme_PP` can't seal the lips**; painted teeth and eyes smear; no blink is possible. `renders/T2_A0_vs_C.png` |
| **B: wrap V1 topology onto Tripo** | Not built | Rejected on the audit alone. Tripo's fur is hundreds of separate clump shells, so a single V1 surface wrapped onto it would lose the look the owner chose. That's the B-v005 failure mode again |
| **A: full Tripo retopology** | Not built this run | Still needed later, but only for regions that deform: shoulders, elbows, hands. The fur clumps should stay as skinned shells. A full retopo of the face alone gives the same as C, and needs a GUI retopo tool for quality |
| **C: hybrid** | Tripo body, fur, crest, ears, headset, mic and brow kept; **new muzzle** (concentric lip loops fitted to Tripo's surface and coloured from Tripo's own texture) with lip roll, cavity, teeth and tongue; **new eyeballs with lids**; brow keys on Tripo's brow | Closed neutral mouth; `aa`, `O`, `E`, `FF`, `PP`; blink, wink plus smirk, happy, angry and sad. **Driven by the real app in Three.js** (`renders/threejs_C/`, `T3_threejs_face.png`). Still reads as Tripo at body and face scale (`T2_body_matched.png`) |

## Decision
**C, the hybrid.** Next steps in order:
1. Face to production quality: sculpt pass on the procedural shapes, plus eye gaze.
2. Hands and shoulders: targeted retopology of the deforming regions (the A technique, applied locally).
3. Fitting V1's skeleton semantics and clips to Tripo proportions.

The face is built so that every morph the app names exists. Topology may differ from V1, so candidates are checked in `contract.check_functional` mode, not `compare`.

## Consequences
- Production assets later: Tripo textures (39 materials) should be atlased. The new parts add 5 materials.
- The muzzle colour is a planar projection of Tripo's texture. It's softer on the steep sides; a proper bake to a real UV layout is a Stage 4 item.
- Clips: Tripo's skeleton is Mixamo, so V1's 37 clips don't play on it yet (0 clips in the proof of concept). Retargeting, or refitting V1's skeleton, is Stage 3/5 work and is required before release.

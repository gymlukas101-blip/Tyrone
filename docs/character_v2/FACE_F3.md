# Monkey V2: E6 eye polish and the integrated face F3

**Status:** F3 is the face candidate for review: the E6 eyes, Tripo's brow and a lip-loop muzzle with a mouth, on one Tripo character. Body and clips are not started.
**Run:** cloud container: Blender 5.3 (bpy, headless), and the branch's own UI build in headless Chromium (SwiftShader). Not tested on Windows / WebView2 / GPU.

## E6: eye polish on the approved E5 geometry (`tools/character_v2/tripo_eyes.py`)
E5's topology (fitted eyeball, one sealed lid and socket mesh per eye, the tuck rim) is unchanged. What changed, against your notes:

| Your note | E6 change |
|---|---|
| Sclera too bright and too exposed | The lid margin sits 0.9 mm (lower) to 2.0 mm (upper) inside Tripo's opening: a heavier, more intense lid, like the source. The sclera is Tripo's measured cream × 0.85, darkening toward the edge of the eyeball (socket depth). Eyeball roughness is 0.3, so the app's environment light gives a soft sheen, not a mirror |
| Uneven lid edges, lower-lid smudge in squint/happy | The lid UVs are re-laid: the dark lash line lives only on the folded rim, so stretched lids stay clean skin. A soft crease runs on the upper lid. The contour is smoothed more |
| Painted highlight | Tripo's painted highlight is removed from the iris (refilled from the surrounding iris). A small glossy catchlight cap is fixed to the **head** on the key-light side, so the iris turns under it like a real reflection, and the lids cover it when they close |
| Lid follow + head follow | The lid loops near the margin take 12–42% of the eye bone's rotation, so the lids follow gaze in the app with no code. The app's look-at (`ui/src/avatar/life.ts`) maps `head`/`neck`/`chest`/`root`/hands to Mixamo bones, so the head and neck now follow the cursor on Tripo's skeleton (measured: head 18°, neck 12°, eyes 20°) |
| Expressions too similar | Stronger, distinct lid shapes: squint (smiling lower lid), happyEyes, angryEyes (heavy lid, inner corner pulled down), sadEyes (inner corner lifted), wideEyes. The brow keys are separate (F3) |
| Independent blinks | The app gained `winkEye(side)` and a `wink` event (`ui/src/avatar3d.ts`, `ui/src/main.ts`): it eases in and out over the ordinary blink, which carries on. Measured in the app: `blink_L` 1, `blink_R` 0 |

Checks:
- Leaks: **unverified.** The run reported 0 background or skull leak pixels (7 neutral views + 16 poses), but the test
  could not fail: AgX rendered the magenta background as (201, 116, 201), which the detector rejects. Back faces were
  drawn too, so an opening into the skull interior wouldn't have read as magenta anyway. Fixed in `eye_audit.py` /
  `eye_poses.py` on 2026-11-25. F3 was not re-run; for the current eyes see `EYES_E7.md`.
- Eyeballs: 0 open and 0 non-manifold edges.
- Sheets: `G1` (Tripo / E5 / E6 / F3 neutral, 7 matched views) and `G2` (16 eye poses: half blink, blink, wink, squint, happy, angry, sad, surprised, 4 gaze directions, blink while looking aside, squint while looking up).

## F3: the face on one character (`tools/character_v2/tripo_face_v2.py`)
- **Eyes:** E6.
- **Brows (Tripo's `part_17`):**
  - a slightly relaxed neutral (inner brows eased up 2.5 mm), so the resting face is friendly, not a scowl;
  - strong keys `browsUp`, `browsAngry` (past Tripo's scowl), `browsSad`, `browUp_L`/`R`;
  - the brow stripe moves, while the skin over the lids stays put (no pale gaps).
- **Muzzle and mouth:**
  - **Geometry:** the lip-loop muzzle (concentric loops around a closed lip line, projected onto Tripo's real muzzle, skirt, lip roll, cavity, teeth, tongue).
  - **Texture:** now a **transfer bake** onto a regular grid UV layout (u = around the mouth, v = ring); each texel is sampled at the nearest point of Tripo's own surface, so the steep sides are sharp. Tripo's open-mouth paint is masked and refilled from the lips, plus a soft lip crease.
  - **Mood gains:** the smile and frown gains are up (×1.8 / ×1.7) for the broad muzzle.
- **Morphs:** 38 face morphs under V1's names. These are the 15 visemes plus `jawOpen`, `smile`, `bigGrin`, `frown`, `smirk_L`/`R`, `mouthO`, `grimace`, `tongueOut`, `cheekPuff`, `cheeksUp`, the 7 eye keys and the 5 brow keys. GLB default weights are all 0.

### Evidence
| Sheet / file | What it shows |
|---|---|
| `G3_F3_face_blender_{front,three_quarter_L}.png` | Blender: neutral; happy / angry / sad / surprised / laugh exactly as the app mixes them; aa, O, E, FF, PP (sealed), U; smile + aa, sad + O, squint + E, wink + smirk, jaw + cheeks, surprise + O, talking while looking left, smirking while looking right |
| `G4_F3_threejs_states.png` + `threejs_F3/threejs_report.json` | **The app** (this branch's UI, `?demo&model=`): speech aa/PP/O/E/FF and barge-in reset; blink; **wink L**; happy, angry, sad, surprised; smiling while talking; sad while talking; gaze in 4 directions; talking while looking aside. The morph weights and eye-bone angles are read back from the live meshes |
| `perf_F3/performance.mp4` (2 min 23 s) + `G5_F3_performance_beats.png` | **A recorded performance in the app:** cursor tracking (head + eyes), a spoken line (28 viseme frames), the line again while smiling with a wink mid-sentence, again while sad and frowning, then angry, surprised and laugh reactions, a right wink, a blink, back to neutral. Every frame is a real screencast frame at its own timestamp |

The software renderer runs a few fps, so the video is slower and choppier than on a GPU. Some key-frame stills catch a frame before the lids move. The read-back weights in the reports are authoritative.

## Open issues
1. **Muzzle rim:** a thin outline shows where the new muzzle meets Tripo's head. It needs a weld or a blend strip in a GUI pass.
2. **Mouth corners:** the procedural mouth shapes read well but are first passes. A sculpt pass on the smile corners, the O roundness and the cheek bulge would lift them.
3. **Emote expressions don't end by themselves:** with no body clips, the app's emote preset never finishes, so the test scripts clear it. That's fixed once clips exist (Stage 3).
4. **Lighting:** the app's ACES tone mapping and lighting make every cream surface paler than in Blender (the muzzle too), so it needs a look-dev pass in the app.
5. **Catchlight:** the left and right catchlights share one light direction; the strength is a starting value.
6. **Untested:** Windows/GPU frame time; real TTS audio (synthetic viseme frames were used); the overlay window.

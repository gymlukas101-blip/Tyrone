# Monkey V2 eyes E7: animatable iris, pupil and catchlights

**Status:** candidate on `feature/monkey-character-v2` (not in production). Built on the C4 clips blend.
**Tool:** `tools/character_v2/eyes_e7.py` (headless Blender 5.3) → `character_v2_workspace/eyes_e7/tripo_E7.{blend,glb}`.

## Why
E6 had Tripo's iris and pupil **painted onto the eyeball**. The eyes could turn and the lids could move, but the
pupil couldn't change size, the iris couldn't react, and both catchlights were one fixed shape. E7 rebuilds them as
separate parts the app animates, while keeping the reference look.

## What's built (per eye)
| Part | Build | Animation |
|---|---|---|
| Sclera | E6 eyeball (geometry, `eye.L/R` bone) with the iris painted out: Tripo's cream sclera (measured, socket shading divided out) and E6's back/socket shading | turns with the eye bone |
| Iris + pupil | `V2_Iris_L/R`: a polar cap (48 × 12 rings) conformed to the eyeball along Tripo's measured iris axis, domed 0.35 mm like a cornea. Pupil = its own faces + glossy black `V2_Pupil`; iris = disc-UV texture from Tripo's radial iris paint (both eyes averaged, saturation ×1.35 toward the reference art), lighter near the pupil, a dark limbal ring and fine radial fibres | shape keys `pupilDilate`, `pupilConstrict`, `irisBig`, `irisSmall`; turns with the eye bone |
| Catchlights | `V2_EyeCatchlight_L/R`, fixed to the head: a big one up-right of the pupil and a small one low-left (as in the reference), placed from each eye's iris axis toward one shared key-light direction | `eyeSparkle` (×1.55) |
| Lids | E6 sock kept | new per-side copies of the expression keys: `squint_L/R`, `wideEyes_L/R`, `happyEyes_L/R`, `angryEyes_L/R`, `sadEyes_L/R` |

Measured on Tripo's paint: iris ≈ 36° (angular radius on a 43 mm eyeball), pupil = 64% of the iris. One iris size
for both eyes. Stack heights over the eyeball: iris 0.18–0.53 mm < catchlights 0.62 mm < lid margin 0.7 mm, so the
lids slide over everything and a blink still seals (0 leak pixels in all 16 poses).

## App (this branch's UI)
- `face.ts`: pupils are one signed size (dilate − constrict) with a slow irregular flutter (hippus, ±0.07), so the eyes
  never look frozen; the two keys are never on at once.
- `acting.ts` cues + state rests and `avatar3d.ts` emote presets drive them: listening → slightly dilated; thinking →
  slightly tight + right eye narrowed; happy/warm/excited → dilated + sparkle; sad/sympathetic → big wet "puppy" eyes;
  surprised / wake startle → pinpoint (irisSmall + pupilConstrict); angry/focused → tight; skeptical → one eye narrowed.
  Older models ignore the unknown morphs.
- Read back in the app: neutral pupilDilate 0.02 (flutter); happy dilate 0.30 + sparkle 0.59; sad dilate 0.50 + sparkle
  0.51; surprised constrict 0.67 + irisSmall 0.51; angry constrict 0.43. 46 clips load.

## Evidence (`character_v2_workspace/eyes_e7/`)
- `E7_vs_reference.png`: reference art / E6 / E7 neutral / happy sparkle / shock.
- `E7_poses_closeup_L.png`, `E7_poses_front.png`: 16 poses (dilate, constrict, big cute, pinpoint, sparkle, one-eye
  squint/wide, angry, sad, blinks, gaze in 4 directions with pupil changes).
- `E7_app_eyes.png` + `threejs/threejs_report.json`: the real app.

## Open
- The happyEyes lower lid still tears slightly at 0.5 (an E6 sock issue, needs the sculpt pass in `EYES_E5.md` §6).
- Catchlight strength and the sclera tone need a look-dev pass under the app's lighting on a GPU.

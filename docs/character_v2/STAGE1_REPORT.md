# Monkey V2, Stage 1: blockout candidates and compatibility report

**Status:** two editable candidates. Both pass validation. **Recommended: B ("bold")**, open issues below.
Nothing was replaced or merged. The production `ui/public/models/monkey.glb` still has sha256 `e9f02358…1012`, and `validate.py` checks that on every run.

## What was built

A non-destructive, topology-preserving reshape of the frozen baseline `.blend` (`tools/character_v2/blockout.py`). Every vertex keeps its index, and every shape key keeps its name, order and meaning.

| Region | A · measured | B · bold (closest to the target) |
|---|---|---|
| Muzzle | +0.065 forward, +14 % wider, dome profile | +0.105 forward, +22 % wider, taller under the mouth, short above it (stays under the eyes) |
| Nose / brow ridge | +0.02 / +0.018 | +0.03 / +0.03 |
| Shoulders / upper arms | radial ×1.15–1.2 / ×1.18–1.22 | ×1.3–1.4 / ×1.28–1.35 |
| Forearms | ×1.08–1.1 plus a 16 mm bulge | ×1.12–1.15 plus a 30 mm bulge (Popeye) |
| Hands | ×1.28 about the wrist | ×1.55 about the wrist |
| Chest / pecs | pecs +10 mm | chest ×1.08–1.12, pecs +18 mm |
| Legs | ×1.06–1.08 | ×1.12–1.18 |
| Crest tufts | ×1.25 long | ×1.6 long |
| Vertices moved | Body 13,528 · Head 423 · Mouth 967 · Brows 568 · Headset (mic) 370 · FurCards 2,958 · Tufts 699 | Body 14,745 · Head 641 · Mouth 967 · Brows 568 · Headset (mic) 387 · FurCards 3,710 · Tufts 699 |
| Largest move | 0.065 (muzzle) | 0.105 (muzzle) |

Unchanged in both: **Ears and Eyes** (0 vertices moved). The eyes are Stage 2 work: see `VISUAL_SPEC.md`.

## Evidence (local files in `character_v2_workspace/renders/`)

All renders use fixed orthographic cameras, so the rows line up exactly. Faces are neutral: every key at 0 and the clip actions detached.

| File | Shows |
|---|---|
| `V2_stage1_body_clay.png` / `_tex.png` | Front, ¾, side and back: baseline, A, B |
| `V2_stage1_face.png` | Face front and ¾ |
| `V2_stage1_vs_target.png` | Target illustration, baseline, B |
| `V2_stage1_expression.png` | `jawOpen` + `viseme_aa` + `smile` 0.6 + `blink_L` + `cheeksUp` 0.5, on all three |
| `V2_stage1_flex.png` | The `flex` clip at frame 20 (skinning and the bigger hands in a real pose) |
| `V2_stage1_fur.png` | The fur cards follow the new arms (baseline vs B) |

Earlier iterations (`cand_*_001`–`004`, `cmp_00*`) are kept for the record. Each version fixed something visible:
- **001:** muzzle too timid.
- **002:** B's muzzle covered the eyes.
- **003:** the muzzle touched the chest (ripples), fixed by separating the head and body fields.
- **004:** forearm bell, then a disc, fixed with the offset bulge.
- **005:** exaggerated keys and exporter vertex splits, both fixed.

## Compatibility (validate.py, Blender 5.3.0, cloud container)

| Check | A v005 | B v005 |
|---|---|---|
| Production GLB hash unchanged | ✅ | ✅ |
| Bones: same 57 names and parents | ✅ | ✅ |
| Rest pose unchanged outside the hand subtree | ✅ (18 hand, finger and thumb bones scaled about the wrist) | ✅ (same 18) |
| Meshes: same 9; same vertex counts, face topology and vertex groups | ✅ | ✅ |
| Shape keys: same 50, same order, all still move | ✅ | ✅ |
| Key size within ×0.5–2.5 (blockout bounds it to ×0.8–1.35) | ✅ max ×1.35 (`jawOpen`, `bigGrin`) | ✅ max ×1.35 (`Brows/browsSad`, `Mouth/smile`, `smirk_L`) |
| 15 visemes | ✅ | ✅ |
| 37 clips, same names | ✅ | ✅ |
| GLB export → re-import (production exporter settings) | ✅ 44,110 vertices, the production count (an untouched baseline gives 44,216) | ✅ 44,110 |
| Export path is never the production model | ✅ (`character_v2_workspace/validation/`) | ✅ |

The keys that change size do so on purpose: they follow the bigger shape.
- `bicepFlex` grows with the arm (×1.2 / ×1.32).
- The brow keys sit on the new ridge (≤ ×1.35).
- B's mouth keys ride the bigger muzzle (≤ ×1.35).

Lip-sync timing and viseme choice are untouched (same names, same clips). Only the size of the mouth shapes changes, by at most 35 %.

**What this does not prove:**
- No Three.js/app render of a candidate: the production model isn't replaced, so the app hasn't seen them.
- No Windows test.
- No full clip-by-clip review: only `flex` and `talk_gest_open_palms` were rendered.

## Recommendation: B

B moves furthest toward the target and still passes every runtime check:
- the snout projects;
- the forearms are a rounded Popeye mass;
- the hands are about 1.55× bigger;
- the shoulders and chest are wider.

A is the safe fallback if B reads as too much in the app.

### Open issues (for B, in priority order)
1. **Eyes are still the V1 anime eyes.** This is the biggest remaining difference from the target. Stage 2: smaller, deeper eyes under the brow, with the 7 eyelid/eye keys rebuilt.
2. **The muzzle surface is slightly lumpy at the rim** in ¾ view: the head is low-poly there (3,575 vertices). Stage 2 needs a retopologised muzzle region, or a smoothing pass applied equally to the basis and the keys.
3. **The mouth decal now sits on the snout tip.** In ¾ view with `jawOpen`, the far mouth corner is partly hidden behind the muzzle. Check it in Three.js with real lip-sync before choosing B for production.
4. **Hands in the `flex` pose come close to the head** (bigger fists, same clip). It's acceptable in the renders, but the clip may need a small retarget later.
5. **The mic ball sits on the side of the snout.** It's attached and stable, but the boom may want to be shortened in Stage 2.
6. **Shoulders and trapezius aren't yet the target's mass,** and the head doesn't sit low between the shoulders. That's Stage 2 (it touches the neck and head bones).
7. **Fur colour and length:** Stage 3.

### Next single action
Load `monkey_v2_cand_B_005.glb` (from `character_v2_workspace/validation/`) in the UI's `?demo` mode on a local branch. Check it with real lip-sync and the idle and gesture clips in Three.js, never replacing `ui/public/models/monkey.glb` on `main`. Then start Stage 2 with the eyes.

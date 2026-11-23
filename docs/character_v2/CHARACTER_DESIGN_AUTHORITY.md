# Monkey V2: Character Design Authority

The construction specification every V2 model change is checked against.
- **Measured** = read from `MonkeyTripo.glb` / candidate B2 (`tools/character_v2/measure_character.py`, `logs/measure_B2.json`).
- **Estimated** = read from the approved illustrations; target ranges, not exact values.

Model units: height H = 0.980 (feet at z 0, Z up, faces −Y; _L = +X = the character's left).

## 1. Artistic overview
Monkey is a powerful, friendly cartoon gorilla, a smart assistant with a mischievous grin.
- **Proportions:** a big head sits low between massive, fur-draped shoulders. Long, heavy arms end in enormous cream fists that rest at floor level. The legs are short and bowed, with broad cream feet.
- **Face:** a broad cream muzzle that projects far, intense green eyes under a heavy brow, and a swept copper crest.
- **Accessories:** a gold-and-black headset with a mic boom at the mouth corner.
- **Body:** a cream heart-shaped chest plate with sculpted abs.
- **Fur:** rich copper-red, in layered, pointed clumps with darker roots and lighter tips.
- **Rendering:** soft, rounded and toy-like, with gentle sheen on the fur and matte cream skin.
- **Acting:** rubbery, weighty and fast in reaction.

## 2. Reference precedence

| Source | Authority for | File (sha256, first 8) |
|---|---|---|
| Hero image A (thumbs-up) and B (crouch) | **Artistic intent:** appearance, silhouette, expression, rendering | `04_HERO_IMAGE_B_CROUCH.png` (`17a498e1`); A appears in the sheets |
| Turnaround | Front/side/back anatomy, proportions, accessory placement | `05_TURNAROUND.png` (`83fa7bed`) |
| Exploded assembly | Component identification, attachment regions, hand articulation | `03_EXPLODED_ASSEMBLY.png` (`4f3c1d19`) |
| `MonkeyTripo.glb` | **Measurable 3D shape**, hidden surfaces, textures, part relations | `8f990a33` |
| F3 / V1 animation system | **Function:** visemes, facial acting, skeleton behaviour, app integration | F3 `504c4373`, V1 `e9f02358` |

### Conflicts and resolutions

| Conflict | Resolution |
|---|---|
| Hero B shows an **open grin**; F3's neutral face has a closed mouth | Expression, not anatomy: the grin is a performable state (`smile` + `jawOpen`/`bigGrin`). The neutral stays closed so speech can seal (P/B/M) |
| Hero A stands **upright with a thumbs-up**; hero B and Tripo **crouch** | Different poses, not different anatomy. The rest stance is Tripo's (fists hanging by the sides, as in the turnaround front). The thumbs-up needs an articulated hand (Phase C) |
| The turnaround shows a **standing** pose with fists at mid-thigh; Tripo's fists reach the floor | Tripo's arms are long; their resting angle is a pose choice. **Unresolved:** whether the standing idle should lift the fists off the floor (turnaround) or keep knuckle contact (hero B). Validate in Phase C with both poses |
| The exploded diagram shows **separate limbs, cups and sockets** | Illustrative only: production keeps one skinned body plus separate accessories (headset, cups, mic, eyes). Disconnected limbs are **not** to be built |
| Exploded and hero A: a **thumb and separable fingers**; Tripo: closed mittens | The art direction wins: articulated digits are required (Phase C). The silhouette must keep Tripo's massive fist |
| Headset **ear cups** sit over the ears (exploded) vs Tripo's cups below and in front of the ears | Tripo's placement is measured and kept. **Unresolved** for a later accessory pass |

## 3. Proportions (measured on the GLB rest pose unless marked)

| Measure | Value | Normalised |
|---|---|---|
| Overall height × width × depth | 0.980 × 0.973 × 0.556 | width = 0.99 H |
| Head region (head + neck weights, incl. crest and headset) w × d × h | 0.447 × 0.416 × 0.518 | head h = 0.53 H (crest top z 0.98, chin ≈ z 0.53) |
| Crest (`part_8`) | 0.286 × 0.286 × 0.247 | 0.25 H tall |
| Muzzle (`part_9`) w × d × h | 0.271 wide, 0.156 deep, 0.183 tall | projects 0.10 in front of the eyes |
| Eyes (E6 fit) | centres (±0.053, −0.106, 0.727); eyeball r 0.043; opening r 0.024–0.041 | eye centre at 0.74 H |
| Shoulder joints span | 0.475 (shoulder fur region 0.660 wide) | 1.06 × head width |
| Upper arm length / forearm length (joints) | 0.250 / 0.291 | the forearm is longer than the upper arm, a gorilla trait |
| Arm fur thickness (upper arm region, depth) | 0.37 | — |
| Fist (`part_3`/`6`) w × d × h | 0.211 × 0.210 × 0.175 | fist width = 0.47 × head width |
| Torso + chest region | 0.395 × 0.436 × 0.508 | chest plates 0.18–0.21 wide each, 0.30 tall |
| Hip width (thigh joints) | 0.176 | — |
| Thigh / shin length (joints) | 0.092 / 0.129 | legs ≈ 0.37 H with fur |
| Foot (`part_5`/`11`) w × d × h | 0.213 × 0.205–0.226 × 0.08 | — |
| Headset band + cup (`part_7`) | 0.264 × 0.138 × 0.250 | — |
| Mic boom (`part_21`) | 0.161 × 0.228 × 0.122 | tip at the mouth corner |

**Illustration estimates** (hero B, perspective, about ±10%):
- head ≈ 0.45 H;
- fists ≈ 0.5 × head width, sitting slightly further out and lower than Tripo's;
- feet more visible between the fists.

The fidelity loop below measures these differences instead of guessing them.

## 4. Construction and part inventory (back → front)

| Part | Source | Rig region | Deforms? | Reuse Tripo? | Rebuild? | Own animation |
|---|---|---|---|---|---|---|
| Body skin + fur clumps (`part_0`), arm fur (`part_1`/`2`) | Tripo | skinned to the whole skeleton | yes: shoulders, elbows, hips | clumps yes | shoulder, elbow and wrist underlay: **Phase C** | fur follow-through (Phase E) |
| Crest (`part_8`, tufts 13/15/31/32) | Tripo | head | rigid + secondary | yes | — | tuft springs (needs bones) |
| Ears (`part_4`/`10`) | Tripo | head | rigid | yes | — | ear springs (needs bones) |
| Headset band and cups (`part_7`/`14`/`34`/`36`), mic (`part_21`) | Tripo | head | rigid | yes | mic tip placement (later) | mic boom spring (needs bone) |
| Brow ridge (`part_17`) | Tripo + F3 keys | head | morphs | yes | — | 5 brow keys |
| Eyes, lids, socket | **F3/E6 rebuilt** | `eye.L`/`eye.R` + head | bones + morphs | — | done | gaze, 7 lid keys |
| Muzzle, lips, teeth, tongue | **F3 rebuilt** | head | morphs (+ jaw rotation in keys) | — | done; seam weld later | 15 visemes + 11 moods |
| Chest plates (`part_19`/`23`) | Tripo | chest | follows the chest | yes | — | chestPuff (to add) |
| Fists (`part_3`/`6`) | Tripo mittens | hand | **wrong**: no digits | silhouette yes | **articulated hands: Phase C** | fist, open, point, grip, knuckle support |
| Feet (`part_5`/`11`, toes) | Tripo | foot/toe | yes | yes | — | contact/IK later |

## 5. Colour and material palette (sRGB)
**Albedo** = the Tripo texture median (`measure_character.py`, over the texels each part uses). **Appearance** = hero B pixels (lit and tone-mapped, `logs/hero_palette.json`), not albedo.

| Element | Tripo albedo (median / dark 15% / light 85%) | Hero B appearance |
|---|---|---|
| Copper fur, body | #823210 / #431604 roots / #d77636 tips | arm #ae461c, shoulder #983a17 |
| Crest | #9b4118 / #5a1f08 / #d87936 | #73290f (mid-shadow) |
| Muzzle cream | #c08146 (F3 bake) | #fddfa7 |
| Brow mask cream | #be864c | — |
| Brows (brown stripe) | in `part_17` texture | #85300e |
| Chest plate cream | #c1925d / #cca169 | #edc88e |
| Fists / hands | #bb7539 / #e5ab67 light | #d89950 |
| Feet | #b37039 | — |
| Iris green | painted eye, sRGB about 0.29/0.46/0.18 (#4a752e) | #365631 |
| Sclera (E6 material) | 0.75/0.71/0.66 after dim | — |
| Inner ear | ear light #eca557 | #fadaab |
| Headset gold / dark parts | light #eac958; band median #5b3e1e | #c69932 |
| Mic boom / tip | #372c1e / — | tip #d5f4f1 (pale mint) |
| Teeth / mouth interior | F3: #f2edde-ish / dark red 0.22/0.04/0.05 | open mouth: pink tongue |

**Materials:**
- Fur: rough (0.6–0.8) with sheen; the app adds a fur sheen to Body/Fur/Tuft/Head materials.
- Cream skin: matte (roughness 0.6). The hero's skin reads lighter and pinker than Tripo's albedo because of soft lighting and tone mapping; match the app look under its ACES lighting, not raw albedo.
- Eyes: roughness 0.3 with a head-fixed catchlight.
- No emissive materials except that catchlight.

## 6. Rigging and animation requirements

| Need | Where | Status |
|---|---|---|
| Bone-driven body (V1 semantic names) | Tripo deform skeleton renamed: `hips, spine, spine_mid, chest, neck, head, shoulder/upper_arm/forearm/hand.L/R, thigh/shin/foot/toe.L/R, f1–f4/thumb.01–03` | **done (B2)** |
| Clips | 37 V1 clips, retargeted relative to V1's idle stance | **5 done:** idle, listen, think, talk, talk_gest_open_palms |
| Face morphs + visemes | F3 (38 names) | done |
| Eye + head tracking | `eye.L`/`eye.R` + `head`/`neck` (app look-at) | done |
| Finger articulation | f1–f4 + thumb bones exist; the mesh is a mitten | **Phase C** |
| IK/FK | foot and knuckle contact for the crouch and gestures | Phase C/E |
| Squash and stretch | V1 clips' bone scale is transferred; volume-preserving spine/chest | partly (inherits V1) |
| Secondary motion | crest tufts, ears, mic boom (springs need bones Tripo lacks) | Phase E |
| Fur follow-through | clump lag on the arms | Phase E |
| Emote cleanup | app: clip-independent expression timeout | **done** |

## 7. Uncertainties and validation needed

| Item | Kind | Validate by |
|---|---|---|
| Standing idle fist height (floor contact vs mid-thigh) | conflict | Phase C pose test in the app with the owner |
| Finger count (Tripo rig: 4 + thumb; the art reads 3–4) | estimate | the hand prototype from exploded/hero A |
| Hidden fist interior and palm shape | unseen geometry | rebuilt in Phase C; check against the hero A thumbs-up |
| Back fur flow under the headset band | unseen in hero | turnaround back view comparison |
| Exact iris hue (the hero is lit; Tripo is painted) | appearance vs albedo | look-dev in the app |
| Hero perspective (≈ 55 mm lens, 16° elevation, calibrated) | estimate | locked calibration (§8); recalibrate only if the reference changes |

## 8. Visual fidelity loop (`tools/character_v2/fidelity_render.py` + `fidelity.py`)
- **Reference silhouette:** green key, then the largest component, then small enclosed holes filled. The green irises are filled; the real gaps between arm, body and leg stay open.
- **Camera:** calibrated once (lens, elevation, 2D similarity) and then **locked**: `fidelity/HERO_B_LOCKED_{camera,calibration}.json`.
  - An early lens choice cropped the forearms out of frame; it was rejected **before** locking.
  - Neutral anatomy uses fixed orthographic cameras with identity registration.
- **Region labels:** from each vertex's strongest bone. Reference pixels the candidate misses are assigned to the nearest candidate region.
- **Outputs:** overall and regional IoU, ranked discrepancies, overlay, heat map, side-by-side, and projected joint landmarks.

### First results
| Comparison | Overall | Head | Up. arms | Forearms | Hands | Hips | Legs | Feet |
|---|---|---|---|---|---|---|---|---|
| Tripo source vs hero B | 0.886 | 0.906 | 0.937 | 0.788 | 0.832 | 0.738 | 0.841 | 0.679 |
| F3 / B2 rest / B2 idle vs hero B | 0.886 | 0.906 | 0.937 | 0.788 | 0.832 | 0.738 | 0.841 | 0.679 |
| B1 idle (V1 stance) vs hero B | 0.740 | 0.906 | 0.704 | 0.572 | 0.492 | 0.719 | 0.861 | 0.400 |
| B2 vs Tripo, neutral front / ¾ / side | 1.000 / 1.000 / 0.997 | 1.0 / 1.0 / 0.988 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

- **Bounded improvement:** B1 → B2 (motion retargeted relative to V1's idle stance, so Tripo keeps his own stance) raises the overall IoU **0.740 → 0.886** (hands 0.49 → 0.83) with no animation loss. All 5 clips play in the app.
- **Remaining gap:** feet, hips and forearms differ from the hero **in Tripo's own source**, from the illustration's pose and perspective. These are the ranked targets for the Phase C arm and hand prototype, not reasons to warp geometry.

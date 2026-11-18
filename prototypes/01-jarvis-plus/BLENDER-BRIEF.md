# Blender brief: Monkey "Jarvis+" (chosen design)

**What to build.** A rigged, animated real-time model of design **#01 Jarvis+**, exported as **`monkey.glb`**. It replaces `ui/public/models/monkey.glb` in the Monkey app. Name the export `monkey.glb`.

**Hard requirement.** The app drives the model by **names**: animation clips, shape keys, and glow material names. Everything in §6–§8 must match **exactly**. If it does, the new model drops in with zero code changes.

**References, in this folder:**
| File | Use it for |
|---|---|
| `sheet.png` | Front, side and back A-pose views: the **primary modeling reference** |
| `hero.png` | Personality, materials and lighting target: the flex pose, fur clumps, glow |
| `../reference/current-3d.png` and the current `ui/public/models/monkey.glb` | The existing rig. Keep its skeleton names and clip set |

---

## 1. Scale and proportions

The scene unit is metres, with +Z up in Blender (glTF export converts to +Y up). The character stands at the origin, faces −Y (Blender front view), and the feet sit on Z = 0.

| Measure | Value | Notes |
|---|---|---|
| Height, sole to top of skull | **1.00 m** | Hair spikes add about +0.10 m on top |
| Head height, chin to skull top | **0.33 m** | About **3.0 heads** tall. The sheet reads closer to 3.6; the hero reads 3.0. Use 3.0 so the face stays big for lip sync |
| Head width without ears | 0.36 m | Nearly round, slightly wider than tall |
| Ear disc diameter | 0.13 m | Set at eye height, angled about 15° forward |
| Shoulder width at the deltoids | **0.70 m** | The widest point of the body |
| Chest width at the pecs | 0.56 m | |
| Waist width | **0.33 m** | Strong V-taper, about 0.47 of the shoulder width |
| Hip width | 0.40 m | |
| Arm, shoulder pivot to fist centre | 0.56 m | Hands hang to about mid-thigh in the A-pose |
| Upper arm / forearm max diameter | 0.15 / **0.19 m** | **Forearms are bigger than upper arms** (Popeye) |
| Fist / open hand | 0.14 m fist, 0.17 m long open hand | Chunky mitten hands: 3 fingers + thumb |
| Leg, crotch to sole | 0.25 m | Short stubby legs |
| Foot length | 0.17 m | Cream sole and toes, 4 rounded toes |
| Tail | 0.50 m total, from the base of the spine | Rises up and out to the character's left, ending in a 1.5-turn spiral about 0.14 m across |

**Silhouette test.** At 64 px tall, filled solid black, it must read as: round head with round ears and three spikes, huge shoulders, tiny waist, short legs, spiral tail.

## 2. Shapes and details

- **Head**
  - A sphere slightly flattened at the jaw, with no neck visible from the front.
  - The **peanut-shaped face mask** is two overlapping eye lobes plus a wide muzzle, in cream. It covers about 60% of the face.
- **Brows**
  - Thick, soft, rounded dark-fur ridges. Separate mesh `Brows`, driven by the brow bones and shape keys.
  - The resting expression is **calm, not angry**: soft curves, no V-shape.
- **Eyes**
  - Huge glossy black spheres, about **0.085 m diameter** each, sitting close together. No visible white sclera.
  - Each has a thin **cyan ring (#33E1FF)** around the iris, about 5% of the eye radius, as an emissive material.
  - Two white specular highlight discs on each eye: a big one upper-left (about 30% of the eye) and a small one lower-right (about 12%). These can be geometry with an emissive white material (`M_Highlight`).
  - Skin-coloured upper lids, used for blinks, stay hidden at rest.
- **Nose:** two small dark nostril dots on the upper muzzle. No protruding nose.
- **Mouth**
  - Wide (about 0.16 m when smiling), set low on the muzzle.
  - Interior: dark red-brown cavity, an upper row of teeth, and a pink tongue as a separate mesh.
  - Resting expression: a closed, friendly smile.
- **Ears:** round discs with a **pink inner (#F08A8A)** and fur-coloured outer rim.
- **Hair:** **3 large spikes** in the centre (tallest in the middle, about 0.10 m) plus 2 small side spikes. These are solid sculpted shapes, not strands.
- **Body fur**
  - Read as **large leaf-shaped clumps**: tufts sculpted into the surface and normal map at the shoulders, upper arms, forearms (pointing toward the elbow), calves and the back.
  - **No hair particles, no strands.** The regenerated model sheet is the target; the first try was too shaggy.
- **Cream areas:** chest plate with two big rounded pecs, an **8-pack** (4 rows × 2), cream down to the belly, cream hands and feet, plus the face mask and inner ears.
- **Headset**
  - A banana-yellow band over the top of the head, behind the hair spikes.
  - Round ear cups: yellow outer, dark grey ring.
  - A **boom mic** from the character's **left** ear cup (viewer's right), curving forward to the right corner of the mouth.
  - The mic tip is a small sphere in **glowing cyan**.
- **Tail:** smooth, fur-coloured, slightly thicker at the base, tapering to the spiral.

## 3. Colours and materials (sampled from the sheet)

| Material (keep these names) | Base colour | Notes |
|---|---|---|
| `M_Body` | `#8B3F1D` fur brown | Sheen (colour `#FFD9A6`, roughness 0.45). Normal map for clumps. Roughness about 0.75 |
| `M_FurPlain` | `#8B3F1D` | Tail, ears outer. No clump normals |
| `M_Tuft` | `#8B3F1D`, tips `#AD7253` | Hair spikes |
| `M_Brow` | `#5F2A12` dark fur | |
| `M_Head` | Cream `#EBCFA1`, shading to `#DFA870` | Face mask, chest, hands, feet. Same as the belly |
| `M_EarInner` | `#F08A8A` | |
| `M_Eye` | `#0B0B10` | Clearcoat 1.0, roughness 0.05 |
| **`M_GlowEye`** | Black base, **emissive #33E1FF, strength 3** | Iris rings. **The name must contain "Glow"**, because the app animates it |
| `M_Highlight` | White, emissive 1.5 | Eye highlights |
| `M_Headset` | `#FFC928` banana yellow; cups ring `#2B2B2B` | Clearcoat 0.3 |
| **`M_GlowLED`** | **Emissive #33E1FF, strength 3** | Mic tip. **The name must contain "Glow"** |
| `M_Mouth` / `M_Teeth` / `M_Tongue` | `#5A1A1A` / `#FFF8EC` / `#F08497` | |

Textures: at most 2K, PBR metal/rough, sRGB base colour. Keep the export under **10 MB**; the current one is 7.3 MB.

## 4. Mesh and topology

- **Separate meshes,** matching the current model: `Body`, `Head`, `Eyes`, `Mouth` (cavity, teeth, tongue), `Brows`, `Ears`, `Headset`, `Tufts`.
- **Budget:** about **30k triangles** total. The head and face get about 40%.
- **Topology:**
  - All quads, with clean edge loops around the eyes, the muzzle and **the mouth**: 3–4 concentric loops plus a jaw loop, for visemes.
  - Elbow, knee, shoulder and hip loops for deformation.
- **Shading:** apply Shade Auto Smooth. Weighted normals on the headset.
- **UVs:** one UV set, no overlaps on baked areas. Normals face outward. **Apply all transforms** before export.

## 5. Rig: keep the existing 57-bone skeleton

Rebuild or retarget onto **exactly these bone names** (from the current `monkey.glb`), so existing and future animation code still matches:

```
root, hips, spine, chest, neck, head, brow.L, brow.R, ear.L, ear.R, eye.L, eye.R, headset, mic_boom,
tuft.1, tuft.2, tuft.3,
shoulder.L, upper_arm.L, forearm.L, hand.L, f1.01.L, f1.02.L, f2.01.L, f2.02.L, f3.01.L, f3.02.L, thumb.01.L, thumb.02.L,
shoulder.R, upper_arm.R, forearm.R, hand.R, f1.01.R, f1.02.R, f2.01.R, f2.02.R, f3.01.R, f3.02.R, thumb.01.R, thumb.02.R,
tail.01, tail.02, tail.03, tail.04, tail.05, tail.06, tail.07, tail.08,
thigh.L, shin.L, foot.L, toe.L, thigh.R, shin.R, foot.R, toe.R
```

- **Root and head:** `root` sits at the floor between the feet. `head` pivots at the base of the skull.
- **Eyes:** `eye.L` and `eye.R` sit at the eye-sphere centres, for look-at.
- **Tail:** `tail.01`–`08` follow the curve, with the spiral in `.06`–`.08`.
- **Weights:**
  - Normalized, at most 4 influences per vertex.
  - Rigid parts are 100% weighted: the headset to `headset`, the mic to `mic_boom`, each spike to its `tuft.*`.
- **Deformation tests:** check the flex pose (both arms up, as in `hero.png`), arms down, a squat, and a 45° head turn. Look for no collapsing at the shoulders or elbows.

## 6. Shape keys: exact names

Mouth and face shape keys go on the meshes they deform. If a key exists on several meshes (e.g. `smile` on Head and Mouth), use the **same name on each**; the app drives them together. Values run 0–1, with the full expression at 1.

- **Visemes (Oculus/Meta set, on `Mouth`, plus `Head` where the muzzle moves):** `viseme_sil, viseme_PP, viseme_FF, viseme_TH, viseme_DD, viseme_kk, viseme_CH, viseme_SS, viseme_nn, viseme_RR, viseme_aa, viseme_E, viseme_I, viseme_O, viseme_U`
- **Mouth:** `smile, bigGrin, frown, smirk_L, smirk_R, mouthO, grimace, tongueOut`
- **Head:** `cheekPuff, cheeksUp, jawOpen, smile, bigGrin`
- **Eyes:** `blink_L, blink_R, happyEyes, angryEyes, sadEyes, wideEyes, squint`. Note: the app no longer uses `happyEyes` because the old version looked half-closed and "dead". Keep the key, but make it a gentle upward lid curve, not a half-close.
- **Brows:** `browsUp, browsAngry, browsSad, browUp_L, browUp_R`
- **Body:** `chestPuff, pecBounce_L, pecBounce_R, bicepFlex_L, bicepFlex_R`

**Viseme sculpting notes:**

| Viseme | Mouth shape |
|---|---|
| `aa` | Jaw open about 60%, tongue low |
| `O` | Round, jaw 40% |
| `U` | Small round pucker |
| `E` | Wide, jaw 30% |
| `I` | Wide, jaw 15%, teeth visible |
| `PP` | Lips pressed |
| `FF` | Lower lip under the upper teeth |
| `TH` | Tongue tip between the teeth |
| `SS` | Teeth together, lips apart |
| `CH` | Lips forward, teeth together |
| `kk`, `DD`, `nn` | Jaw 20%, tongue up |
| `RR` | Slight pucker |
| `sil` | Neutral, closed |

## 7. Animations: exact clip names (12 Actions, pushed down as NLA strips)

| Clip | Length | Loop | Content |
|---|---|---|---|
| `idle` | 4 s | yes | Breathing (chest 2%), slight weight shift, tail sway, occasional ear twitch |
| `listen` | 3 s | yes | Lean in 5°, head tilt about 8°, one hand near the ear cup, brows up a bit |
| `think` | 3 s | yes | Right fist to chin, eyes up-right, slow tail curl |
| `talk` | 2 s | yes | Upper-body beats and hand gestures. **No mouth keys** (lip sync is live) |
| `happy` | 2 s | no | Bounce on the toes, arms open, chest puff |
| `laugh` | 2 s | no | Lean back, shoulders shake, hand on belly |
| `sad` | 3 s | no | Slump, head down, arms hang |
| `angry` | 2 s | no | Fists clenched, chest forward, stomp |
| `surprised` | 1.5 s | no | Jump back 3 cm, hands up, ears perk |
| `wave` | 2 s | no | Right-hand wave above the head. The hand must clear the head |
| `flex` | 2 s | no | **Hero pose:** double-bicep flex with `bicepFlex_L/R` and `pecBounce` shape keys |
| `dance` | 4 s | no | 120 BPM groove: hips, arms, tail swing |

- Each clip starts and ends near the `idle` pose, because the app crossfades over 0.3 s.
- Keep root motion in place. No translation of `root` beyond a few cm.
- Don't key shape keys inside `talk`.

## 8. Export (File → Export → glTF 2.0)

- **Format:** glTF Binary `.glb`, **+Y Up** on.
- **Include:** selected objects plus armature only, no cameras or lights.
- **Mesh:** Apply Modifiers on, UVs and Normals on, vertex colours off.
- **Shape Keys** on, with Shape Key Normals on.
- **Skinning** on. Bone influences: 4.
- **Animation:**
  - Mode: Actions/NLA. Export all 12 named actions.
  - "Always sample animations" on, at 30 fps.
  - Optimize animation size on.
- **Materials:** export. Ensure `KHR_materials_emissive_strength`, `sheen` and `clearcoat` are written.
- **Images:** JPEG for base colour, PNG for normal maps.

## 9. Acceptance checks (run before handing back)

1. **The file loads in Monkey.** Drop it in as `ui/public/models/monkey.glb` and run the UI. The app's test hook must show **12 clips** and all **15 `viseme_*`** shape keys. This is the same headless check I ran on the current model.
2. **Glow:**
   - The cyan rings and mic tip brighten and dim with state (idle → listening pulse → thinking pulse → talking).
   - Nothing else glows.
   - The background stays transparent: no bloom is needed in the app.
3. **Lip sync:** with Monkey talking, the mouth visibly forms open, round and wide shapes, and the teeth and tongue don't poke through the muzzle.
4. **Framing:** the app frames the camera by model height, so keep the bind pose upright with arms in an A-pose. A T-pose makes him render too small.
5. **Size and performance:** at most 10 MB, about 30k triangles, and 60 fps in the app on an integrated GPU.
6. **Originality check:** compare the silhouette and props against the reference list in `../REFERENCES.md`. No necktie, no glasses with armor, no headband with hand wraps.

# Monkey V2 mouth M1: mouth bag, teeth, gums, tongue and wider open shapes

**Status:** candidate on `feature/monkey-character-v2` (not in production). Built on the E7 eyes blend (C4 clips + E7).
**Tool:** `tools/character_v2/mouth_m1.py` (headless Blender 5.3) → `character_v2_workspace/mouth_m1/tripo_M1.{blend,glb}`
and `tripo_M1_report.json`.
**Run:** cloud container: Blender 5.3 (bpy, headless) and the branch's UI build in headless Chromium (SwiftShader).
Not tested on Windows / WebView2 / a GPU.

## Why
F3's mouth was a first pass. It opened to a thin slit, the teeth were flat double-sided slabs, the tongue was a squashed UV
sphere and the cavity was 5 thin rings with one flat dark material. The reference art (`refs/01_TARGET.png`) shows an
open, friendly grin with a big pink tongue in a dark mouth. The owner asked for a mouth "as high quality as the monkey
model", using Donkey Kong Bananza and other cartoony game characters as style references.

## Research: how stylized game characters build mouths
Method: web searches only. Fetching the pages themselves was blocked by this session's network policy (gamesradar.com and
mariowiki.com refused), so the points below come from the search results' summaries of those pages, plus general knowledge
of widely published cartoon game characters. No reference image was downloaded or copied, nothing was traced, and no
character's geometry or likeness was recreated. The "zedshape" DK model was not used.

| Source | What it says that matters here |
|---|---|
| [Miyamoto on the Bananza redesign (GamesRadar)](https://www.gamesradar.com/games/donkey-kong/donkey-kong-creator-shigeru-miyamoto-explains-the-big-apes-redesign-was-all-in-service-of-making-him-more-expressive) | The redesign went back to the Rare-era design and asked how to make it **more expressive**; the face is the point |
| [Ask the Developer Vol. 19: Donkey Kong Bananza (Nintendo)](https://www.nintendo.com/sg/news/article/7s4qWP1oLR3CbacuKDLtuH), [summary (MarioWiki)](https://www.mariowiki.com/Ask_the_Developer_Vol._19:_Donkey_Kong_Bananza) | The team got detailed input on body frame and **facial expressions**; he looks very large on screen, so his expressions had to read at a distance |
| [Kevin Bayliss on the Bananza design (OpenCritic)](https://opencritic.com/news/15127/bananza-s-donkey-kong-design-gets-approval-from-dkcs-original-artist), [design notes (Nintendo Soup)](https://nintendosoup.com/donkey-kongs-character-design-in-bananza-was-inspired-by-miyamotos-original-design/) | "His face is way more expressive now"; rounder facial features, pre-DKC (Miyamoto) roots |
| [Tooth Strip (TV Tropes)](https://www.tvtropes.org/pmwiki/pmwiki.php/Main/ToothStrip) | Cartoons usually draw teeth as **one strip**, switching to a few individual teeth only when the teeth carry the expression; in 3D, a strip mapped to look like a row |
| [Learning Blender: Teeth and Tongue (O'Reilly)](https://www.oreilly.com/library/view/learning-blender-a/9780133886283/ch07lev2sec28.html) | Stylized teeth are "two curved surfaces with thickness" and the tongue a basic shape, styled like the rest of the character |
| [Pixar paper (graphics.pixar.com)](https://graphics.pixar.com/library/DFF/paper.pdf), [darkening a mouth (80.lv)](https://80.lv/articles/see-how-3d-animator-darkened-this-character-s-mouth) | The inner mouth is kept **stylized and fairly dark**, which sidesteps interior-lighting problems; artists darken it to match the scene |
| [Mouths from different angles (80.lv)](https://80.lv/articles/pixar-animator-shows-how-3d-character-mouths-look-from-different-angles), [Modeling the Mouth Area (Autodesk)](https://download.autodesk.com/global/docs/softimage2014/en_us/files/face_modeling_ModelingtheMouthArea.htm) | The interior must be fully modelled because it deforms a lot and shows from many angles: a mouth bag, not a decal |
| [Teeth, gums and mouth interior (Tripo blog)](https://www.tripo3d.ai/blog/explore/hd-model-teeth-gums-and-mouth-interior-detail) | Gums and tongue are wet, slightly translucent surfaces: softer and glossier than skin |
| [Ratchet & Clank: Rift Apart animation (PlayStation Blog)](https://blog.playstation.com/?p=352844), [Blender Studio stylized character course](https://studio.blender.org/training/stylized-character-workflow/) | Game faces are acted from a pose library; stylized pipelines build the mouth bag, teeth and tongue after the face |

### Design traits taken (not geometry)
- **Width:** cartoon-ape grins run across most of the muzzle, and the corners curl up into the cheeks. The reference grin
  spans about 80% of Monkey's muzzle.
- **Lips:** thick and rolled, the upper lip overhanging, the lower lip heavy. The inner lip shows as a darker rose band
  when the mouth opens.
- **Teeth:** one smooth upper band (the "tooth strip"), with individual teeth only hinted. The gums are mostly hidden. A
  smaller lower row, or none, as in the reference art.
- **Tongue:** big, wide and rounded, with a shallow centre groove. It fills the floor of the mouth and comes forward in a
  grin. It is the most visible thing in the reference's open mouth.
- **Interior:** stylized and dark, maroon fading to near-black at the throat, the roof a little pinker than the floor.
- **Corners:** they pinch; the middle opens and the corners stay sealed, which gives an oval or crescent, never a box.

### Does it fit Monkey's style?
**Yes.** The reference art is already in this idiom: a crescent grin, a heavy upper lip, a big pink tongue and a dark
interior. What was adapted, and what was not taken:
- **Kept Monkey's own forms.** The muzzle's outer surface and its transfer-baked Tripo texture are untouched. All shapes are
  derived from Tripo's measured muzzle (lip line, recessed lower lip, chin underside) and the reference art, not from any
  other character.
- **Teeth stay secondary.** The reference shows almost no teeth, so the ivory band sits set back behind the upper lip. It
  shows only when the lip lifts (grin, laugh, E, TH), and it is ivory, not paper white. The gums appear only in a grimace.
- **The neutral stays closed.** The app needs a sealed PP, and the design authority says the grin is a performable state.
- **Softness matches the Tripo look.** Squircle sections, rounded tooth ends, a smooth tongue with a subtle groove, and no
  sharp detail that would fight the soft, toy-like rendering.

## What was built (per part)
| Part | Build | Motion |
|---|---|---|
| Mouth bag (`V2_Muzzle`, material `V2_MouthBag`) | F3's 5 thin inner rings + tip are replaced, in the same mesh (no seam), by a 3-ring **lip roll** and a 6-ring **sack + throat pole**. The first roll ring overlaps 0.4 mm behind the 1 mm lip slit, so a closed mouth has no line of sight inside. Cheek pockets are wider than the lip line, the roof is high, and the lower half is narrower to clear Tripo's thin, recessed lower lip. Muzzle: 1625 verts, manifold (only the skirt's outer ring is open, as before), consistent winding, every bag normal facing the cavity. 128² baked gradient: dusky rose inner lip → maroon → near-black throat, roof +16%, floor −12% | the roll follows the lips; the bag blends from the roll's motion to a deep jaw field (the floor rotates with the jaw, a little less toward the throat) |
| Upper teeth (`V2_TeethUpper`, `V2_Teeth`) | one ivory band: a squircle tube swept on a horseshoe arc, closed rounded ends, a slightly convex front, 8 hinted teeth (scalloped biting edge + faint grooves), the edge rising toward the sides. 668 verts, closed, single-sided | head-fixed |
| Lower teeth (`V2_TeethLower`) | smaller band (15 mm), set back behind the lower lip | rides the jaw |
| Gums (`V2_GumUpper/Lower`, `V2_Gums`) | rounded tubes the teeth sit in; their roots sink into the roof and floor | upper fixed, lower rides the jaw |
| Tongue (`V2_Tongue`, `V2_Tongue` material) | a 26 × 24 subdivided rounded slab: a rounded tip in plan and section, a 2.6 mm centre groove that fades at tip and root, a domed middle, and a thicker root sunk into the floor; gradient texture (pink tip → darker root, darker underside). 626 verts, closed | jaw field + its own keys (below) |

**Jaw.** The hinge moved from 13 cm behind the lip and 5 cm above it to a jaw-joint position (y −0.02, z 0.628). The
lower lip now **drops** instead of swinging back under the upper lip. jawOpen = 13.5°. The lower muzzle rides the jaw as
one piece: the lip corners stay pinched, the cheeks blend over a wider band further out, and the falloff ends at the
muzzle rim. Horizontal lip moves (wide, smile, frown, cheeks up) **slide on Tripo's surface**: front rays, clamped to
±15 mm, zero where a ray misses. The smile's lift reaches further up the cheek than down the chin. That fixes F3's
upper-lip fold next to the corners: 40 flipped faces in F3's laugh, 0 in M1 apart from F3's degenerate skirt faces.

**Keys:** the same 62 morph names as E7 (identical set), all default weights 0, 46 clips.
- The 26 mouth keys are rebuilt on every moving part: muzzle, tongue, lower teeth, lower gum.
- Tongue helpers:
  - `tongueOut`: forward 5 cm over the lower lip, widened, flattened and drooping at the tip.
  - `viseme_TH`: tip forward and up between the teeth.
  - `DD`/`nn` (and part of `CH`/`SS`/`RR`): tip up to the ridge behind the upper teeth.
  - `kk`: tip down, back of the tongue up.
  - `aa`/`O` (and part of `E`/`jawOpen`/`mouthO`): the tongue lies low.
  - `bigGrin`: the tongue rides forward and up.

## Evidence (`character_v2_workspace/mouth_m1/`)
| File | What it shows |
|---|---|
| `M1_before_after_face.png`, `M1_before_after_mouth.png` | Blender, before (E7) vs after (M1), front + 3/4: neutral, jawOpen, aa, O, E, PP, TH, bigGrin, laugh (bigGrin + squint 0.7 + cheeksUp 0.9, the app's mix), tongueOut, smile + aa, surprised (mouthO + wideEyes + browsUp) |
| `poses_after/poses.json`, `poses_before/poses.json` | 19 poses × 4 views (front, 3/4, side, low): hole test, foreign geometry, interior outside the lips, visible mouth/teeth/tongue pixels (`tools/character_v2/mouth_poses.py`) |
| `M1_app_mouth_sheet.png` | **The real app**, E7 vs M1: speech aa/PP/O/E/FF, smile + aa, jawOpen, bigGrin, laugh emote, tongueOut, mouthO, surprised, happy, with the morph weights read back from the live meshes |
| `app_face/threejs_report.json`, `app_clips/clips.json` | app face check (62 morphs) and all clips |
| `tripo_M1_report.json` | topology, per-pose numeric checks (32 poses incl. speech/mood combos), moves > 45 mm, GLB contents |

### Numbers
- **Leak test** (magenta background, only the muzzle and mouth parts rendered, back faces culled): **0 magenta pixels
  inside the mouth** in all 76 renders (19 poses × 4 views). **0 foreign pixels**: nothing of Tripo's head shows inside
  the mouth. Same for E7.
- **Visible mouth, front, 360 px** (bag + teeth + tongue pixels), E7 → M1. Open shapes show 1.3–2.1× more mouth. The
  tongue reads in every open shape, and it no longer pokes through the teeth in TH (E7's did).

  | Pose | Mouth px | Teeth px | Tongue px |
  |---|---|---|---|
  | jawOpen | 5234 → 9548 | | 1066 → 2678 |
  | aa | 4535 → 7495 | | |
  | bigGrin | 3998 → 8085 | 2006 → 2678 | 156 → 1673 |
  | laugh | 4096 → 8318 | | 148 → 1636 |
  | tongueOut | 3824 → 7874 | | |
  | smile + aa | 5381 → 8474 | | |
  | E | 2655 → 4069 | | |
  | O | 3515 → 4634 | | |
  | surprised | 3352 → 4814 | | |

- **Lip gap at the centre** (mm), E7 → M1: jawOpen 29 → 51, aa 25 → 40, bigGrin and laugh 15 → 34, mouthO 23 → 35,
  O 23 → 32, E 13 → 20, tongueOut 16 → 24. PP is still sealed at 0.6 mm. Mouth width: bigGrin 178 mm (66% of the
  muzzle), laugh 182 mm.
- **Closed mouth:** teeth visible through the lips, neutral/PP front: E7 137 px (a 1 px line through the slit) → M1 0.
- **Pokes** (`tripo_M1_report.json` → `checks`): over 32 poses, 0 bag faces seen through the skin from the front.
  The flesh between bag and skin is ≥ 3.8 mm in every pose. Interior pixels outside the lips: ≤ 13 in every pose and
  view except tongueOut (where the tongue is meant to be out).
- **Cost:** mouth parts 1703 → 4403 vertices. GLB 10.2 → 11.3 MB (morph deltas on the jaw-riding parts). +2 draw
  calls (the two gums); the muzzle keeps its two materials and F3's teeth and tongue were replaced one for one.
- **App:** the M1 GLB loads in this branch's UI. 62 morphs; 46 clips play with 0 page errors and none missing. The face
  check drives speech, emotes, laugh, bigGrin, jawOpen, tongueOut and mouthO through the app's own mixer. The only console
  error is the same favicon 404 as the E7 run.
- **Tests:** `pytest tests/test_character_v2_fidelity.py` 5 passed; `vitest` 52 passed; `tsc --noEmit` clean.

## Open issues (honest)
1. **Under the chin at full jaw:** a few skirt faces (rows 14–17) crease where the rotating chin meets the fixed skirt.
   This is visible only from below. A wider falloff folds the skirt instead (its rings nearly coincide), and pinning the
   skirt folds the underside, so it needs the muzzle-rim weld (F3 open issue 1) or a real jaw bone.
2. **No jaw bone.** The jaw is a rotation baked into morphs, so combined opens add rotations linearly. The chord error at
   the largest app combination (about 20°) is a few mm. The lower teeth and gum carry 26 morph targets each for what is a
   rigid rotation. A `jaw` bone driven by the mixer would be cheaper and exact, but needs an app change.
3. **By design, inside the flesh:** the gum roots sit in the roof and floor; the lips press on the teeth in PP and FF; the
   tongue root sinks into the floor. None of this is visible in any of the 76 test renders.
4. **The radial bag test** flags one bag vertex near a lip corner in I, nn and laugh (a grazing ray). The face-level and
   render tests show nothing there.
5. **Corner sculpt:** the far corner of the 3/4 grin still has a slight notch where the procedural smile meets the cheek
   (F3 open issue 2 remains: the corners, the O roundness and the cheek bulge want a sculpt pass).
6. **Look-dev:** the Workbench sheets use studio light. In the app (ACES), the teeth read whiter and the inner lip pinker.
   The tooth ivory, gum and bag colours need a look on the Dell's GPU.
7. **Style choice to confirm with the owner:** M1 shows the upper tooth band in grins and E/TH. The reference art shows
   almost none. Showing less tooth is a two-line change (`upper_up` in `bigGrin`/`VIS`).
8. **Untested:** Windows / WebView2 / GPU frame time with +2.7k vertices and +2 draw calls; real TTS audio.
9. **Found on the way (eyes, not fixed here):** `tools/character_v2/eye_poses.py` checks for magenta with the blends'
   AgX view transform, under which the magenta background renders as (201, 116, 201), so its leak test can't fail. The
   E5–E7 "0 leak pixels" results are therefore unverified. `mouth_poses.py` forces the Standard transform; the eye test
   needs the same fix and a re-run. **2026-11-25:** fixed in `eye_poses.py` and `eye_audit.py`, and shown to fail on a
   throwaway scene. The counts on `tripo_M1.blend` are still to measure (`EYES_E7.md`).

# Toy-block background concepts for Monkey

*2026-11-24, branch `feature/blocky-backgrounds`.* The owner asked for "potential background images for Monkey with
all 3D animatable Blender assets in a Roblox cartoon style". This is the **style** only: chunky bevelled blocks,
toy-like low-poly shapes, bright simple plastic materials and soft light, in Monkey's jungle palette. Everything is
**original and procedural**: no logos, characters, fonts, textures or assets from Roblox or any other game, and no
copy of any game's level. It matches the toy-block icons already in the app (`docs/ui/BLOCKY_ICONS.md`).

Nothing in the app changes. These scripts only make concept stills, preview videos and glTF files.

## Outputs (not in git)

Everything lands in `character_v2_workspace/backgrounds/` (local only; add `character_v2_workspace/` to
`.git/info/exclude` if your checkout doesn't ignore it). Never commit these binaries to the public repo.

| File | What |
|---|---|
| `contact_sheet.png` | All scenes side by side: still on top, the same still with Monkey's silhouette below |
| `<scene>/<scene>_still.png` | 1080x1800 still (3:5 portrait), Cycles |
| `<scene>/<scene>_still_monkey.png` | The still with the real avatar's silhouette (idle pose, same camera) where he stands |
| `<scene>/<scene>_loop.mp4` | 4 s seamless loop, 540x900, 24 fps (H.264); play it on repeat |
| `<scene>/<scene>.glb` | Whole scene with every clip (plus the camera `BG_Camera`) |
| `<scene>/<scene>_app.glb` | Same scene, app-ready: vertex colours + merged static set (see "Using one in the app") |
| `<scene>/assets/<Asset>.glb` | Each asset on its own, at its own pivot, with its own clip, to mix later |
| `<scene>/<scene>.blend` | The Blender scene (Blender 5.3) |
| `<scene>/manifest.json` | Asset list, placements, triangles, sizes, timings |
| `<scene>/frames/` | The loop's 96 PNG frames (frame 96 = frame 0, so it is left out) |
| `glb_report.json` | `check_glb.py --json`: every glb's clips, durations, seams, triangles, draw calls |

## Rebuild

```bash
python -m venv ~/bpyenv && ~/bpyenv/bin/pip install bpy==5.3.0        # headless Blender as a module
PY=~/bpyenv/bin/python
OUT=character_v2_workspace/backgrounds
$PY tools/backgrounds/build.py -- --scene all --out $OUT               # ~1.5 h on 4 CPU cores (see timings)
for s in sunny_clearing treehouse_sunset waterfall_lagoon night_jungle; do
  $PY tools/backgrounds/app_variant.py -- $OUT/$s/$s.blend             # <scene>_app.glb
done
python tools/backgrounds/sheet.py $OUT                                  # silhouettes + contact sheet (Pillow)
python tools/backgrounds/check_glb.py $OUT --json                       # clips, 4 s durations, loop seams, tris
python tools/backgrounds/report.py $OUT                                 # the tables below, in Markdown
node tools/backgrounds/bench_three.mjs $OUT/sunny_clearing/sunny_clearing_app.glb   # CPU cost in three.js (needs ui/node_modules)
```

Options: `--scene <name>`, `--still-samples 64`, `--video-samples 8`, `--no-still`, `--no-video`, `--layout`
(a 360x600 Cycles preview in ~10 s, for composing) and `--motion` (the whole loop in Workbench at 270x450 in about
20 s, for judging motion). ffmpeg must be on the PATH for the videos.

| Script | What it does |
|---|---|
| `kit.py` | Bevelled boxes, prisms, chunky balls and extruded slabs built in small bmeshes and merged into one mesh per asset; rigs; loop keys; camera, lights, render settings |
| `assets.py` | Every asset builder (trees, palms, vines, bananas, ferns, clouds, sun/moon, stars, butterflies, birds, fireflies, lanterns, water, waterfall, fish, lily pads...) |
| `scenes.py` | The four scene layouts and their own set pieces (deck, hut, trunk, shore, cliffs, canopy sea, hills) |
| `build.py` | Builds a scene, saves the .blend, exports the glbs, renders the still, the loop and Monkey's mask |
| `app_variant.py` | Writes the draw-call-friendly `<scene>_app.glb` |
| `check_glb.py` | Re-reads the glbs without Blender: clip names, durations, first-vs-last-key seam, triangles, draw calls |
| `sheet.py`, `report.py` | Contact sheet and silhouettes; Markdown tables |
| `bench_three.mjs` | Per-frame CPU cost of playing a glb in three.js (mixer + bone updates), no GPU |

## How the scenes are built

- **Monkey's spot:** he stands at the origin, feet on z = 0, facing the camera; 1 unit = 1 m and he is 1.0 m tall
  (measured from `ui/public/models/monkey.glb` in its idle pose). Nothing is placed in the clear zone around and in
  front of him, so the lower-middle of every frame is open.
- **Camera:** 3:5 portrait, 40° vertical field of view, 4.12 m in front of him at 0.85 m height, tilted up 3° so his
  feet sit 14% above the bottom edge and he fills about a third of the height. In three.js (Y up) that is
  `PerspectiveCamera(40, 0.6)` at `(0, 0.85, 4.12)`, which is also exported as the `BG_Camera` node.
- **Style:** flat-shaded bevelled blocks (1 or 2 bevel segments), saturated Principled "plastic" materials
  (roughness 0.4–0.8, low specular), a soft sun (8–10° angle) plus a coloured world light, AgX "Punchy". Skies are a
  vertex-coloured backdrop with a Background shader, which exports as `KHR_materials_unlit` + `COLOR_0`.
- **Animation contract:** every animated asset is **one armature named after the asset + one skinned mesh**
  (`<Asset>_mesh`), and all motion is bone keys, so each asset exports as **exactly one glTF clip with the asset's
  name**. Water surfaces have no armature: two shape keys in quadrature (weights cos/sin of the loop phase) make a
  ripple that travels one wavelength per loop. No drivers, constraints or modifiers other than the armature, so
  everything exports. All clips are 4.0 s (frames 0–96 at 24 fps, frame 96 = frame 0) and use only integer
  frequencies, so they loop without a seam; `kit.loop()` refuses a curve whose end differs from its start, and
  `check_glb.py` re-checks every exported channel.
- **Reproducible:** every random choice comes from a fixed seed per asset, so a rebuild gives the same geometry and
  animation (checked: the glbs match value for value; only the exporter's buffer layout can differ byte for byte).
- **Tricks for things that "travel":** the waterfall's flow blocks and the splash rings wrap round at scale 0 (or
  under the water), so the jump back is invisible; the fish leaps during part of the loop and swims back hidden under
  the opaque water; birds and butterflies fly closed paths with their heading unwrapped (a whole turn is the same
  quaternion); clouds can't cross the sky in 4 s, so they drift on a slow oval and breathe.

## Scenes, assets and numbers

| Scene | Assets (animated) | Triangles | Draw calls | Bones | Scene .glb | Still (1080x1800) | Video frame (540x900) |
|---|---|---|---|---|---|---|---|
| Sunny jungle clearing | 27 (23) | 31,524 | 112 | 215 | 3.23 MB | 128.4 s @ 64 spp | 14.83 s @ 8 spp |
| Treehouse deck at sunset | 24 (17) | 18,972 | 95 | 130 | 1.87 MB | 298.8 s @ 64 spp | 10.73 s @ 8 spp |
| Waterfall lagoon | 22 (18) | 30,228 | 85 | 150 | 2.92 MB | 183.4 s @ 64 spp | 13.87 s @ 8 spp |
| Night jungle | 23 (20) | 26,728 | 90 | 221 | 2.83 MB | 231.5 s @ 64 spp | 9.66 s @ 8 spp |

#### Sunny jungle clearing (`sunny_clearing`)

Midday clearing: blocky trees and palms, hanging vines and banana bunches across the top, ferns and flowers on toy-tile grass, clouds and birds in a bright sky.

| Asset | Animation (4 s loop) | Tris | Rig | .glb |
|---|---|---|---|---|
| SkyBackdrop | static | 256 | - | 12 KB |
| DistantJungle | static | 3,960 | - | 229 KB |
| Ground | static | 4,560 | - | 260 KB |
| Boulders | static | 608 | - | 35 KB |
| Tree_R | trunk sways (3-bone chain + crown, follow-through), 6 leaf blocks flutter at 2x | 1,172 | 10 bones | 144 KB |
| Tree_L | trunk sways (3-bone chain + crown, follow-through), 6 leaf blocks flutter at 2x | 1,172 | 10 bones | 144 KB |
| Tree_BackR | trunk sways (3-bone chain + crown, follow-through), 6 leaf blocks flutter at 2x | 660 | 10 bones | 100 KB |
| Palm_L | trunk sways (4-bone chain), 7 fronds x 3 bones flutter with follow-through | 1,608 | 25 bones | 195 KB |
| Palm_Back | trunk sways (4-bone chain), 7 fronds x 3 bones flutter with follow-through | 1,608 | 25 bones | 196 KB |
| CanopyOverhang | branch bobs; 7 leaf blocks flutter (2x/3x per loop) | 976 | 8 bones | 117 KB |
| Vine_1 | 5-bone chain swings like a pendulum with a travelling lag (side + fore/aft) | 768 | 5 bones | 91 KB |
| Vine_2 | 5-bone chain swings like a pendulum with a travelling lag (side + fore/aft) | 768 | 5 bones | 91 KB |
| Vine_3 | 4-bone chain swings like a pendulum with a travelling lag (side + fore/aft) | 636 | 4 bones | 76 KB |
| BananaBunch_1 | stem pendulum + bunch bobs on a spring (2x) with a small twist | 2,244 | 2 bones | 235 KB |
| BananaBunch_2 | stem pendulum + bunch bobs on a spring (2x) with a small twist | 2,244 | 2 bones | 235 KB |
| Fern_1 | 7 leaves x 2 bones flutter (2x/3x per loop, random phase) | 604 | 15 bones | 81 KB |
| Fern_2 | 7 leaves x 2 bones flutter (2x/3x per loop, random phase) | 604 | 15 bones | 81 KB |
| Fern_3 | 7 leaves x 2 bones flutter (2x/3x per loop, random phase) | 604 | 15 bones | 81 KB |
| Fern_4 | 7 leaves x 2 bones flutter (2x/3x per loop, random phase) | 604 | 15 bones | 81 KB |
| GrassTufts | 18 tufts sway (1 bone each, 2x per loop) | 3,168 | 18 bones | 354 KB |
| Cloud_1 | drifts on a slow oval (side-to-side 0.35 x scale, bob 2x) while its puffs breathe | 540 | 5 bones | 61 KB |
| Cloud_2 | drifts on a slow oval (side-to-side 0.35 x scale, bob 2x) while its puffs breathe | 432 | 4 bones | 49 KB |
| Cloud_3 | drifts on a slow oval (side-to-side 0.35 x scale, bob 2x) while its puffs breathe | 432 | 4 bones | 49 KB |
| Butterfly_1 | flies a figure-8 (body bone) facing its path; wings flap 12x per loop (3 Hz) | 132 | 3 bones | 24 KB |
| Butterfly_2 | flies a figure-8 (body bone) facing its path; wings flap 12x per loop (3 Hz) | 132 | 3 bones | 24 KB |
| Bird_1 | glides a banked oval (body bone, yaw follows the path), two slow flaps then a glide; outer wing follows the inner | 516 | 6 bones | 70 KB |
| Bird_2 | glides a banked oval (body bone, yaw follows the path), two slow flaps then a glide; outer wing follows the inner | 516 | 6 bones | 70 KB |

#### Treehouse deck at sunset (`treehouse_sunset`)

Up on a plank deck in the canopy at golden hour: swaying paper lanterns on a rope, a hut and a giant trunk framing the sides, palms poking out of a sea of treetops, a stepped toy sun.

| Asset | Animation (4 s loop) | Tris | Rig | .glb |
|---|---|---|---|---|
| SkyBackdrop | static | 256 | - | 12 KB |
| SunDisk | glow breathes: halo rings pulse in scale (2x per loop), core bobs slightly | 384 | 2 bones | 38 KB |
| DistantHills | static | 396 | - | 24 KB |
| CanopySea | static | 3,080 | - | 179 KB |
| Deck | static | 1,628 | - | 93 KB |
| Hut | static | 356 | - | 24 KB |
| BigTrunk | static | 1,024 | - | 60 KB |
| LanternRope | static | 120 | - | 8 KB |
| Lantern_1 | pendulum sway on its rope (2 bones: rope + body, follow-through) with a slow twist | 332 | 2 bones | 41 KB |
| Lantern_2 | pendulum sway on its rope (2 bones: rope + body, follow-through) with a slow twist | 244 | 2 bones | 32 KB |
| Lantern_3 | pendulum sway on its rope (2 bones: rope + body, follow-through) with a slow twist | 332 | 2 bones | 41 KB |
| Lantern_4 | pendulum sway on its rope (2 bones: rope + body, follow-through) with a slow twist | 244 | 2 bones | 32 KB |
| Palm_1 | trunk sways (4-bone chain), 7 fronds x 3 bones flutter with follow-through | 1,608 | 25 bones | 195 KB |
| Palm_2 | trunk sways (4-bone chain), 7 fronds x 3 bones flutter with follow-through | 1,608 | 25 bones | 195 KB |
| Vine_1 | 5-bone chain swings like a pendulum with a travelling lag (side + fore/aft) | 768 | 5 bones | 91 KB |
| BananaBunch_1 | stem pendulum + bunch bobs on a spring (2x) with a small twist | 2,244 | 2 bones | 235 KB |
| Fern_PotL | 7 leaves x 2 bones flutter (2x/3x per loop, random phase) | 604 | 15 bones | 81 KB |
| Fern_PotR | 7 leaves x 2 bones flutter (2x/3x per loop, random phase) | 604 | 15 bones | 81 KB |
| Cloud_1 | drifts on a slow oval (side-to-side 0.35 x scale, bob 2x) while its puffs breathe | 432 | 4 bones | 49 KB |
| Cloud_2 | drifts on a slow oval (side-to-side 0.35 x scale, bob 2x) while its puffs breathe | 432 | 4 bones | 49 KB |
| Cloud_3 | drifts on a slow oval (side-to-side 0.35 x scale, bob 2x) while its puffs breathe | 540 | 5 bones | 60 KB |
| Bird_1 | glides a banked oval (body bone, yaw follows the path), two slow flaps then a glide; outer wing follows the inner | 516 | 6 bones | 70 KB |
| Bird_2 | glides a banked oval (body bone, yaw follows the path), two slow flaps then a glide; outer wing follows the inner | 516 | 6 bones | 70 KB |
| Fireflies | 8 fireflies orbit small ellipses (1x/2x per loop) with bobbing and a blink (scale pulse) | 704 | 8 bones | 97 KB |

#### Waterfall lagoon (`waterfall_lagoon`)

Monkey on a mossy shore rock; behind him a turquoise faceted lagoon with lily pads and leaping koi, and a stepped waterfall pouring from a notch in block cliffs.

| Asset | Animation (4 s loop) | Tris | Rig | .glb |
|---|---|---|---|---|
| SkyBackdrop | static | 256 | - | 12 KB |
| DistantJungle | static | 3,432 | - | 200 KB |
| Cliffs | static | 9,188 | - | 505 KB |
| Shore | static | 1,700 | - | 97 KB |
| LagoonWater | two shape keys in quadrature (cos/sin weights) = ripples travelling one wavelength per loop | 1,200 | 2 shape keys | 264 KB |
| Waterfall | 16 flow blocks slide down the stepped sheet (1x/2x per loop), growing in at the lip and shrinking into the foam, so the wrap is invisible | 836 | 17 bones | 132 KB |
| Foam | 7 foam blocks churn: bob and pulse at 2x/3x per loop | 756 | 7 bones | 92 KB |
| Tree_CliffL | trunk sways (3-bone chain + crown, follow-through), 6 leaf blocks flutter at 2x | 660 | 10 bones | 100 KB |
| Tree_CliffR | trunk sways (3-bone chain + crown, follow-through), 6 leaf blocks flutter at 2x | 660 | 10 bones | 100 KB |
| Palm_R | trunk sways (4-bone chain), 7 fronds x 3 bones flutter with follow-through | 1,608 | 25 bones | 197 KB |
| Vine_1 | 5-bone chain swings like a pendulum with a travelling lag (side + fore/aft) | 768 | 5 bones | 91 KB |
| Vine_2 | 5-bone chain swings like a pendulum with a travelling lag (side + fore/aft) | 768 | 5 bones | 91 KB |
| Fern_1 | 7 leaves x 2 bones flutter (2x/3x per loop, random phase) | 604 | 15 bones | 81 KB |
| Fern_2 | 7 leaves x 2 bones flutter (2x/3x per loop, random phase) | 604 | 15 bones | 81 KB |
| LilyPads | 7 pads bob on the ripples (2x per loop), tilt and turn a little | 1,652 | 7 bones | 184 KB |
| Fish_1 | leaps out of the water on an arc (root bone, pitch follows the arc), body wiggles (3-bone chain), swims back hidden under the surface | 364 | 4 bones | 51 KB |
| Fish_2 | leaps out of the water on an arc (root bone, pitch follows the arc), body wiggles (3-bone chain), swims back hidden under the surface | 364 | 4 bones | 51 KB |
| RippleRings | 7 splash rings grow from 0.1x, flatten and sink under the surface (timed to the fish) | 3,080 | 7 bones | 329 KB |
| Butterfly_1 | flies a figure-8 (body bone) facing its path; wings flap 12x per loop (3 Hz) | 132 | 3 bones | 24 KB |
| Bird_1 | glides a banked oval (body bone, yaw follows the path), two slow flaps then a glide; outer wing follows the inner | 516 | 6 bones | 70 KB |
| Cloud_1 | drifts on a slow oval (side-to-side 0.35 x scale, bob 2x) while its puffs breathe | 540 | 5 bones | 61 KB |
| Cloud_2 | drifts on a slow oval (side-to-side 0.35 x scale, bob 2x) while its puffs breathe | 540 | 5 bones | 60 KB |

#### Night jungle (`night_jungle`)

Moonlit jungle in deep blues: a stepped glowing moon and twinkling star gems, orbiting fireflies, glowing mushrooms and dark swaying trees, palms and vines.

| Asset | Animation (4 s loop) | Tris | Rig | .glb |
|---|---|---|---|---|
| SkyBackdrop | static | 256 | - | 12 KB |
| Stars | 34 star gems twinkle (scale pulse 1x-3x per loop, random phase) | 680 | 34 bones | 147 KB |
| Moon | moon bobs gently; stepped glow halo pulses (2x per loop) | 668 | 2 bones | 66 KB |
| DistantJungle | static | 3,960 | - | 230 KB |
| Ground | static | 4,616 | - | 264 KB |
| Tree_L | trunk sways (3-bone chain + crown, follow-through), 6 leaf blocks flutter at 2x | 1,172 | 10 bones | 144 KB |
| Tree_R | trunk sways (3-bone chain + crown, follow-through), 6 leaf blocks flutter at 2x | 1,172 | 10 bones | 144 KB |
| Tree_BackL | trunk sways (3-bone chain + crown, follow-through), 6 leaf blocks flutter at 2x | 660 | 10 bones | 100 KB |
| Palm_L | trunk sways (4-bone chain), 7 fronds x 3 bones flutter with follow-through | 1,548 | 25 bones | 186 KB |
| Palm_R | trunk sways (4-bone chain), 7 fronds x 3 bones flutter with follow-through | 1,608 | 25 bones | 195 KB |
| CanopyOverhang | branch bobs; 7 leaf blocks flutter (2x/3x per loop) | 976 | 8 bones | 117 KB |
| Vine_1 | 5-bone chain swings like a pendulum with a travelling lag (side + fore/aft) | 768 | 5 bones | 91 KB |
| Vine_2 | 5-bone chain swings like a pendulum with a travelling lag (side + fore/aft) | 768 | 5 bones | 91 KB |
| Fern_1 | 7 leaves x 2 bones flutter (2x/3x per loop, random phase) | 604 | 15 bones | 81 KB |
| Fern_2 | 7 leaves x 2 bones flutter (2x/3x per loop, random phase) | 604 | 15 bones | 81 KB |
| Mushrooms_1 | 4 glowing mushrooms squash-and-stretch (1x/2x per loop) | 880 | 4 bones | 103 KB |
| Mushrooms_2 | 3 glowing mushrooms squash-and-stretch (1x/2x per loop) | 660 | 3 bones | 78 KB |
| Mushrooms_3 | 4 glowing mushrooms squash-and-stretch (1x/2x per loop) | 880 | 4 bones | 101 KB |
| Fireflies_1 | 10 fireflies orbit small ellipses (1x/2x per loop) with bobbing and a blink (scale pulse) | 880 | 10 bones | 120 KB |
| Fireflies_2 | 12 fireflies orbit small ellipses (1x/2x per loop) with bobbing and a blink (scale pulse) | 1,056 | 12 bones | 144 KB |
| Fireflies_3 | 14 fireflies orbit small ellipses (1x/2x per loop) with bobbing and a blink (scale pulse) | 1,232 | 14 bones | 167 KB |
| Cloud_1 | drifts on a slow oval (side-to-side 0.35 x scale, bob 2x) while its puffs breathe | 540 | 5 bones | 60 KB |
| Cloud_2 | drifts on a slow oval (side-to-side 0.35 x scale, bob 2x) while its puffs breathe | 540 | 5 bones | 60 KB |

Render times are from this cloud container (4 vCPU, Cycles on CPU, OpenImageDenoise), **not the owner's Dell**.
Stills: 64 samples, 4 bounces. Video frames: 8 samples, 2 bounces (clean after denoising at this flat-colour look).

## Recommendation

**Default: the sunny jungle clearing**, with the **night jungle** as its pair.

- *Sunny clearing* matches the app best: the same saturated greens and banana yellow as the UI, Monkey's brown fur
  reads clearly against the lit grass and the pale jungle band behind his head, and the busy parts (vines, bananas,
  canopy) stay in the top third, away from him and the status chips under the stage.
- *Night jungle* is the natural partner for his sleep chain (doze → sleep): swap to it when he dozes off or after
  dark. It is dark enough that white UI text stays readable on top of it.
- *Treehouse at sunset* is the most atmospheric (the sun's halo sits right behind his head like a rim light), but his
  brown fur on a brown deck has the least contrast; good as an "evening" variant, not as the default.
- *Waterfall lagoon* is the calmest and cleanest behind him (water and a single vertical waterfall). Good alternative
  if the clearing feels too busy; the cliffs are the least "toy" part and would want another pass.

A time-of-day rotation (clearing by day, treehouse in the evening, night jungle at night and while he sleeps) uses
three of the four with no extra work.

## Using one in the app

Monkey's 3D view (`ui/src/avatar3d.ts`) is a transparent WebGL canvas (`alpha: true`, clear colour 0) inside
`#stage`, whose CSS background is a green radial gradient. The avatar renders at tiered rates: the display's rate
while busy, 30 fps idle, 15 fps asleep, nothing while hidden (`tierFps`). That shapes the options:

| | **A. Static still (recommended first)** | **B. Looping video** | **C. Animated .glb in the avatar's scene** |
|---|---|---|---|
| How | `<scene>_still.png` → WebP as the `#stage` CSS background, anchored bottom-centre so his feet meet the floor | `<scene>_loop.mp4` in a muted, looping `<video>` behind the canvas | Load `<scene>_app.glb` into the same `THREE.Scene`, play every clip with one `AnimationMixer`, use its `BG_Camera` framing |
| Shipped bytes | **37–65 KB** WebP at 1080x1800, 23–41 KB at 720x1200 (measured) | 0.25–0.44 MB per 4 s loop at 540x900 (H.264) | 1.9–3.9 MB per scene, 0.4–0.7 MB gzipped (the installer compresses) |
| CPU per frame | none (one composited layer) | video decode at 24 fps (hardware decode in WebView2; small but never zero) | **0.04–0.08 ms** for mixer + bone updates with the app variant, 0.06–0.14 ms with the full glb (measured with `bench_three.mjs` in Node on this container's CPU; Monkey's own idle clip: 0.10 ms), plus WebGL submission of the extra draw calls |
| GPU per frame | none extra | compositing a 24 fps layer | +19–32k triangles (Monkey is 61.5k) and +22–26 draw calls with the app variant (85–112 without; Monkey: 17); but the canvas would have to cover the whole stage and every pixel is then shaded each frame (today most of it is transparent) |
| Idle behaviour | nothing to do | pause the video at the idle/asleep/hidden tiers, or it decodes forever | the background only moves when the avatar renders, so it follows his tiers (30 → 15 → 0 fps) |
| Look | exactly the Cycles render | exactly the Cycles render | different: lit by the app's lights and environment, not Cycles; needs flat/toon materials and `castShadow = false` on the background to stay cheap and on-style |
| Effort | a few lines of CSS + a dimming overlay for text contrast | small | real work: camera/framing changes (the avatar camera is 28° and framed on him), lighting, a quality tier |

**Cost estimate in short:** A costs nothing at runtime. B costs a continuous decode + composite unless it is paused
with the avatar's tiers. C adds roughly one more Monkey's worth of draw calls, half his triangles and a full-canvas
fill every frame, on top of the main GPU cost the lag audit already counts (`docs/LAG-AUDIT.md`); measure it on the
Dell before shipping (none of these numbers come from the owner's hardware; GPU time can't be measured meaningfully
in this container's software GL).

**Suggested path:** ship A for one or two scenes (clearing by day, night jungle while he sleeps); if the owner wants
the world to move, try B at Juice *full* only, paused whenever the avatar drops to its idle/asleep/hidden tiers; keep
C for a later "Monkey interacts with the world" feature (picking a banana, parallax with the cursor), using
`_app.glb`, the toon materials from `ui/src/blocky/kit.ts` and only the near assets live (vines, bananas, fireflies)
over a static still of the rest.

## Limits and next steps

- **Not checked on the Dell.** All timings and costs are from this cloud container.
- **Clouds** can't cross the sky in a 4 s loop; they drift on an oval. A longer clip (e.g. 24 s) per cloud would let
  them cross and still loop, at the cost of different clip lengths.
- **Glow** (lanterns, fireflies, moon, mushrooms) is plain emission; there is no bloom, so tiny emitters read as dots.
- The **lagoon cliffs** and the **distant jungle bands** are the plainest parts; the bananas are the heaviest asset
  (about 2.2k triangles each).
- The **glbs are not optimised**: no quantisation or meshopt. `gltfpack -cc` or Draco would shrink them a lot if C is
  ever pursued.
- The **app variant** bakes colours into vertex colours with one roughness, so it is slightly flatter than the full
  materials.

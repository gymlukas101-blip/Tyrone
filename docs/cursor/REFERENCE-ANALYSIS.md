# Banana cursor: reference analysis and fidelity status

## Reference

- **What it is:** the owner's concept sheet, 1536×1024. It shows:
  - a large hero cursor (hover-like, with glow and rays);
  - four state tiles: DEFAULT, HOVER, CLICK (PRESS), LOADING / BUSY;
  - labels and a third-party wordmark.
- **Not committed.** The sheet is kept local: it has a third-party wordmark and isn't needed at runtime. `ref/` (the analysis crops) is gitignored.
- **What is committed:**
  - `banana_sprite.png`: the DEFAULT cursor isolated from it, original pixels;
  - the effect parameters measured from it.

## Status (2026-11-19): extracted, promoted, compared

1. `python -m tools.cursor.fidelity extract reference.png` isolated all five cursors. They're shown on light and magenta backgrounds to check for fringes, and none were found.
   - DEFAULT is 203×276 px of original art, with the hotspot at sprite pixel (14, 6).
   - It's a clean cut: exact silhouette, no background, and no dark fringe.
2. `promote` made it the **one base asset**: `manifest.json → sprite`. Every state, the browser cursor, the Settings preview and the Windows overlay PNGs draw that same image. The vector `banana.svg` is now only the fallback.
3. `compare` rendered the states with the **real runtime controller** and aligned them on the hotspot. The sheets are in `docs/cursor/fidelity/`.

| State | Silhouette IoU (32 / 48 / 64 / 128 px) | Luma SSIM (same) | Reading |
|---|---|---|---|
| DEFAULT | 0.993 / 0.992 / 0.993 / 0.994 | 0.989 / 0.985 / 0.983 / 0.972 | The reference's own pixels. Differences sit only on anti-aliased edges after resampling. The 96 px row scores 0.93/0.63 because of a one-pixel alignment rounding in the comparison at that size, not a visible difference. |
| HOVER | ≈0.59 | ≈0.1–0.2 | The low numbers mostly measure the reference crop's **dark glow halo** (pixels of the dark board that the mask kept) against our transparent glow. Visually: contour band, warm glow and three wedge rays now match in placement and shape. **Remaining difference:** our contour band is slightly heavier toward the lower right; the reference band is perfectly even. |
| CLICK | ≈0.5–0.58 | ≈0.1–0.4 | The reference is a single still frame; ours is an animation captured at 120 ms. Inner bright ring, second ring and segmented outer arcs are present. **Deliberate difference:** our rings are centred **exactly on the click point** (the tip), as the functional requirements demand. The reference's rings sit slightly below and to the right of the tip. |
| BUSY | 0.83 / 0.81 (at 48 / 64) | 0.85 / 0.74 | Ring position, size, flat segment ends and bright-right/dim-left pattern match. The ring rotates, so any still frame differs in phase. |

These scores support judgement; they don't replace it. The DEFAULT object is a faithful reproduction (it *is* the
reference art). The effects are close reproductions built as independent layers, not a 1:1 match.

## Layout of the sheet (approximate, used as search windows; the mask finds the exact bounds)

| Element | Approximate region (x0, y0, x1, y1) | Notes |
|---|---|---|
| Hero | 95–668, 70–895 | Golden contour glow on the whole silhouette; 2–3 bold ray wedges up and to the right (about 480–615, 120–265) |
| DEFAULT | 832–1030, 85–335 | **Normal-state baseline**: no glow, about 190×250 px, so every runtime size from 32 to 128 px is a downscale of original pixels |
| HOVER | 1195–1450, 85–360 | DEFAULT plus a bright yellow contour (about 3 px) with soft outer glow, and 3 rays at the upper right |
| CLICK (PRESS) | 790–1060, 515–790 | DEFAULT, slightly smaller, plus a bright inner ring around the tip and segmented outer arcs |
| LOADING / BUSY | 1200–1450, 535–790 | DEFAULT plus a 6-segment ring at the upper right of the banana; segment opacity steps around the ring |

## The object (from the hero)

- **Pointer**
  - A tall cream arrowhead with its tip at the top left. The tip is the hotspot.
  - Facets: about 5–7 large flat triangles, lighter on the left and top, slightly darker cream toward the right edge.
  - The left edge carries a **thick dark-brown extrusion band**: the 3D side of the pointer, about 8% of the cursor width.
- **Right peel**
  - A large puffy **hood** that rises above the pointer's right edge, arcs over and comes down on the right side.
  - The top is pale cream with many small facets; the underside is darker and visible as a shadowed cavity.
- **Left peel**
  - A big curled petal on the left that hangs down and slightly inward, its tip pointing down.
  - Cream outside, golden-cream inside, with rounded faceting.
- **Fruit**
  - Saturated golden yellow, broad between the peels, narrowing diagonally down and to the right.
  - Clearly faceted, in vertical strips.
- **Stem**
  - A beveled **brown block** at the lower right: a lighter top face, a darker side face, and a crisp square end.
- **Outline**
  - A dark brown rim around the whole silhouette, thicker on the lower left (the extrusion).
  - In the hover and hero states, a thin bright-yellow outer contour sits outside it, with no dark fringe between them.
- **Palette** (eyeballed; `extract` measures the real medians):

| Region | Colour |
|---|---|
| Cream | `#f7e8b8`–`#fff6d6` |
| Fruit | `#ffd21a`–`#f2b50c` |
| Brown edge | `#5a3517` |
| Stem | `#7a4521` / `#4e2a10` |
| Glow | `#ffd60a` |

## The earlier vector reconstruction vs the reference (kept for the record; now only a fallback)

`banana.svg` is a hand-built vector reconstruction, used only if the sprite is missing.

| Aspect | Matches | Differs |
|---|---|---|
| Silhouette | Pointer up-left, two peels, fruit diagonal, stem lower right | Reference peels are **larger and rounder**. The right hood is taller and wider, the left petal fuller. The pointer is proportionally a bit longer in the reference. |
| Facets | Flat faceted look, lighter left faces | The reference has more, smaller facets on the peels and soft ambient occlusion between pieces; the vector uses fewer, larger facets. |
| Brown edge / stem | Visible extrusion band and beveled stem | The reference's left band is thicker and more even; its stem block is larger relative to the fruit. |
| Colours | Same family | The vector's cream runs slightly warmer, and its fruit is slightly more orange in the shadows. |
| HOVER | Bright contour, glow, 3 rays up and to the right | Reference rays are placed closer to the hood; its contour is a crisper, more even band. |
| CLICK | Squash around the tip, ring at the tip, dashed outer ring | Reference outer ring is drawn as **separate arcs** (gaps), not a dashed line. |
| BUSY | 6-segment golden ring with stepped opacity, upper right | Close |

With the vector, the quality gates "silhouette closely matches" and "peel proportions retained" were **not** met. With the promoted sprite they are (DEFAULT IoU 0.99).

## Why a sprite, not Blender, for the base

- **Resolution is enough.** DEFAULT is about 190×250 px of original art. Every runtime size from 32 to 128 px downsamples it. A sprite reproduces the facet layout, lighting and colours exactly; a re-modelled 3D banana can only approximate them.
- **One object.** The hover, click and busy differences in the reference are all *effects around the same banana*. They're implemented as independent CSS layers around one base image, so the object can't change between states.
- **Blender: deferred.** A Blender file only pays off for real 3D motion (peel flaps moving). The development priority puts that fifth. `tools/blender/` already has the headless pipeline if it's wanted later.

## Pipeline (tools/cursor/fidelity.py, numpy and Pillow only)

1. **Mask.** Cursor pixels are saturated (yellow, brown) or bright (cream); the textured background is dark, grey and low saturation. Then: the largest component, nearby effect blobs kept for the effect states, and holes filled.
2. **Decontaminated alpha.** Interior pixels are kept exactly. The 1.5 px edge ring takes its colour from the nearest *interior* pixel, so there's no dark fringe on light pages.
3. **Hotspot.** The opaque pixel furthest toward the top left (the tip).
4. **Effect layers.** State minus DEFAULT, aligned on the hotspot: `ref/fx_hover.png`, `ref/fx_click.png`, `ref/fx_busy.png`.
5. **Compare.**
   - Renders come from the **real runtime controller** (`render_states.js`), not an art tool.
   - They're aligned on the hotspot and silhouette height.
   - The tool computes silhouette IoU, luma SSIM on the overlap and mean RGB error.
   - The sheets show reference | runtime | overlay (red = missing, blue = extra) | difference, on dark and light, at 32–128 px plus 384 px.
6. **Self-test of the pipeline.** On a synthetic sheet, the runtime render on a textured board laid out like the reference, extraction and comparison round-trip at **IoU 0.979 and SSIM 0.923** at 128 px. Those losses come from compositing the glow and resampling, which bounds what a faithful sprite should score.

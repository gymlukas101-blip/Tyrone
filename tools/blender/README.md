# Monkey's Blender tools (headless, bpy 5.3)

The model only exists as `ui/public/models/monkey.glb`; these scripts import it, change it and export it again
with settings that keep the runtime contract (node, morph and clip names, KHR material extensions).

| Script | What it does |
|---|---|
| `common.py` | GLB import/export that round-trips cleanly (verified with `glbinfo.py`) |
| `glbinfo.py` | Summary of a GLB for before/after diffs (no Blender needed) |
| `anim.py` | Pose DSL: angles in armature axes (Z up, faces -Y, his right is -X), mirroring, overlap lag, easing |
| `reach.py` | Tiny FK solver: puts a hand exactly on a spot of his body (results cached in `reach_cache.json`) |
| `clips_tier1.py` | The Tier-1 kit: idle fidgets, sleep chain, wake-ups, attention, talk gestures (23 clips) |
| `bake_ao.py` | Cycles AO bake, composited into the color maps (originals kept in `src/`; `--reuse-ao` skips re-baking) |
| `fur_cards.py` | 300 crossed alpha-tested tufts on the silhouette, skinned + shape keys from the body (`--count`, `--seed`) |
| `contact_sheet.js` | Renders clips with the real app renderer (three.js) into a review sheet |
| `axis_test.py` | Render-checks the DSL's axis conventions |
| `blocky_icons.py` | Renders four toy-block icons' "pop" clip as sprite strips for the icon study (`docs/ui/BLOCKY_ICONS.md`, gallery only) |

Rebuild the shipped model (each step edits it in place, in this order):

    python -m venv ~/bpyenv && ~/bpyenv/bin/pip install bpy==5.3.0
    python tools/fur/make_fur_detail.py                       # fur_detail.png + tuft_alpha.png
    cd tools/blender
    ~/bpyenv/bin/python clips_tier1.py -- ../../ui/public/models/monkey.glb
    ~/bpyenv/bin/python bake_ao.py -- ../../ui/public/models/monkey.glb [--reuse-ao]
    ~/bpyenv/bin/python fur_cards.py -- ../../ui/public/models/monkey.glb

Every export resets the default morph weights to the idle clip's first frame (his resting face), because
three.js restores those defaults whenever a clip without face tracks takes over.

Review: `cd ui && npm run build`, serve `ui/dist` on :8765, then
`node tools/blender/contact_sheet.js --models monkey.glb --clips yawn,sit_down --frames 5 --out sheet.png`
(`--crop x,y,w,h` for close-ups, `--query tm=aces|agx|neutral` or `nofur`/`nocards` for look-dev).

Sound and effect beats for each clip live in `ui/src/avatar/events.ts` (frame numbers at 30 fps).

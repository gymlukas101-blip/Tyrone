# Sound source ledger

Every sound in this repo, and where it came from.

- **Shipped kit (`ui/public/sfx/*.ogg`, 145 takes):** ElevenLabs SFX, generated for this project. Prompts and loudness targets are in `tools/sfx/cues.json`; raw takes are in `tools/sfx/raw/`. This is the baseline "A", kept untouched.
- **Candidates (`ui/public/sfx/candidates/`, 105 takes, 13 cues):** rendered offline from the free sources below by `python -m tools.sfx.recipe tools/sfx/recipes/sprint1.json OUT --sources DIR`.
  - The recipe pins all 96 source files by SHA-256.
  - It records every processing step: trim, pitch (playback rate), high/low-pass, fades, gain, layer offsets, a level target and a −3 dBTP ceiling.
  - The candidates are used only when someone picks them in the Sound Lab.
- **Spend:** no paid audio API calls, no purchases. ElevenLabs credits used by this work: **0**.

Retrieval for all sources:
- **Date:** 2026-11-20.
- **Method:** `git clone --depth 1` or the project's GitHub release asset.
- **Safety:** no repo scripts, CLIs, npm installs or MCP servers were run. Audio was hashed and decoded only.
- **Storage:** the source files stay outside the repo. Re-download them from the URLs below.

License texts are copied in `docs/audio/licenses/`.

## Sources used

| Source | Pinned at | Author | Asset license (evidence) | Recorded or synthesized | Used for |
|---|---|---|---|---|---|
| [ETdoFresh/kenney.nl](https://github.com/ETdoFresh/kenney.nl): a mirror of Kenney's packs | `45df48c4` | Kenney Vleugels | **CC0 1.0.** Each pack ships its original `License.txt`: "License: (Creative Commons Zero, CC0) … free to use in personal, educational and commercial projects" (Impact Sounds 1.0, RPG Audio, Interface Sounds). Copies are in `licenses/kenney-*`. | Not stated. Impact and RPG are Foley-style material (impacts, cloth), very likely recorded. | `thump`, `chest_thump`, `flop` (impacts + cloth), `rustle` (cloth), `ui_open`/`ui_close`/`check`/`ui_error` (Interface Sounds) |
| [Calinou/kenney-ui-audio](https://github.com/Calinou/kenney-ui-audio) | `8c3d81b9` | Kenney Vleugels; packaged by Hugo Locurcio | **CC0.** Original `LICENSE.txt`: "UI SFX Set … (Creative Commons Zero, CC0) … You may use these assets in personal and commercial projects." | Not stated | `ui_click` C |
| [maximilianfeix/plinkfx](https://github.com/maximilianfeix/plinkfx), release asset `plinkfx-wav-ogg.zip` (sha256 `bafbad93…3b2f`) | `7e5f6a47` (v0.3.0) | Maximilian Feix | **CC0 1.0.** `LICENSE-SOUNDS`: "dedicated to the public domain under CC0 1.0 Universal … every audio file rendered from them … No credit needed." Code is MIT. | Synthesized (procedural recipes) | `ui_click` B, `check` B, `ui_open`/`ui_close` C, `ui_error` B, `notify` B, `flop` C, `rustle` C, `boing`, `sparkle` C |
| [wyzowl/sfx-kit](https://github.com/wyzowl/sfx-kit) | `92780e7a` | Wyzowl | **CC0 1.0.** Full CC0 legal code in `LICENSE`; README: "Free for any use, commercial or not: CC0, no credit required." | Synthesized | `whoosh`, `sparkle` B |
| [romainsimon/uisfx](https://github.com/romainsimon/uisfx) | `9950fe66` | Yuki Capital | **CC0 1.0.** `LICENSE-AUDIO`: "dedicated to the public domain under … CC0 1.0 … the procedurally generated audio files in `packages/uisfx/sounds`." | Synthesized | `notify` C (organic pack) |

## Checked and not used (yet)

| Source | Status | Why |
|---|---|---|
| kapishdima/soundcn | Conditional | Its "CC0" label is hard-coded for every file. Per file: 692 OK (482 with Kenney's original license), 121 excluded, including 110 Blizzard/World of Warcraft files marked "All Rights Reserved". Everything useful is available from the Kenney mirror directly, so I didn't use it. **Never run its `enrich-registry.ts`: it calls a paid AI gateway.** |
| remarkablegames/game-sounds | Conditional | MIT only, with no separate asset license. It would need the MIT notice shipped with the audio. Not needed this sprint. |
| adafruit/Adafruit-Sound-Samples | Conditional | CC0 per the README only (no license file); 22 kHz recordings |
| JimHPerry/psfx | **Rejected** | Non-commercial license; forbids redistribution and AI use |
| FilmCow mirror, cybernetic-samples | **Rejected** | No license file / no per-file provenance |
| Sonniss GDC bundles | **Not allowed here** | The license permits use in productions but not redistribution of the raw or reworked files. A public repo and its releases would be redistribution. |
| kenney.nl, opengameart.org, freesound.org, sonniss.com | **Blocked** | The container's network proxy refused them. Kenney is covered by the mirror's original license files. OwlishMedia's CC0 Foley pack and freesound CC0 recordings remain to be checked from a normal browser. |

## Rules
- Only CC0 (or, with its notice shipped, MIT) audio goes into this public repo.
- Record each new source here before using it, with its URL, pinned commit and quoted license.
- Pin every source file in a recipe by SHA-256. The renderer refuses a changed source.
- Monkey's voice and vocalizations stay his own: Fish clone or Pocket backup, made on the owner's PC.
- Never upload restricted audio to an AI service, and never present a synthesized source as recorded Foley.

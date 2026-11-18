# Monkey: UI, animation, VFX and sound direction (researched 2026-11-18)

This document holds the decisions. Each decision is followed by why, and by what we'll build in which order. Three research passes went into it:
- UI and Figma;
- Donkey Kong-style character animation;
- cartoon VFX and layered SFX.

Concept sheets are in `prototypes/vfx/`, made with GPT Image from the current 3D model for $0.48. They're style references, not final assets.

> **Limits of this research:** this session's network blocks YouTube, figma.com, elevenlabs.io, 80.lv and a few others.
> - The reference video ("Donkey Kong Bananza – All Idle Animations", `PcrWphKcoFI`) couldn't be watched directly. DK's idles were researched through wikis, Nintendo's "Ask the Developer" interview and coverage of it.
> - Figma and ElevenLabs details come from their indexed docs. They're marked "verify" where it matters.
>
> Monkey is an **original** character. We borrow principles (weight, timing, staging, comedy), never DK's designs, exact animations or sounds.

---

## 1. Decisions at a glance

| Question | Decision |
|---|---|
| How to organize the UI | **3 zones** plus overlays: top HUD with the voice-state pill and quick chips; **Stage** (avatar, about 60%); side panel with tabs **Chat · Tasks · Health**; bottom dock with a big push-to-talk button and a text fallback. Settings and Avatar Lab open as overlays. |
| Use Figma? | **Yes, but not as the source of truth.** The repo owns tokens, components and motion. Use Figma (through the Figma MCP connector) for: (a) a **review board**, where the built UI is pushed into Figma to compare against style frames and annotate; (b) **FigJam diagrams** of the screen map and the voice/animation state machine; (c) optionally **Figma Motion** for 1–2 vector loops. **Skip** Make, Sites, Code Connect, Dev Mode, Figma AI and prototyping/Smart Animate. They generate React, cost credits, need paid plans, or are slower than tuning springs in code. |
| Mockups first? | **Yes, AI images first, but only for art direction**: full-screen style frames and one sheet each for icons and VFX, judged as a whole so the elements match. Then **build in code**: icons become **SVG** in the repo, motion is code presets tuned in a "Juice Lab" page, and VFX is built in three.js/CSS. AI images are never sliced up and shipped. |
| Animation production | **Blender 5.3 headless (bpy) scripted keyframing** through a small "pose + beat" animation DSL. The scripts render contact sheets for review and export GLB. On top of that, a **runtime procedural layer** (breathing, look-at, blinks, spring bones, idle state machine) brings Monkey to life between clips. Mocap or AI text-to-motion is used only for occasional blocking. |
| VFX tech | Our own small **pooled VFX system**: toon `ShaderMaterial` with a 3-step ramp, alpha-erosion dissolve and an outline hull, with effect time **quantized to 12 fps** for a hand-drawn feel. Hero shapes (Z, "!", "?", lobed puff, banana, crack) are modeled in Blender and exported as a small GLB. **three.quarks** handles bursts (confetti, sparkles, tears). CSS overlays handle full-screen beats (impact flash, shake). |
| Sound | **Fish Audio S2.1 in Monkey's own voice for every vocal effort**: grunts, "hoo-hoo", yawns, laughs, gasps. Its bracket tags include `[yawning]` and `[laughing]`, so the vocals match his speech. **ElevenLabs SFX v3** (`POST /v1/sound-generation`, always with `duration_seconds`) for everything non-vocal. **ZzFX** synthesis for tiny UI blips, which costs zero bytes. A custom **Web Audio mixer** handles buses, ducking under speech, round-robin takes, pitch jitter and cooldowns. |
| Libraries | **Motion** (`animate`, MIT, a few kB) plus CSS `linear()` springs, **canvas-confetti**, **ZzFX**, **three.quarks**, and a hand-written spring-bone solver. **Skip** Rive and Lottie (WASM runtimes fight our single-file build), Howler (dormant) and Tone.js (heavy). |
| Not annoying after 100× | Intensity goes **inversely with frequency**, using common / uncommon / rare tiers. Use 3–5 takes played round-robin with no repeats, ±4–6% pitch and ±2 dB volume jitter, per-sound cooldowns and coalescing, and "familiarity decay" (celebrations get shorter after N plays). Speech always wins: SFX duck about 10 dB under Monkey's voice and are muted while the mic listens. Add a **Juice level** setting (Full / Calm / Minimal) that defaults from Windows "Animation effects" (`prefers-reduced-motion`), plus separate Master/SFX/UI volume. |

---

## 2. What makes Donkey Kong's animation work (and what Monkey takes from it)

- **Expressiveness was the brief.** Miyamoto says the Bananza redesign was about making DK "more expressive." The large on-screen size allows a wide range of facial expressions, and the comedy keeps him charming ([GamesRadar](https://www.gamesradar.com/games/donkey-kong/donkey-kong-creator-shigeru-miyamoto-explains-the-big-apes-redesign-was-all-in-service-of-making-him-more-expressive), [Nintendo Ask the Developer Vol. 19](https://www.nintendo.com/us/whatsnew/ask-the-developer-vol-19-donkey-kong-bananza-part-1/)).
  - DK barely speaks, so **his body and face carry everything** ([Game Rant](https://gamerant.com/donkey-kong-bananza-dialogue-facial-expressions-mascot/)).
  - Rule for Monkey: every animation must read with the sound off.
- **Weight is partly sound.** Miyamoto found DK floaty until the footsteps were made louder, step by step ([GoNintendo](https://gonintendo.com/contents/51943-miyamoto-helped-shape-movement-in-donkey-kong-bananza)). Rule: every foot plant and chest hit gets a soft low thump.
- **Heavy-body mechanics:**
  - The torso carries the squash while the short legs barely bend.
  - The long arms swing like heavy pendulums.
  - The head *lags* the chest.
  - Settles take longer than on a light character.
  - Volume is preserved: squash wider, stretch thinner.
- **Snappy timing with held poses** (from Overwatch's GDC animation talk): overshoot extremes, push poses further than feels normal, and hold key poses a little longer ([summary](https://evasokolova.wordpress.com/2016/04/03/gdc-overwatch-animation-talk-summary/)).
- **Never fully still.** A breathing base loop is the "ground texture" of the idle, with inhale slower than exhale. Body parts react with slight delays, and the pelvis sways side to side ([AnimSchool](https://blog.animschool.edu/2024/06/14/breathing-life-into-idle-animations)).
- **Goofy but powerful.** DK's idles and taunts pair a power beat (fist bump into uppercut, chest pound) with a goofy beat (crossed eyes, wet-dog shake, shrug) ([SmashWiki](https://www.ssbwiki.com/List_of_idle_poses_(SSB4)), [Mario Wiki taunts](https://www.mariowiki.com/taunt)). Monkey's kit follows the same pairing.
- **Idles escalate, then tell a little story.** They go from breathing to short bits to a self-entertainment gag (DK plays a handheld). In Bananza, idles even **change as a relationship grows**: Pauline goes from worried, to ruffling DK's hair, to tickling him ([GoNintendo](https://gonintendo.com/contents/52202-did-you-notice-this-small-animation-change-for-pauline-as-you-progress-in-donkey)). In Bananza DK also dozes off instantly at beds ([TV Tropes](https://tvtropes.org/pmwiki/pmwiki.php/Characters/DonkeyKongTitleCharacter)).
  - For Monkey: long idle leads to yawn, sit, doze, lying down and a **ZZZ sleep loop**.
  - New idle variants **unlock with your streak** or with how long you've had him.

**Working timings at 30 fps.** These are recommendations, not measured from DK:

| Beat | Frames |
|---|---|
| Anticipation | 4–8 |
| Fast action | 2–4 |
| Overshoot | 2–3 |
| Settle | 6–12 |
| Key-pose hold | 8–20 |
| Chest beat | 3 frames per hit |
| Blink | 2 closing, 1 closed, 3 opening |

Comedic "takes" can step on twos, while base loops stay smooth.

---

## 3. Rig and model audit (`ui/public/models/monkey.glb`, Blender 5.3 export)

**What's already there (good):**
- **57 bones:**
  - root, hips, spine, chest, neck, head;
  - shoulders, upper arm and forearm;
  - hands with 3 fingers × 2 joints plus a 2-joint thumb (a cartoon 4-finger hand);
  - thigh, shin, foot, toe;
  - **8-bone tail**, **3 hair tufts**, both ears, brows, eye bones, headset and mic boom.
- **Shape keys:**
  - 15 Oculus visemes;
  - smile, bigGrin, frown, smirk L/R, mouthO, grimace, tongueOut;
  - blink L/R, happy/angry/sad/wide eyes, squint;
  - brows up/angry/sad plus brow up L/R;
  - cheekPuff, cheeksUp, jawOpen;
  - body chestPuff, pecBounce L/R, bicepFlex L/R.
- **12 clips:** idle, listen, think, talk, happy, laugh, sad, angry, surprised, wave, flex, dance.

**Changes we'll make in Blender (scripted, headless):**

| Add | Why |
|---|---|
| `belly` bone plus `pec.L/R` bones (weighted from the existing chest/belly region, with falloff) | Spring jiggle on landings, chest beats and laughs. This is the heavy-body read. |
| A second spine bone (`spine.001`) | Smoother torso arcs and better squash and stretch on the big chest |
| Forearm twist bones | Fists, punches and chest beats deform without candy-wrapping |
| `prop.R` / `prop.L` sockets in the hands | Banana snack, handheld gadget, coffee mug and similar props |
| **VFX sockets:** `fx.head_top`, `fx.mouth`, `fx.temple.L`, `fx.ear.L/R`, `fx.chest`, `fx.foot.L/R`, `fx.ground` | Effects attach to exact spots: ZZZ from the mouth, sweat at the temple, steam from the ears, shockwave from the chest |
| **Shape keys:** `yawnWide`, `sleepy` (half-lids), `sneer`, `pucker` (whistle, kiss), `teethBare`, `browInnerUp`, `snoreCheek` | Yawning, sleeping, snoring, smug and goofy faces. These aren't possible today. |
| A shared non-uniform scale allowance on spine, chest and head (test skinning) | Squash and stretch |
| **Hero VFX mesh GLB** (Z, "!", "?", lobed puff, banana, crack decal, rock chunk, heart, star, music note, lightbulb) | Shared by the VFX system, each under 2k triangles |

Visemes stay as morphs. A jaw bone isn't required, because `jawOpen` plus `yawnWide` cover the big mouth shapes.

## 3b. Why DK looks higher quality than Monkey (and the fix list)

**Finding: Bananza's rendering tech is modest.** Digital Foundry measured:
- about 1080–1200p;
- FSR 1 plus SMAA, no DLSS;
- a 60 fps target that drops to 30;
- criticized shadows and a soft image.

Sources: [Nintendo Life](https://www.nintendolife.com/news/2025/07/somewhat-mixed-digital-foundry-delivers-its-technical-analysis-of-donkey-kong-bananza), [TweakTown](https://www.tweaktown.com/news/106456/donkey-kong-bananza-on-the-switch-2-uses-amd-fsr-1-not-nvidia-dlss/).

So DK's quality comes from **art direction, shape design, fur, materials and above all animation**, not graphics tech:
- The team (the Super Mario Odyssey team, Nintendo EPD Tokyo) deliberately made his fur "rich and thick". They added britches and suspenders so his back isn't "a monotonous mass of brown fur" ([TechRadar](https://www.techradar.com/gaming/nintendo/donkey-kong-wears-clothes-in-banaza-because-nintendo-was-conscious-of-what-the-ape-would-look-like-from-the-back)).
- They put "particular effort into creating a wide range of expressions" ([Bounding Into Comics](https://boundingintocomics.com/video-games/donkey-kong-bananza-new-design-insights)).
- It won CEDEC 2026 awards for visual arts and engineering ([Inven](https://www.invenglobal.com/articles/24119/donkey-kong-bananza-wins-three-awards-at-cedec-2026)).
- No public source describes how DK's fur is rendered. From looking at it, it appears to be sculpted, clumped tufts that break the silhouette, a strand/clump normal map, darker roots and lighter tips, and a soft rim sheen **(unverified)**.

**Our gap, ranked:**

| Rank | Cause | Impact | Detail | Status |
|---|---|---|---|---|
| 1 | Animation | Biggest | Short, generic clips (baked at 24 fps, but the motion itself is simple). Before Phase 1: no secondary motion, no look-at, no breathing, no idle variety. | Phase 1 fixed a lot of this |
| 2 | Materials and fur | Large | Only 2 textures for the whole model, no normal map. Painted noise reads as a plush toy. No tufts on the silhouette. | **Done:** baked AO in the color maps (`tools/blender/bake_ao.py`), runtime triplanar strand detail (`ui/src/avatar/fur.ts`), 300 crossed silhouette tufts (`tools/blender/fur_cards.py`) |
| 3 | Lighting and post | Medium | We already have ACES tone mapping, room IBL, key and rim light. We lack ambient occlusion, a contact shadow (added now), fur sheen (added now) and SMAA. | **Done:** custom jungle IBL, 3-point lights with two rims, soft self-shadows (scaled by juice level). No screen-space post: the canvas is transparent, and baked AO covers the creases. |
| 4 | Model | Smallest | 38k vertices is **not** the bottleneck. A smooth silhouette, and the face and hands, matter more than polycount. | Planned |

So the answer to "Blender failed, or lighting?" is a **third option: mostly animation and fur/material design**, with lighting a smaller factor.

**Upgrade list, in order:**
1. ✅ Alive layer, contact shadow, fur sheen (done).
Results: `prototypes/fur-lighting/compare-full.png` and `compare-closeup.png` (before | after).

2. ✅ **Baked fur detail (done as: Cycles AO baked into the color maps, plus runtime triplanar strand bump, which avoids UV seams):**
   - subdivide plus a clump/strand displacement along the fur flow;
   - bake normal, AO and cavity onto the game mesh;
   - multiply AO and cavity into the albedo for darker roots and lighter tips;
   - vary roughness.
3. ✅ **Silhouette tuft cards:** alpha-tested fur "fin" cards along the shoulders, forearms, head and back, skinned to the same bones (+1–3k triangles).
4. **Post:** N8AO or GTAO at half resolution, plus SMAA. It must keep the transparent background, so test it in WebView2.
5. **Clip polish pass in bpy:** Bezier easing, child-bone overlap offsets of 1–3 frames, anticipation and overshoot keys, arcs. Longer 6–10 s idles with variation.
6. **Optional "high" setting:** shell fur (8–16 shells, alpha-test).

**Honest ceiling:** we won't match a dedicated Nintendo team's hand-sculpt and hundreds of hand-keyed clips. The realistic target is a "Bananza-like feel" at 60 fps on a laptop. If there's ever budget, 4–6 hand-keyed clips from a freelance animator would beat any script.

---

## 4. The animation kit

**Layers:**
- **FB** = full body.
- **UB** = upper-body override (clip filtered to spine and up).
- **ADD** = additive.
- **FACE** = morphs driven by code.

**Frequency:**
- **C** = common (every 15–40 s of idle).
- **U** = uncommon (2–5 min, cooldown of 3 min or more).
- **R** = rare.

**Tier 1 (build first: this is what you see all day)**

| Group | Clips |
|---|---|
| **Idle** | `idle_base` (breathing and sway, refined existing clip), and these variants: `lookaround` (C), `scratch_head` (C), `scratch_belly` (C), `knuckle_crack` (C), `stretch_shoulders` (C), `mini_chestbeat` (U), `shake_off` wet-dog shake (U, the springs do the work), `cross_eyes` goofy beat (U), `flex_check` (U), `banana_snack` (U, prop), `impatient_tap` (U, after 3 min) |
| **Long idle → sleep** | `yawn` (5 min) → `sit_down` → `sit_doze` (head nods, catches himself) → `lie_down` (8 min) → `sleep_loop` (belly breathing, snore cheek puff, **ZZZ**) → occasional `sleep_rollover` |
| **Wake** | `wake_startle` (the wake word while asleep: jolt, "!", lands in a squash, sheepish head scratch) and `wake_groggy` (you return without the wake word: rubs eyes, stretches) |
| **Attention and listening** | `attn_perk` (ears and head snap toward you, brows up, small hop), `listen_loop` (lean in, hand cupped to ear) with additive nods during speech pauses |
| **Thinking** | `think_loop` (chin rub, eyes up-left) → `think_scratch` / `think_count_fingers` when the wait is over 3 s → `think_eureka` (finger up, lightbulb) on the first word of the answer |
| **Talking** | `talk_base`, plus 8 upper-body gestures picked by sentence sentiment and punctuation every 2–4 s: open palms, point at you, shrug, two-hand "big", fist-in-palm, count on fingers, thumbs up, wave-off. A procedural head bob follows voice loudness. |

**Tier 2**

| Group | Clips |
|---|---|
| **Emotions** | Each one gets a hit (1–1.5 s) that settles into a looping hold, with face presets that can layer over talking. Existing: happy, laugh, sad, angry, surprised. New: embarrassed, proud, confused, bored. |
| **Celebrations** | `celebrate_small` (fist pump: task done), `celebrate_chestbeat` (assignment complete: shockwave, small screen shake), `celebrate_jump_spin` (milestone), `streak_dance` (3/7/30-day streaks) |
| **Reactions** | `error_oops`, `facepalm`, `surprise_take` (squash, then stretch, then a 3-frame hold), `laugh_big` (knee slap, belly bounce), `shrug_grunt`, `flinch` |
| **Movement** | `strut_walk` (in place; code moves him), `jump_up` / `fall` / `land_heavy`, `ground_pound`, `roll`, `peek_in` (slides in from the screen edge on startup) |
| **Power moves** (comedy easter eggs, e.g. "Monkey, show me your strength") | `chestbeat_shockwave` (8 accelerating hits), `ground_slam_double`, `wind_up_punch` (12-frame windup, 2-frame punch, smear, falls over), `uppercut_combo` |
| **Dances** | Existing dance, plus hip shake, stomp two-step, robot, arm wave. Loops land on bar boundaries. |

**Runtime brain (`ui/src/avatar/`):**
- Priority: **system** (listen/think/talk) > **reaction** > **celebration** > **idle variant** > **idle base**.
- Every 6–15 s while idle, pick a variant by weighted random among those eligible. Exclude the last two played, halve a variant's weight each time it plays, and let it recover over its cooldown.
- The escalation tier comes from idle time: under 60 s fidgets; up to 3 min props; up to 8 min yawn, sit and doze; after that, sleep.
- Loud idles are suppressed while you type. New variants unlock with your streak.
- **Procedural layer:**
  - Additive breathing.
  - Look-at toward the cursor and window center: eyes lead fast, the head follows with lag, split about 40/60 between neck and head, clamped.
  - Blinks every 2–6 s, with a 15% chance of a double blink and a blink on big head turns.
  - Damped springs on the tufts, ears, tail, mic boom and the new belly/pec bones.
  - Morph-target tracks are stripped from body clips, and the face is written last: visemes own the mouth, and emotion mouth shapes are scaled by (1 − 0.6 × speech energy).
- **Event sidecar** (`avatar/events.ts`): one table per clip lists `{t, sfx, vfx}`. The same table drives sound and effects, so they stay locked to the animation.

---

## 5. VFX catalog (concepts in `prototypes/vfx/`)

**House style:**
- Rounded lobed puffs, teardrops, 4- and 5-point stars, spiky bursts, tapered speed lines.
- Flat 3-tone cel color with thick warm-brown outlines (#2A1A10).
- Warm cream/yellow/orange/white effects against the jungle greens, with cyan #33E1FF as the accent.
- Timing: about 10% build, 20% hold, 70% dissipate. Impulse effects pop to 120% on frame 1.
- Effects animate on 12 fps steps.
- **Palette (from the style board):**

| Hex | Color |
|---|---|
| #FFF7E2 | cream |
| #F6DFA6 | light yellow |
| #FFD42A | yellow |
| #FF8A1C | orange |
| #FFFFFF | white |
| #33E1FF | cyan |
| #16B554 | jungle green |
| #0A7D3A | dark green |
| #B99163 | tan |
| #8A5B3E | brown |
| #2A1A10 | outline |

| Effect | Trigger | Look and timing | Built as |
|---|---|---|---|
| **ZZZ** | sleep_loop | 3 chunky extruded cream Z's from the mouth. One every 1.2 s, rising on a sine sway, growing 0.6×→1.2×, popping after 2.5 s. | Hero mesh, pool of 6 |
| Yawn puff | yawn | One pale lobed puff, 0.6 s, erodes away | Erosion mesh |
| **"!" burst** | wake / surprise | Yellow "!" over a spiky white burst. 0 → 1.4× → 1.0× in 0.15 s, hold 0.6 s, plus 3 shock lines; the floating Z's pop like bubbles. | Sprite plus mesh |
| Sweat drops | thinking hard | 1–3 cyan drops from the temple, arcing and squashing, every 1.5 s | Mesh |
| "?" / lightbulb | confused / eureka | Wobbly purple "?"; bulb with ray dashes flashing twice | Sprite |
| Anger steam plus vein | angry | Lobed puffs from the ears at 8 fps; red cross vein throbbing 1.0–1.25× | Erosion mesh plus sprite |
| Laugh tears | laugh | Cyan droplets squirting sideways from the eyes | quarks |
| Hearts and stars | happy | 5–8 rising with a wobble, 1.2 s | quarks |
| Dizzy stars | dizzy | 3 stars orbiting the head bone at 1 rev/s | Instanced |
| **Shockwave rings** | chest beat | 2–3 rings from the chest, 0.3×→2.5× in 0.35 s, thinning | Ring mesh, additive |
| **Ground slam** | ground pound | 1-frame white flash, star crack decal held 1.5 s, lobed dust ring, 8 rounded rock chunks in arcs | Decal, instanced chunks, CSS flash |
| Dust puffs | land / stomp / sit | 4–8 tan puffs in a ring at the feet | Instanced erosion |
| Speed lines | dash / jump | 6–10 tapered streaks flickering at 12 fps | Ribbon trail |
| **Banana confetti** | celebrate | Cone burst of mini bananas and paper bits that flutter down, 2.5 s | quarks with mesh renderer |
| **Sparkles plus check badge** | assignment done | Staggered 4-point twinkles (0.25 s each); green check badge pops at 1.4× and settles | Points plus DOM badge |
| Music notes | dance | Emitted on the beat, zig-zag upward | Sprites synced to BPM |

**Budget:**
- Fewer than 30 draw calls and 300 live particles.
- 1–2 1024² atlases (WebP).
- No allocation while effects play.
- Effects pause when the window is hidden, and pixel ratio is capped at 1.5.

---

## 6. Sound design

**Layers per action**, each a separate short file, triggered together or staggered by a few frames:
1. Vocal effort (Fish, Monkey's voice).
2. Body foley (fur, skin slap, chest thump).
3. Motion (whoosh sized to the limb).
4. Contact (footsteps, impacts).
5. Cartoon sweetener (slide whistle, boing, pop, xylophone run).
6. A shared short-room reverb send.

**Mixer rules:**

| Rule | Setting |
|---|---|
| Buses | Voice, SFX, UI, Ambient |
| Ducking | SFX/UI duck about 10 dB under Monkey's speech (50 ms attack, 300 ms release). Vocal efforts are suppressed while he talks. Everything is muted while the mic records. |
| Variation | Takes chosen by shuffle bag (never the same take twice in a row), ±4–6% pitch, ±2 dB |
| Cooldowns | Per sound (sweeteners at most once per 3 s) |
| Polyphony | At most 8 voices; the oldest is stolen |
| Loudness | Master about −18 LUFS, peaks −1 dBTP; UI 6–10 dB under speech; ambient about −30 LUFS |
| Format | Opus mono, 48–64 kbps, loaded from the app folder (not inlined). About 250 clips is roughly 2–3 MB. |

**Asset sources:**
- **Vocals (Fish Audio S2.1, his voice).** About 15 types × 5 takes:
  - hup, hngh, hoo-hoo, ooh!, huh?, hmm;
  - yawn (`[yawning] Hwaaaahhh… mmm.`), sigh, snort-wake, gasp, growl, giggle, big laugh (`[laughing] Hoo-hoo-HAH-hah!`), "woo-hoo!";
  - a rare "oh banana!" easter egg.
  - Note: Fish S1 retires 2026-12-31, and we already use `s2.1-pro`.
- **SFX (ElevenLabs SFX v3).** About 50 one-shot cues × 3–5 kept takes, plus snore, dizzy, tick-tock and ambient loops.
  - About **25k credits** at 40 credits per second with the duration set. That fits a Starter month tightly, or about 20% of Creator.
  - Generate sequentially within plan concurrency.
  - Every prompt ends with "isolated, no music, close-mic, dry, game sound effect".
  - Examples:
    - snore: "Big comedic cartoon snore: deep rumbling inhale then a high whistling exhale", 4 s, loop.
    - chest beat: "Gorilla beating chest: one deep hollow cartoon thump, punchy low end", 0.5 s.
    - wake: "Cartoon startle: quick rising slide whistle and a bright boing", 0.8 s.
- **UI.** ZZFX synth parameters for clicks, ticks and pops (0 bytes), plus a few short clips for checkbox "ka-thunk", reward jingle and error "bonk".
- **Sound Lab page.** You audition the generated takes, keep or reject them, and the kept set is normalized and encoded automatically.

---

## 7. UI organization and "juice"

**Layout:**
- Top HUD: status pill, "3 due today" chip, Body Battery chip, settings.
- Stage: avatar, speech-bubble captions, VFX layer.
- Side panel tabs Chat / Tasks / Health, with keyboard shortcuts 1/2/3.
- Bottom dock: big push-to-talk button and text input.
- When a spoken answer is about tasks, the panel switches to Tasks and pulse-highlights the rows.
- State is shown in 3 channels at once:
  - avatar pose;
  - pill color and label;
  - an earcon on transitions only, plus an `aria-live` text update.

**Design tokens:**
- DTCG JSON in the repo (W3C format, stable 2025.10), generated into CSS variables.
- Three tiers: primitives → semantic → component.
- **Motion tokens:**
  - Durations: `instant 80`, `fast 150`, `base 240`, `slow 400`, `celebrate 900` ms.
  - Springs: `snappy`, `bouncy`, `wobbly`.
- **Audio tokens:** per-tier volume, cooldown and jitter.

**Juice rules:**
- **Buttons:** on press, scale to 0.95 and move down 2–3 px while the chunky shadow compresses (50–100 ms). On release, a spring returns with overshoot to 1.03 (150–250 ms). All buttons behave the same; only the main button wiggles on hover.
- **Popups:** scale 0.85 → 1.06 → 1, children stagger 30–50 ms, exits are faster and don't bounce.
- **Toasts:** at most 3, with duplicates merged ("+3 synced").
- **Checkboxes:** squash, stroke-draw the check, leaf puff and "ka-thunk". **Combo pitch** rises a semitone per check made within 10 s. Clearing everything is the big moment.
- **Counters:** tween 400–900 ms, ticks throttled to 12–15/s with rising pitch, ending in a scale punch.
- **Reward tiers:**
  - micro (<200 ms);
  - medium (popup plus small confetti);
  - big (Monkey celebration clip, confetti, jingle, small trauma-model shake of the panel only).
- **The comedy lives in Monkey; the chrome stays restrained** ([Juice It or Lose It](https://gdcvault.com/play/1016487/contactUs), [The Art of Screenshake](https://gamedeveloper.com/design/vlambeer-co-founder-shares-advice-on-building-better-action-games), [Most Satisfying Checkbox](https://notbor.ing/words/the-most-satisfying-checkbox), [UX in Motion](https://uxmag.com/articles/creating-usability-with-motion-the-ux-in-motion-manifesto)).

**Icons:** one AI reference sheet for consistency → SVG sprite in the repo (thick outline, flat fills) → inlined.

**The "100× test":** before shipping, script every common interaction to fire 100 times, and watch and listen.

---

## 8. Workflow (who owns what)

| Artifact | Tool |
|---|---|
| Art direction, style frames, VFX and icon concept sheets | GPT Image (reference only), `tools/vfx/generate_vfx.py` |
| Tokens, components, layout, motion presets | Code (repo). Juice Lab page for live tuning. |
| Review board, screen map and state diagrams | Figma and FigJam through MCP (optional mirror) |
| Rig changes, animation clips, hero VFX meshes | Blender 5.3 headless scripts (`tools/blender/`), with contact sheets for review |
| VFX runtime | three.js pooled toon VFX plus three.quarks plus CSS overlays |
| Vocal efforts | Fish Audio S2.1 (Monkey's voice) |
| SFX | ElevenLabs SFX v3, curated in the Sound Lab; ZzFX for UI blips |
| Sync | `avatar/events.ts` sidecar (one timeline for animation, SFX and VFX) |

---

## 9. Build order

| Phase | What | You'll see |
|---|---|---|
| **1. Alive foundation** (no new clips needed) | Idle brain (tiers, cooldowns, escalation to sleep), procedural breathing, look-at, blinks, spring bones, event sidecar, Web Audio mixer, VFX system with ZZZ, "!", sweat, sparkles, dust and confetti, Juice-level and volume settings | Monkey is never frozen, follows your cursor, falls asleep with ZZZs and wakes with a "!" |
| **2. Rig upgrade plus Tier 1 clips** | Blender script: new bones, sockets, shape keys, hero VFX meshes; the idle variants, sleep/wake set, attention/listen/think/talk gestures; contact sheets for your approval | The DK-style "never the same twice" idle life |
| **3. Sound** | Fish vocal set plus ElevenLabs SFX (needs your key, entered through the secure form, never in chat), Sound Lab curation, mixing | Layered sound on every move |
| **4. UI reorganization** | 3-zone layout, tokens, Juice Lab, SVG icons, button/popup/toast/checkbox juice, reward tiers; Figma review board and FigJam diagrams | The organized, juicy app |
| **5. Tier 2** | Celebrations, reactions, movement, power moves, dances, with their VFX and SFX | The full kit |

## Sources (main)
UI and Figma:
- [Figma MCP docs](https://developers.figma.com/docs/figma-mcp-server/)
- [Figma MCP write to canvas](https://developers.figma.com/docs/figma-mcp-server/write-to-canvas)
- [Code Connect requirements](https://help.figma.com/hc/en-us/articles/23920389749655-Code-Connect)
- [Figma for Education](https://help.figma.com/hc/en-us/articles/360041061214)
- [Config 2026 recap](https://www.figma.com/blog/config-2026-recap/)
- [DTCG 2025.10](https://www.designtokens.org/tr/2025.10/)
- [Material: sound in UI](https://m2.material.io/design/sound/applying-sound-to-ui.html)
- [Apple HIG: playing audio](https://developer.apple.com/design/human-interface-guidelines/playing-audio)
- [Vance et al. SOUPS 2019 (habituation)](https://www.usenix.org/conference/soups2019/presentation/vance)
- [Smashing: reduced motion](https://www.smashingmagazine.com/2021/10/respecting-users-motion-preferences/)
- [Motion sizes](https://motion.dev/docs/feature-comparison)
- [canvas-confetti](https://github.com/catdad/canvas-confetti)
- [ZzFX](https://npmjs.com/package/zzfx)
- [Rive runtime sizes](https://rive.app/docs/runtimes/runtime-sizes.md)

Animation:
- [Nintendo Ask the Developer Vol. 19](https://www.nintendo.com/us/whatsnew/ask-the-developer-vol-19-donkey-kong-bananza-part-1/)
- [GamesRadar on DK expressiveness](https://www.gamesradar.com/games/donkey-kong/donkey-kong-creator-shigeru-miyamoto-explains-the-big-apes-redesign-was-all-in-service-of-making-him-more-expressive)
- [Miyamoto on footstep weight](https://gonintendo.com/contents/51943-miyamoto-helped-shape-movement-in-donkey-kong-bananza)
- [Nintendo Life on Bananza idles](https://www.nintendolife.com/news/2025/08/random-donkey-kong-bananzas-idle-animations-are-outrageously-cute)
- [GameSpot: DK plays Switch when idle](https://www.gamespot.com/articles/donkey-kong-plays-nintendo-switch-when-you-go-idle/1100-6458188/)
- [SmashWiki idles](https://www.ssbwiki.com/List_of_idle_poses_(SSB4))
- [Overwatch GDC talk summary](https://evasokolova.wordpress.com/2016/04/03/gdc-overwatch-animation-talk-summary/)
- [AnimSchool on idles](https://blog.animschool.edu/2024/06/14/breathing-life-into-idle-animations)
- [three.js makeClipAdditive](https://discourse.threejs.org/t/how-to-use-the-makeclipadditive-method/18419)
- [Blender 5.0 API change log](https://docs.blender.org/api/5.0/change_log.html)
- [Mesh2Motion](https://github.com/mesh2motion/mesh2motion-app)
- [Cascadeur plans](https://cascadeur.com/plans)

VFX and SFX:
- [VFX Apprentice timing](https://www.vfxapprentice.com/blog/the-soul-of-effects-what-is-timing-in-vfx)
- [VFX style guides](https://www.vfxapprentice.com/blog/creating-vfx-style-guides-for-games)
- [GDC stylized VFX](https://gdcvault.com/play/1024715/Art-Directing-VFX-for-Stylized)
- [Cuphead making-of](https://gamesradar.com/the-making-of-cuphead)
- [Codrops dissolve shader](https://tympanus.net/codrops/2025/02/17/implementing-a-dissolve-effect-with-shaders-and-particles-in-three-js/)
- [three.quarks](https://github.com/Alchemist0823/three.quarks)
- [ElevenLabs Sound Effects API](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert)
- [SFX v3](https://elevenlabs.io/blog/sfx-v3-for-developers)
- [Fish Audio emotion tags](https://docs.fish.audio/emotion-control/tts-emotion-and-control-tags-user-guide)
- [Cuphead sound interview](https://www.asoundeffect.com/cuphead-sound/)
- [CRI random containers](https://blog.criware.com/?p=3604)

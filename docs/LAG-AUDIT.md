# Monkey lag audit (2026-11-20)

The goal is less lag without losing any capability or beauty. This audit separates what was **measured in the cloud
container** (software rendering, 4 CPU cores, no GPU) from what **only the Dell can measure**. Numbers marked
"swiftshader" come from software rendering: use them to compare things with each other, not as Dell timings.

## What's measured

| Area | Measure | Value | Where |
|---|---|---|---|
| 3D scene | draw calls / triangles | 18 / 61.5k | container |
| 3D scene | skinned meshes / bones / morph meshes | 17 / 57 / 11 | container |
| 3D scene | shadow casters, shadow map | 12, 1024² PCF soft | container |
| 3D scene | shader programs at startup | 24 | container |
| 3D frame | animation + "alive layer" JS per frame | 0.11 ms | container |
| 3D frame | render per frame | 0.8 ms (swiftshader, 503×576 at DPR 1) | container |
| Startup | single-file UI (`index.html`, JS inlined) | 942 KB | container |
| Startup | `monkey.glb` | 7.5 MB (37 clips, an 818 KB JPEG plus 5 smaller textures) | container |
| Startup | longest main-thread block | 4.3 s (model decode + shader compile, swiftshader) | container |
| Startup | `import monkey.app` | 1.2 s (0.86 s of it is the Anthropic SDK) | container |
| Events | one level + visemes batch in the UI | 0.002 ms | container |
| Events | idle UI-bus calls per second | 0 after Milestone 4 (was about 30, into both windows) | container |
| Chat | appending one turn | 2.2 ms; the log keeps every message (604 DOM nodes after 300 turns) | container |
| Audio | speaker DSP (visemes + leveler) per 23 ms block | 0.16 ms | container |
| Voice turn | each stage from your last word to his first sound | **traced since Milestone 2; needs the Dell** | Check everything → Speed |
| GPU | GPU time per frame, idle vs talking; which GPU WebView2 uses | **needs the Dell** | — |
| STT | Whisper small.en on the Dell's CPU | **needs the Dell** (model download is blocked here) | — |

## Where the lag you feel comes from (ranked)

1. **The voice turn.** This is by far the biggest felt delay. Every stage now has a timestamp (Milestone 2 traces), but the real numbers need the Dell.
   - **Stages, from the code:**
     - the end-of-turn silence (1.4 s, plus 0.4 s for short utterances);
     - whole-utterance Whisper on the CPU;
     - a Haiku classifier call for requests the rules don't match;
     - memory recall;
     - Claude's first token;
     - waiting for a whole sentence;
     - Fish's first audio over HTTP.
   - **Plan:** Voice 2.0 (its own milestone plan).
2. **Startup.** One multi-second main-thread block while the 7.5 MB model decodes and 24 shaders compile. On a real GPU it's shorter, but it's still a visible hitch.
3. **GPU per frame.** Unmeasured on the Dell.
   - **What adds up:** the shadow pass (12 casters re-rendered every frame), antialiasing, up to 2× pixel ratio, and two WebViews drawing the same model when the companion is open.
   - **What's already done:** Milestone 4 cut idle and sleeping frames by half or more.
4. **Small but constant work.**
   - **The "shine" on buttons:** it animates `background-position`, which repaints every frame and can't run on the compositor.
   - **The chat log:** it never drops old messages.

## Plan (each item keeps every feature and the current look)

| # | Change | Expected gain | Beauty risk | Status |
|---|---|---|---|---|
| L1 | Render tiers: 30 fps idle, 15 asleep, 0 hidden, full while anything moves | idle GPU/CPU roughly halved | none (breathing and blinks look the same at 30 fps) | **done** (M4) |
| L2 | UI bus sends the mouth level only on change | zero idle `evaluate_js` | none | **done** (M4) |
| L3 | Compile shaders before the first frame (`renderer.compileAsync`), show the existing pose image until then | no first-frame hitch | none | next |
| L4 | Compress the model with meshopt (`gltfpack -cc`, keeps every clip and morph; textures as KTX2 at the same resolution) | 7.5 MB → est. 2–3 MB, faster decode | **check renders**: quantization is lossless to the eye at 14-bit positions, but compare before/after renders at normal size | next, with the Animation 2.0 renders |
| L5 | Shadow map refreshed every frame only in the full tier; every 2nd frame at idle | shadow pass halved at idle | none visible at 30 fps idle | next |
| L6 | Button shine as a transform on a pseudo-element (compositor) instead of `background-position` | no per-frame repaint | none (same sweep and timing) | **done** |
| L7 | Keep the last 200 chat messages in the DOM (older ones stay in history and "Earlier") | flat memory and layout cost | none | **done** |
| L8 | Import the Anthropic SDK after the window shows | about 0.9 s faster window | none | after Voice 2.0's warm-up work (the client is needed early for the first turn) |
| L9 | Pixel ratio: keep 2, but drop to 1.5 automatically only if the Dell shows GPU-bound frames | maybe 40% fewer pixels | **visible** softening; only if measured necessary, and switchable | waits for Dell numbers |
| L10 | Companion and main window: draw the full model in one window at a time when both are visible (the hidden one already draws nothing) | up to 2× GPU when both show | none | needs a Dell check of how often both are visible |

## Needs the Dell (add to Check everything)

- GPU time per frame per tier (WebGL timer queries), and which adapter WebView2 uses (Intel iGPU or RTX). WebView2 can ignore the high-performance hint.
- The turn trace's p50/p95 for "you stop → he speaks" and each stage (already collected; open Check everything → Speed).
- CPU contention: whether Whisper, Pocket TTS and the avatar slow each other down when they overlap.

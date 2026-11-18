# Making Monkey highly animated: plan (researched 2026-11-18)

> **Update (v0.3):** We went with the 3D route after all.
> - A rigged glTF model (57 bones, 45 shape keys including the 15 Oculus visemes, 12 animation clips) is now live in the app via three.js (`ui/src/avatar3d.ts`).
> - Lip sync uses a spectral viseme estimate computed in Python (`monkey/audio/visemes.py`).
> - The Rive pipeline below is optional now.
> - HeadAudio or Fish timestamps remain an upgrade path for sharper visemes.

## Where we are now (v0.2)
- Monkey is a hand-coded layered SVG (`ui/src/avatar.ts`).
- Already in place:
  - The mouth opens and closes with the loudness of his voice.
  - Blinking, breathing and head bobbing.
  - Arm poses for each state.
  - Emotes: a double-bicep flex with banana rain, a laugh and a shrug.
- It costs nothing and works today. What's missing is drawn quality, real mouth shapes and smooth deformation.

## Recommendation
**AI-generated 2D art → separated parts → rig in Rive → state machine → audio-driven visemes with HeadAudio.**

Why this route:
- **Proven:** Duolingo's characters lip-sync with Rive state machines.
- **Fits the app:** the Rive web runtime is MIT-licensed, has no royalties, and runs in our WebView2 window.
- **Mostly automatable:** in 2026 an AI agent can do most of the rigging. The Rive desktop editor (Early Access app, Windows/macOS) runs an MCP server that can create bones, state machines and view models.
- **Real lip sync from Fish audio:** HeadAudio (MIT) turns any audio stream into the standard 15 visemes in the browser. It needs no transcript or timestamps.

## Steps

| # | Step | Tool / model | Who | Cost |
|---|------|--------------|-----|------|
| 1 | **Concept and model sheet:** front view, ¾ view, 8 expressions | Nano Banana 2 (Gemini 3.1 Flash Image) for exploring. Nano Banana Pro for the final sheet: it tied for the top character-consistency score in IMG.LY's Oct 2026 benchmark | Agent generates; **you pick** | ~$0.07 per image exploring, ~$0.13 per final |
| 2 | **Separate parts** on transparent PNGs: head, muzzle, eyes (open, half, closed), brows, torso, upper and lower arms, fists, open hands, tail, banana. Plus a sheet of 9 mouth shapes (Rhubarb's A–H plus X) | GPT Image 2 with `background:"transparent"` (preview feature), using the model sheet as the reference image. Alternative: Qwen-Image-Layered on fal ($0.05), which splits one image into RGBA layers but isn't designed for body parts | Agent generates, trims and aligns; **you approve** and touch up hidden areas | $0.05–0.21 per part, ~$10–20 total |
| 3 | **Rig** with bones and mesh deformation for the arms, chest and head turn | Rive desktop editor, driven by the agent over Rive's MCP server. Also: the Rive CLI with "RML" text files compiles `.riv` headlessly (technical preview) | You install Rive and approve the MCP connection. The agent builds the rig, and you tweak weights by eye | Free plan works (Rive splash screen, 50 publishes per month). $9–17/mo to remove the splash |
| 4 | **State machine** through a data-binding view model. Values: `mode` (idle, listen, think, talk), `viseme`, `jaw`, `lookX` and `lookY`. Triggers: blink, flex, laugh, celebrate, shrug, facepalm | Rive state machine plus our app code, which randomizes blinks, glances and fidgets | Agent | $0 |
| 5 | **Lip sync:** Fish PCM → audio worklet → HeadAudio visemes → map the 15 visemes to 9 cartoon mouths. Loudness still drives the jaw. Delay the audible signal ~100 ms so the mouth lines up | HeadAudio (MIT). Optional upgrade: Fish's `/v1/tts/stream/with-timestamp` endpoint, which gives text alignment for more accurate visemes | Agent | $0 |
| 6 | **Integrate.** Serve the UI from pywebview's localhost server (audio worklets need a secure context, so not `file://`). Swap `avatar.ts` for a Rive canvas behind the same `setState`, `setLevel` and `emote` API, and keep the SVG as a fallback | `@rive-app/canvas` (web runtime) | Agent | $0 |
| 7 | *(Optional)* **Big cinematic emotes** as short clips, such as a victory dance or a banana-peel slip | Veo 3.1 Lite via OpenRouter (~$0.05 per second), then ffmpeg to a sprite sheet | Agent | ~$5 |

**Estimated total:** about $15–45 one-off, plus $0–17 a month if you want Rive without the splash screen.

## Is OpenRouter the right hub?
- **Images and video: yes, as one convenient key.**
  - Images: Gemini (Nano Banana), GPT Image, FLUX, Seedream, Recraft (including SVG) and Qwen-Image.
  - Video since April 2026: Veo, Seedance, Wan and Grok.
  - It charges a 5.5% fee when you buy credits.
- **It doesn't cover everything:**
  - No image-to-3D.
  - Some specialist models are elsewhere. Qwen-Image-Layered and Hunyuan3D are on **fal.ai**.
  - New parameters (like GPT Image 2's transparent background) reach the **direct vendor APIs** first.
- **Best mix:** OpenRouter for exploring, then the direct Google/OpenAI APIs (or fal) for the final asset runs.

## Routes considered and not chosen
- **Live2D Cubism:** great results and free for individuals; the PRO student license is $46 for 3 years. But rigging is mostly manual work in the editor, and the AI layer-splitters are anime-focused.
- **Spine:** the $69 Essential tier has no meshes, Pro is $369, and interaction logic lives in your code.
- **3D (Meshy/Tripo → auto-rig → three.js):** auto face rigs aren't solved yet, and talking needs 52+15 blendshapes. High effort, and it loses the 2D cartoon look.
- **Real-time talking-avatar video (Hedra Live, Tavus, HeyGen):** billed per minute, so an always-on idle avatar gets expensive. Cartoon support is unverified, and local LivePortrait failed to find a face in line art.

## Risks
- Parts generated separately can drift in style or scale, and hidden areas need inpainting.
- Rive's MCP server and CLI are new and may be missing features.
- Lip sync from audio alone is approximate. It's good enough for a cartoon, and Fish's timestamps can sharpen it later.

## What I need from you to start
1. **Pick the look.** I'll generate 8–12 concept options (about $1) once there's an image API key: OpenRouter, Google AI or OpenAI.
2. **Install the Rive desktop Early Access app**, sign in, and turn on its MCP server, so I can drive it.

Then I build steps 2–6 and keep the current SVG Monkey as the fallback.

## Sources
- [Duolingo: character visemes](https://blog.duolingo.com/world-character-visemes/)
- [Rive MCP docs](https://rive.app/docs/editor/ai/mcp)
- [Rive CLI](https://rive.app/docs/cli/overview)
- [Rive vs Spine](https://rive.app/rive-vs-spine)
- [Rive pricing](https://rive.app/pricing)
- [HeadAudio](https://github.com/met4citizen/HeadAudio)
- [TalkingHead](https://github.com/met4citizen/TalkingHead)
- [IMG.LY consistency benchmark](https://img.ly/ai-benchmarks/findings/consistency/)
- [GPT Image 2 transparent backgrounds](https://the-decoder.com/openais-gpt-image-2-can-now-generate-images-without-a-background/)
- [Qwen-Image-Layered on fal](https://fal.ai/models/fal-ai/qwen-image-layered)
- [OpenRouter video generation](https://openrouter.ai/blog/video-generation)
- [Fish TTS with timestamps](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech-stream-with-timestamps)
- [Live2D license](https://www.live2d.com/en/sdk/license/)
- [Spine pricing](https://esotericsoftware.com/spine-purchase)

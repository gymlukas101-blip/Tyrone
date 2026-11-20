# Sound-off playtest

**Question:** with the sound muted, can you tell what just happened?

`python -m tools.playtest.sound_off` drives the real built UI (demo mode, audio muted) through 18 moments that make a sound or change state. For each, it checks two things:
- **Screen:** pixels that changed outside the 3D avatar, minus the background motion measured over the same 600 ms just before.
- **Avatar and feedback:** whether Monkey visibly reacted (a state change, an emote, an effect), or a feedback cue appeared (a badge, a stage flash, a label pulse).

Random idle fidgets are switched off during the measurement, so every reaction comes from the event itself.

| | Moments that read with the sound off |
|---|---|
| Before | **15 of 18**. Missing: the slow-reply "hmm", memory saved, mic reconnected |
| After | **18 of 18** |

## What was added (`ui/src/feedback.ts`)

The cues use one small vocabulary, kept sparse and on-theme:
- **pop:** a badge that springs up above Monkey's head and fades;
- **flash:** a glow around the stage edge;
- **shake:** a short shake;
- **pulse:** a bump on the status label.

With "reduce motion" on, they fade in and out without scaling or shaking.

| Moment | Before (sound off) | Now |
|---|---|---|
| Slow reply: soft "hmm" | nothing | 💭 "Hmm…" badge |
| Memory saved | nothing (unless technical details were on) | 🧠 "Remembered" / "Updated" / "Forgotten" badge |
| Mic reconnected | the small hint line changed | 🎙 "Mic back" badge |
| He heard you (end of your turn) | a subtle pose change | 👂 "Got it" badge + label pulse |
| "Monkey, stop" | looked the same as him finishing | ✋ "Stopped" badge + shake (the backend now sends a `stopped` event) |
| Conversation over | a chip quietly disappeared | 👋 "Talk soon" badge |
| Didn't catch that | a chat line | ❓ badge |
| Error / warning | a chat line | red / amber stage flash (+ shake for errors) |

## Found along the way

The Today view's tab bar showed over the chat while Today was closed. Its CSS `display: flex` beat the `hidden` attribute. Fixed on the flagship branch, with a regression test.

## Test

`tests/test_sound_off.py` runs the playtest and fails if any moment stops reading. It runs in the browser-UI CI job.

# Facial animation tests

How to check that Animation 2.0 behaves, and what each check proves.

## Automated

| Test | Where | Proves |
|---|---|---|
| eases the same at 15, 30, 60 and 144 fps | `ui/test/face.test.ts` (Vitest) | Timing doesn't depend on the monitor or render tier |
| lips meet on M/B/P even while smiling | same | A closure wins over a lip-parting mood |
| a smile tints speech instead of fighting it | same | Mouth moods scale down while talking |
| vowel shape and jaw don't double-count | same | Open vowels no longer over-open |
| asymmetric brows survive speech | same | Acting reads during dialogue |
| an interrupt clears the mouth at once; overrides (blink, yawn) win | same | No stale mouth shape after a barge-in |
| silence while idle leaves no jitter | same | No twitching at rest |
| approach is exact at dt=0 and converges | same | The easing math |
| reads intent from the words, not loudness | same (director) | Cues come from text |
| anticipates, hits, holds, then settles; one reaction at a time with a cooldown | same | Phasing and restraint |
| states have a resting attitude and a new state drops a stale reaction | same | No leftover looks |
| syllables follow the spelling closely enough for the eye | `tests/test_lipsync.py` | Text → syllable parsing |
| each new syllable burst advances and closures land in the gap | same | Audio timing drives the sequence |
| blend keeps closures and audio texture | same | A closure is never diluted |
| speaker uses the sentence text and forgets it on stop | same | No stale words drive the next reply |

Run them with:

```bash
cd ui && npx vitest run
.venv/bin/python -m pytest -q tests/test_lipsync.py
```

## Visual (renders on the real model)

```bash
python -m tools.anim.face_sheet face.png          # held poses, old vs new face close-ups
python -m tools.anim.dialogue_demo demo_out/      # 15 s acted dialogue, side by side, with audio
```

Both need the UI built (`cd ui && npm run build`), Chromium (Playwright), and `espeak-ng` + `ffmpeg` for the demo. Keep the outputs out of the repo.

## Manual, on the Windows PC (not yet done)

1. Talk to Monkey normally. Watch that M/B/P close the lips, and that the mouth doesn't chatter or lag behind the voice.
2. Ask something that makes him say "actually" or "whoa": he should get one readable reaction, not a reaction on every sentence.
3. Barge in mid-sentence ("Monkey, stop"): the mouth should close at once.
4. Compare with `?face=baseline` (a dev build URL flag) if something looks worse.
5. Check on a high refresh-rate monitor: the mouth speed should look the same as at 60 Hz.

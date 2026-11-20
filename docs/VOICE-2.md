# Voice 2.0: faster, more natural turns (first vertical slice)

Merged to `main` on 2026-11-20 at the owner's request. Everything below ran in the cloud container; **nothing here has
been heard on the Dell yet.** To fall back to the old endpointing, set `early_commit` to false in settings (`fish_latency` already defaults to "balanced", the old behavior).

## 1. Audit: what the code did (confirmed from source)

| # | Concern from the brief | What the code did | Now |
|---|---|---|---|
| 1 | 1,400 ms end-of-turn silence | Fixed `END_SILENCE_PRESETS["normal"]` (`audio/endpoint.py`) | Still the fallback; **early commit** ends finished thoughts after 0.48–0.88 s |
| 2 | +400 ms for short utterances | `short_extra_ms` when under 1.5 s of speech | Kept for the fallback rule, skipped by early commit |
| 3 | Whole-utterance Whisper | Transcribed only after the turn ended | Transcribed **during the pause**; at the end of the turn it's done (or the in-flight run is reused) |
| 4 | Haiku classifier on unmatched requests | Every unmatched request waited on it (cap 4 s) | **Voice skips it** unless the request looks like thinking work (`_NEEDS_THOUGHT`) |
| 5 | Per-turn memory recall | Every message | Gated by task since Milestone 5 (tens of ms, local) |
| 6 | Chunker: 24 chars and a sentence end | First audio waited for a whole sentence | The **first clause** may go early (4+ words, at a comma) |
| 7 | Fish HTTP streaming, `latency="balanced"` | A **new HTTPS connection per sentence** | One kept-alive connection; balanced kept |
| 8 | TTS queueing / interrupt | Fixed in Milestone 2 (generations, close on stop) | Plus reply-tagged audio, so stale markers can't end the next reply |
| 9 | Single-worker executor | One worker; the agent lock held for the whole turn | Kept (ordering), but a cancel no longer waits on a tool or a silent stream |
| 10 | Long-held locks, slow cancel | A cancel was only seen between streamed events or after a tool returned | The stream is **closed on cancel**; tools run on a bounded pool and are abandoned on cancel |
| 11 | Real audio vs UI "speaking" | Fixed in Milestone 2 (ordered notify, audible-time marks) | — |
| 12 | Caching / warm-up / escalation | 1 h system-prompt cache, Whisper warm-up, `escalate` tool | Unchanged |
| 13 | CPU contention (Whisper, Pocket, avatar) | Not measured | Render tiers (M4) lower the avatar's share; **needs the Dell** |

## 2. Latency: before and after (voice benchmark)

`python -m tools.voice_bench` runs the app's real decision code over 10 spoken turns:
- the endpointer and early commit;
- the router and the fast voice path;
- the sentence chunker.

Vendor timings are **assumptions**: Whisper on a laptop CPU, Claude's first token, and Fish's first audio cold (0.70 s) or kept-alive (0.45 s). The assumed values are printed with every report. Replace them with the Dell's real numbers using `--from-traces <%APPDATA%\Monkey\traces>`.

```
turn                       base    now   end-of-turn  stt after  route 1st tok 1st piece  voice
question                   4.10   2.34   1.84→1.04 0.56→0.00   0.05    0.55 0.30→0.15 0.80→0.55
command                    3.84   2.31   1.84→1.04 0.48→0.00   0.05    0.55 0.12→0.12 0.80→0.55
quick fact                 4.88   2.37   1.84→1.12 0.59→0.00   0.05    0.55 0.25→0.10 0.80→0.55
mid-thought pause          3.81   2.65   1.44→1.28 0.75→0.00   0.05    0.55 0.22→0.22 0.80→0.55
breath between clauses     4.25   2.93   1.44→1.28 0.77→0.00   0.05    0.90 0.28→0.15 0.80→0.55
long question              4.59   3.22   1.44→1.44 1.10→0.18   0.05    0.90 0.30→0.10 0.80→0.55
thinking task              4.28   2.96   1.44→1.28 0.74→0.00   0.05    0.90 0.35→0.18 0.80→0.55
thanks                     3.07   1.51   1.84→0.96 0.43→0.00   0.00    0.00 0.00→0.00 0.80→0.55
opinion                    4.57   2.40   1.44→1.12 0.63→0.00   0.05    0.55 0.30→0.13 0.80→0.55
chat                       4.73   2.34   1.84→1.04 0.54→0.00   0.05    0.55 0.15→0.15 0.80→0.55

p50: 4.26 s → 2.39 s   p95: 4.81 s → 3.10 s
(after starting the pause transcription at 320 ms instead of 480, per the research: p50 2.23 s, p95 2.94 s)
cut-offs during mid-thought pauses: 1 → 0
classifier calls on the critical path: 3 → 0
```

How to read this:
- **"Base" didn't just wait longer, it cut the user off.** In the "mid-thought pause" turn ("Remind me to call…", a 1.6 s pause, "…my mom at five"), the old fixed rule ended the turn during the pause. The new rule hears that "to call" expects more and waits.
- **The total gain is about 1.9 s at the median.** About 0.8 s comes from the end of turn, 0.5 s from transcribing during the pause, 0.25 s from the kept-alive connection, and 0.1–0.2 s from the early first clause. The classifier skip adds 0.8 s more on unmatched requests.
- **The p95 turn is the long question.** Transcribing 4 s of audio takes longer than the pause, so the normal rule ends the turn and reuses the in-flight transcription.

Against the brief's proposed targets (to validate on the Dell):
- **Under 1.5 s median first audio for simple turns:** not met in the model (2.3–2.4 s). The remaining time is mostly Claude's first token, TTS first audio and the end of turn. The next step is streaming TTS and a semantic turn model (see §5).
- **Under 250 ms from interrupt to silence:** the Milestone 2 tracer records it, and the speaker stops within one audio block plus output latency (tested with fake streams, not measured on the Dell).
- **No increase in false turn endings:** in the benchmark, 1 → 0 cut-offs. A real-speech evaluation (pause and filler recordings) still needs the Dell or recorded samples.

## 3. What's implemented (tests in `tests/test_voice2.py`, 15)

- **Early commit** (`audio/turn.py`, `audio/listener.py`):
  - At a 480 ms pause, the audio so far is transcribed in the background.
  - Questions and short clear answers end the turn at 0.48 s; finished statements at 0.88 s.
  - Endings like "to call…", "and", "um", "no wait" or a trailing comma get +640 ms.
  - Talking again makes the pause's transcript stale.
  - If the normal rule ends the turn first, the running transcription is reused (one Whisper run per turn).
  - Setting: Settings → "Answer sooner when I've clearly finished" (on by default).
- **Fast voice routing** (`brain/router.py`): unmatched voice requests go straight to the general model; ones that look like thinking work (design, debug, plan, essay, research…) are still classified. Typed requests are unchanged. Offline, on the routing bench: 10 of 14 classifier calls skipped, with 0 model mismatches.
- **Speech generation:** one kept-alive Fish connection for all sentences and turns, and an early first clause. Later sentences keep whole-sentence prosody.
- **Soft-timeout acknowledgment:**
  - If no reply audio has started 1.5 s after the turn ends, Monkey plays one short "hmm" from his own vocal kit (and nothing if there is no kit).
  - It uses no words and claims nothing.
  - It's skipped once any reply audio is on its way, and it never delays the reply.
- **Barge-in and concurrency:**
  - A cancel closes a stream that's still waiting for Claude.
  - Tools run on a bounded pool (3 threads), and a cancel stops waiting for them; a late result is discarded.
  - History stays valid (the user turn gets an assistant reply).
  - A cancelled reply can't hand a sentence to the speaker (cancel and speak share a lock).
- **Measurement:** the Milestone 2 turn tracer records every stage on the Dell, and `tools/voice_bench.py` gives before/after comparisons from the app's real decision code.

## 4. Not verified, needs the Dell

- Real Whisper, Claude and Fish timings (the benchmark uses assumptions; the turn traces will hold the real ones).
- How early commit feels with real speech, background noise and other people talking. False early endings should be watched for in Check everything → Speed and the traces' corrected-next-turn rate.
- That the soft "hmm" plays at a sensible volume and only when he's genuinely late.
- CPU overlap between the pause transcription, Pocket TTS and the avatar.

## 5. Next highest-value step

Stream Claude's text into Fish over its WebSocket API (the research is in `docs/research/VOICE-2-REFERENCES.md`), so the first audio starts from the first words, not the first clause. Then try a small local semantic turn-detection model to replace the word lists in `turn.py`, measured against the same benchmark plus real recordings. Deepgram Flux stays an optional, paid experiment and needs your approval.

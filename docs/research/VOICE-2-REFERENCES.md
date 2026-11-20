# Voice 2 references: low-latency turn-taking and TTS (2026-11-20)

Research only, no code changed. The question: what would make "you stop → Monkey speaks" audibly faster, beyond
Voice 2.0 (early-commit endpointing, no classifier on voice turns, an early first clause, a kept-alive Fish
connection, a 1.5 s "hmm", cancellable streams).

**Source tags** (every vendor claim carries one):
- **[R]**: read directly from the vendor's public GitHub repo, cloned on 2026-11-20.
- **[S]**: the official page was found by web search, but this session could not fetch it. `openai.com`,
  `developers.openai.com` and `docs.livekit.io` failed DNS under the session's network allowlist, so the other
  vendor sites were not tried either. The text is a search-engine summary of that page: **treat it as
  unverified** and re-read the page before relying on a number.
- **[A]**: my own analysis or estimate, not a vendor claim.

## 0. Where Monkey's time goes today

`python -m tools.voice_bench` (2026-11-20). The vendor timings in it are **assumed defaults, not measurements**
(see `tools/voice_bench.py`):

| Segment | Now (bench) | What sets it |
|---|---|---|
| End of turn (last word → turn ends) | 0.96–1.44 s | `EARLY_MS`=480 ms pause, **then Whisper on that audio** (0.25 s + 0.18 s per audio second, assumed). Commit waits for the transcript. |
| Route | 0.05 s | fast path, no classifier |
| Claude first token | 0.55–0.90 s | model tier |
| First speakable piece | 0.10–0.22 s | `SentenceChunker` early clause |
| Fish first audio + device | 0.55 s | 0.45 s warm (assumed) + 0.10 s output |
| **Total p50 / p95** | **2.39 / 3.10 s** | baseline before Voice 2.0 was 4.26 / 4.81 s |

[A] The biggest segment is still end-of-turn. In the bench, end-of-turn ≈ 0.48 s + Whisper time. For a
"question", 1.04 s = 0.48 s pause + 0.56 s Whisper. So the silence policy is no longer the main cost: the
*transcription that the policy waits for* is. Claude's first token comes second.

## 1. Comparison

| Technology | What it contributes | Latency, vendor-stated | Independent / caveats | Cost | Where it runs | Fit for Monkey [A] |
|---|---|---|---|---|---|---|
| **OpenAI GPT-Live / Realtime** ([post](https://openai.com/index/continuous-voice-interaction-with-gpt-live/), [guide](https://developers.openai.com/api/docs/guides/voice-agents)) | GPT-Live: a full-duplex speech-to-speech model with no turn detector in the audio path; tools run behind an async boundary [S]. The guide offers three paths: GPT-Live, Realtime, or a chained STT→agent→TTS pipeline [S]. `semantic_vad` eagerness low/medium/high has max timeouts of 8/4/2 s [S]. | No figures obtained (pages not fetched) | None found for GPT-Live [S] | API usage | Online | **Ideas only.** It would replace Claude, the cloned Fish voice and the approval gate. Monkey is the "chained" design. |
| **OpenAI voice infra** ([post](https://openai.com/index/delivering-low-latency-voice-ai-at-scale/)) | WebRTC split into a stateless UDP relay and a stateful transceiver. "WARP" cuts setup from 6 round trips to 1; "Instant Connect" pre-negotiates [S]. | Not obtained | n/a | n/a | Server side | **No.** This solves a server-scale problem. The takeaway for Monkey: set up connections before they are needed. |
| **LiveKit turn handling** ([tuning](https://docs.livekit.io/agents/logic/turns/tuning/); source [`voice/turn.py`](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/turn.py)) | Endpointing `min_delay` 0.5 s, `max_delay` 3.0 s (0.3 / 2.5 s with a streaming detector). Preemptive generation is **on** by default: LLM only, `preemptive_tts` off, skipped for turns over 10 s of speech, at most 3 tries per turn. False interruptions resume after 2.0 s, with `min_duration` 0.5 s [R]. Metrics: `end_of_utterance_delay`, `transcription_delay`, `ttft`, `ttfb` [R]. | One user saw the turn detector add only ~55 ms; the rest was waiting for the STT final [S, forum] | Framework is Apache-2.0 | Free | Local or cloud | **Patterns, yes; framework, no.** Copy the preemptive-generation limits and the metric names. |
| **LiveKit turn-detector model** ([page](https://docs.livekit.io/agents/logic/turns/turn-detector/); [plugin](https://github.com/livekit/agents/tree/main/livekit-plugins/livekit-plugins-turn-detector), [MODEL_LICENSE](https://github.com/livekit/agents/blob/main/MODEL_LICENSE)) | Text end-of-utterance model (`livekit/turn-detector`, `model_q8.onnx`, last 6 turns / 128 tokens, CPU onnxruntime). The plugin is now deprecated for an audio `TurnDetector` whose local `v1-mini` uses ~450 MB RSS. Needs <500 MB RAM [R]. | Older docs: multilingual Qwen2.5-0.5B, 396 MB, ~50–160 ms per turn [S] | — | Free | Local CPU | **Not usable.** The license says you may not use the models "on a standalone basis or with any frameworks other than LiveKit Agents" [R]. |
| **Pipecat Smart Turn v3.2** ([repo](https://github.com/pipecat-ai/smart-turn)) | Audio-only (prosody) end-of-turn classifier. Whisper-Tiny backbone, ~8M params, int8 CPU ONNX of **8 MB**. Takes 16 kHz audio, up to 8 s. 23 languages. Meant to run after a VAD detects silence [R]. | "as little as 10 ms on some CPUs, under 100 ms on most cloud instances"; ~65 ms on Pipecat Cloud [R] | 12.6 ms on a c7a.2xlarge ([Daily blog](https://www.daily.co/blog/announcing-smart-turn-v3-with-cpu-inference-in-just-12ms/), [S]) | Free, **BSD-2-Clause** [R] | Local CPU | **Good candidate** for a local semantic turn model. See R5. |
| **Deepgram Flux** ([quickstart](https://developers.deepgram.com/docs/flux/quickstart), [eager EOT](https://developers.deepgram.com/docs/flux/voice-agent-eager-eot), [config](https://developers.deepgram.com/docs/flux/configuration)) | Streaming STT with turn detection built in (`/v2/listen`, `flux-general-en`). Events: `EndOfTurn`, `EagerEndOfTurn`, `TurnResumed`. `eot_threshold` defaults to 0.7. `eager_eot_threshold` ranges 0.3–0.9, is unset by default, and must be ≤ `eot_threshold`. The eager transcript equals the final one unless the turn resumes [S]. | ~260 ms end-of-turn, p50 at defaults. Eager arrives 150–250 ms earlier, but "can increase LLM API calls by 50-70%" [S] | Deepgram's own blog gives p90 ≈ 1 s and p95 ≈ 1.5 s [S]. Third-party "<300 ms median" is unverified. | ~$0.0065/min English, pay-as-you-go ([pricing](https://deepgram.com/pricing), [S]; a Deepgram blog says $0.016/min, so it conflicts) | **Online** | **Optional paid experiment.** See R6. |
| **Fish realtime ASR** `transcribe-stream-1` (Preview) ([docs repo](https://github.com/fishaudio/docs/blob/main/features/speech-to-text/realtime.mdx)) | Turn-by-turn STT with `eager_end_of_turn`, `turn_resumed`, `user_backchannel`, `agent_speaking` hints. Sessions up to 60 min [R]. | Draft ~0.5 s after speech starts. `eager_end_of_turn` ~0.6 s and `committed` ~1.1 s after the speaker stops, "measured on the production service with synthetic speech", before network [R] | — | $0.36 per *session* hour [R] | Online | **Not better than local today**: 0.6 / 1.1 s plus network, against Monkey's 1.0–1.3 s. Same key and vendor, though. |
| **Fish TTS WebSocket** ([AsyncAPI](https://github.com/fishaudio/docs/blob/main/api-reference/asyncapi.yml), [streaming guide](https://github.com/fishaudio/docs/blob/main/features/realtime-streaming.mdx), [best practices](https://github.com/fishaudio/docs/blob/main/developer-guide/best-practices/real-time-streaming.mdx)) | `wss://api.fish.audio/v1/tts/live`, MessagePack frames. Client sends `start`, `text`, `flush`, `stop`; server sends `audio`, `finish` [R]. | "Normal: ~500 ms", "Balanced: ~300 ms" [R]. `s2-pro` is listed with "100 ms time-to-first-audio" [R]. | `s2.1-pro-free` comes with "No TTFA or DPA guarantees" [R] | `s2.1-pro` $15 / M UTF-8 bytes. `s2.1-pro-free` $0, "fair-use limits" [R] | Online | **Experiment only.** See R7 (question a). |
| **fish-speech (self-host)** ([repo](https://github.com/fishaudio/fish-speech)) | Open S2 weights. S2-Pro has 4B params [R]. | "RTF 0.195 on a single H200, about 100 ms to first audio" [R] | — | Fish Audio Community License: free below $500k revenue; an assistant's own replies are not a "Hosted Service" [R] | GPU | **No.** 4B params is impractical on a laptop CPU. Pocket TTS stays the offline voice. |
| **ElevenLabs Agents / API** ([conversation flow](https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow), [latency](https://elevenlabs.io/docs/eleven-api/concepts/latency)) | Soft timeout (filler while the LLM is slow): off by default (-1), range 0.5–8 s, 3 s recommended, **once per turn**. Turn eagerness Eager/Normal/Patient. `turn_timeout` 1–30 s. `flush: true` at end of turn. "Speculative turn-taking" appears in blog posts only [S]. | Flash ~75 ms model inference only; ~100 ms median; the network adds 50–200 ms [S] | The numbers differ between pages [S] | Paid | Online | **Ideas only.** The voice is the cloned Fish voice. |
| **Sesame TurnBench** ([journal URL given](https://www.sesame.com/journal/turnbench); found as [blog](https://www.sesame.com/blog/turnbench), [site](https://turnbench.sesame.com/), [arXiv 2608.25218](https://arxiv.org/abs/2608.25218)) | Benchmark of end-of-turn and interruption detection on hand-labeled dual-channel human talk (30 h test, 104 h train). For end-of-turn, a **mid-turn pause** counts as a false positive. For interruptions, **backchannels**, noise and bleed count as false positives [S]. | Humans start the next turn a median **151 ms before** the turn ends. Systems need several hundred ms of silence [S]. | 14 systems compared [S] | Free | — | **Method, not code.** Score Monkey on its own labeled recordings the same way. |
| **isair/jarvis** ([repo](https://github.com/isair/jarvis)) | An LLM "intent judge" over the transcript and TTS history. **Echo suppression** by fuzzy-matching the transcript against what TTS just said (rapidfuzz) [R]. | — | — | **Custom non-commercial license** [R]: ideas only, no code | Local | Echo idea, for barge-in |
| **OpenJarvis** ([repo](https://github.com/open-jarvis/OpenJarvis)) | Apache-2.0. Pluggable speech backends: faster-whisper, Deepgram, Kokoro, Cartesia, ElevenLabs, OpenAI [R]. | — | — | — | Both | Nothing new for latency |

## 2. Recommendations, ranked

All gains are [A] estimates on top of today's 2.39 s p50. Every one should be checked with `voice_bench
--from-traces` on the Dell before and after.

| # | Change | Audible gain | Risk | Cost |
|---|---|---|---|---|
| 0 | Measure first: real Whisper, first-token and Fish timings from the Dell's traces | — (the gains below depend on it) | none | none |
| 1 | Start the speculative transcription at a shorter pause (480 → ~240–300 ms) | **0.15–0.25 s** on most turns | low | more CPU (one run at a time, already guarded) |
| 2 | A/B Fish `latency: "low"` (and `chunk_length`) on the existing HTTP path | 0–0.2 s, unknown | low | none (config) |
| 3 | Preemptive Claude on the speculative transcript: text only, held until commit | **0.1–0.5 s** on statements and trail-offs; more combined with #1 and #5 | medium | +LLM calls |
| 4 | Pre-warm Fish at the end of the user's turn (not only keep-alive) | 0–0.25 s when the connection idled out | low | none |
| 5 | Local Smart Turn v3 next to `turn.py` | 0.1–0.3 s, plus fewer cut-offs | medium | 8 MB model |
| 6 | Deepgram Flux, optional and paid | **0.5–0.9 s on paper** (biggest) | medium-high | ~$0.39/h streamed |
| 7 | Fish WebSocket streaming | ≈0–0.05 s on first audio; smoother long replies | medium | complexity |

**R1. Transcribe earlier.** Today the turn can't end until Whisper finishes on the 480 ms-pause audio, so
end-of-turn ≈ 480 ms + Whisper. Start the background transcription at ~250 ms of silence instead. Keep the
commit thresholds `commit_after_ms` 480/880 as they are, so the decision rule doesn't change: only the
transcript arrives sooner. A "question" would end at max(0.48, 0.25 + 0.56) ≈ 0.81 s instead of 1.04 s.
`pause_seq` already throws away transcripts made stale when you resume talking. The extra cost: more Whisper
runs that get discarded during breaths. CPU was single-flight already (`_spec_busy`).

**R2. Fish `latency: "low"`.** The OpenAPI schema's `latency` enum is `low | normal | balanced`, described
as "normal: best quality, balanced: reduced latency, low: lowest latency" [R]. The guides only mention normal
and balanced [R]. Monkey sends `"balanced"`. It's a one-field A/B; listen for quality loss on the cloned voice
and on `s2.1-pro-free`. `chunk_length` is 100–300, default 300 [R]. The WS examples use 100 [R]. That probably
matters little for a short first clause [A].

**R3 = (d) Preemptive generation.**
- How: when the pause transcript arrives and `completeness()` reads complete, start the Claude stream right
  away with the same prompt, which is already cache-controlled in `brain/agent.py`. Buffer its text and don't
  speak. On commit, release the buffered text into `SentenceChunker` and Fish. If speech resumes
  (`pause_seq` changes), cancel; the streams are already cancellable.
- What it gains: Claude's first token (0.55–0.9 s) overlaps with the remaining commit wait (0.88 s for
  statements, plus the trail-off extension). This is LiveKit's default behaviour (LLM only, not TTS; skipped
  when speech > 10 s; ≤ 3 tries per turn [R]). Deepgram makes the same trade [S].
- Cost: Deepgram warns of +50–70 % LLM calls with eager end-of-turn [S]. Monkey's rate should be lower,
  because it speculates only on "complete"-reading transcripts. Measure it. Cached input tokens make the
  repeats cheap; output tokens of discarded drafts are the waste. Cap it like LiveKit: no speculation when the
  utterance is > 10 s or after 3 tries.
- Correctness (the hard part): a speculative run must **never execute a tool**. If the model emits
  `tool_use` before commit, hold it until commit. Read-only tools are cheap, but outward actions already need
  the approval gate. Only the transcript that is finally committed may enter history and memory; a discarded
  draft must leave no trace. If the committed transcript differs from the speculated one (more words came),
  restart. Don't start Fish speculatively: it would cost credits and could leak audio.

**R4. Pre-warm Fish per turn.** Fish recommends to "keep the connection warm for back-to-back generations"
[R]. httpx keeps the connection for 120 s, but the server may close it sooner [A]. At speech end, fire a
cheap request on the pooled client so the TLS session is live when the first clause arrives. The bench
assumes 0.25 s between a cold and a warm connection. **Unverified**: no cheap no-op Fish endpoint was checked.

**R5 = (b) A local semantic turn model.**
- LiveKit's models are ruled out by their license (LiveKit Agents only) [R]. The local `v1-mini` is also
  heavy (~450 MB RSS) [R].
- **Smart Turn v3.2 fits**: 8 MB int8 ONNX, ~8M params, BSD-2, 10 ms to <100 ms on CPU [R]. onnxruntime is
  already present through faster-whisper [A].
- Input: the last ≤ 8 s of 16 kHz turn audio, zero-padded at the front [R], as Whisper log-mel features. Use
  faster-whisper's own numpy `FeatureExtractor` instead of adding `transformers` [A, **unverified** that the
  features match exactly].
- Use it at the same early pause as R1, combined with `turn.py`:
  - both say done → commit at transcript time;
  - audio says "not done" → extend, like a trail-off;
  - they disagree → today's rule.
- It reads prosody (a falling vs rising tone), which the word lists miss and which Whisper's punctuation
  only approximates.
- Risk: false commits. Gate it behind a setting and score it TurnBench-style on recorded turns: mid-turn
  pauses that cut you off vs extra wait.

**R6 = (c) Deepgram Flux as a paid experiment.**
- What it would replace: local Whisper, the silence endpointer, `turn.py` and speculative transcription,
  while you are recording. The wake word, local VAD, the barge-in stop keywords and the offline Whisper
  fallback stay.
- How: stream 16 kHz PCM to `/v2/listen` (`flux-general-en`). Commit on `EndOfTurn`. With
  `eager_eot_threshold` set, run R3 on `EagerEndOfTurn` and cancel on `TurnResumed` [S].
- Expected gain: ~260 ms to end-of-turn (p50) against ~1.0–1.3 s now (bench) → 0.6–0.9 s. The vendor's own
  p95 is ~1.5 s [S], so the tail improves less.
- Cost: billed only while streaming. 30 min a day ≈ $0.20/day ≈ $6/month at $0.0065/min [A, using [S]
  pricing].
- Risks: online only, a third party hears all speech, a new dependency.
- Per CLAUDE.md this is **spending money**: ask the owner first. The key goes through the secure form and
  DPAPI.
- Fish's own `transcribe-stream-1` is the same price class but is documented slower (0.6 / 1.1 s) [R], so
  try it only if Flux is unavailable.

**R7 = (a) Fish WebSocket vs per-sentence HTTP with keep-alive.** Verdict: **not worth it for first-audio
latency; worth a flagged experiment for smoother multi-sentence replies.** Why [A]:
- First audio still waits for a first clause either way. The server buffers text "according to the
  chunk_length" until it is flushed [R], so you'd flush at the same early-clause boundary `SentenceChunker`
  already uses. The only saving is per-request overhead on an already-warm connection (tens of ms).
- Gaps between sentences are already hidden: `speaker.py` synthesizes the next sentence while the current
  one plays.
- WS is worse on setup: the plain `/v1/tts/live` channel says "The WebSocket connection will close after
  this event" (`finish`) [R]. That means a fresh TCP + TLS + upgrade per reply, unless the socket is opened
  ahead. The timestamped channel instead says you "can send another StartEvent on the same connection" [R].
  The two are inconsistent; verify by test.
- An open socket probably holds a concurrency slot. The Starter tier allows 5 concurrent requests [R]. Fish
  states the slot rule for realtime ASR; for TTS it is unverified.
- Real benefits: one synthesis context per reply (`condition_on_previous_chunks`) instead of independent
  per-sentence clips, so prosody is more even [A, inferred from the parameter name], and fewer requests on
  long answers.

If built, use exactly the documented protocol [R]:
1. **Connect** to `wss://api.fish.audio/v1/tts/live` with headers `Authorization: Bearer <key>` and
   `model: s2.1-pro-free` (or the paid id). The free model is in the WS model enum, so it works over WS on
   paper [R]. Unknown model ids fall back to paid `s2.1-pro` [R], the same trap as HTTP. Open it at
   speculative-transcript time, not at the first token, to hide the handshake.
2. **Start**: `{"event":"start","request":{"text":"","reference_id":<voice>,"format":"pcm","sample_rate":TTS_RATE,"latency":"balanced","chunk_length":100,"normalize":true}}`.
   Every frame is msgpack (`ormsgpack`/`msgpack`: a new dependency; `websockets` is already one).
3. **Text**: for each `SentenceChunker` piece, send `{"event":"text","text":piece+" "}`. Send
   `{"event":"flush"}` after the first piece, then after each sentence (or let the server buffer later pieces
   for better prosody).
4. **Stop**: at the end of the reply, send `{"event":"stop"}` ("note 'stop', not 'close'") [R].
5. **Receive**: read concurrently. Sending everything first "can stall on flow control" [R].
   - `{"event":"audio","audio":bytes}` → int16 PCM, with the same leftover-byte handling as `stream_pcm`.
   - `{"event":"finish","reason":"stop"|"error"}` ends the reply. Ignore unknown events [R].
6. **Barge-in**: there is no documented cancel event, so close the socket [A].
7. **Fallback**: an error before the first audio → per-sentence HTTP → Pocket.

This needs a per-reply engine API in `speaker.py` (begin / feed / end) instead of `stream_pcm(sentence)`.
That is the main cost and the reason it ranks last.

**Also worth keeping or adopting (small):**
- The soft "hmm": keep 1.5 s and keep it **once per turn**. ElevenLabs recommends 3 s, once per turn [S].
  Fillers shouldn't promise a time frame [S].
- Name trace fields like LiveKit's: `end_of_utterance_delay`, `transcription_delay`, `ttft`, `ttfb` [R].
- Report p50 and p95, and change one factor at a time (OpenAI's guidance [S]).
- jarvis-style echo suppression (drop transcripts that fuzzy-match what Monkey just said), if open-mic
  barge-in is ever added. Today barge-in is the wake word or a stop keyword.

## 3. Impractical for Monkey, and why [A]
- **Full-duplex speech-to-speech (GPT-Live, Realtime)**: it would replace Claude, the cloned voice, memory
  injection and the approval gate with another vendor's model. It's also online only.
- **LiveKit turn-detector models**: the license forbids use outside LiveKit Agents [R]. Adopting the whole
  framework (rooms and WebRTC) for one desktop user is out of proportion.
- **Self-hosted fish-speech S2**: 4B params, benchmarked on an H200 [R]. Not CPU-feasible.
- **Preemptive TTS**: LiveKit leaves it off by default [R]. It would spend Fish credits and fair-use quota on
  discarded audio, for ~0.3 s more.
- **WebRTC / edge-relay work** (OpenAI's infra posts): server-side scale problems. Monkey makes one HTTPS
  call per reply.
- **Running TurnBench itself**: dual-channel conversational corpora don't match wake-word commands. Borrow
  the false-positive definitions only [S].
- **ElevenLabs voices / Agents platform**: a hosted agent stack and a different voice. Only its settings ideas
  carry over.
- **Fish realtime ASR as the turn detector**: documented 0.6 / 1.1 s plus network, no faster than local [R].

## 4. Not verified here
- Every [S] item. The OpenAI, LiveKit-docs, Deepgram, ElevenLabs and Sesame pages could not be fetched from
  this session: allow those hosts (or read them by hand) before acting on a number.
- Fish: whether `latency:"low"` works on `s2.1-pro-free`; whether `/v1/tts/live` really allows one reply per
  socket; whether a TTS WebSocket holds a concurrency slot while idle.
- Smart Turn: whether faster-whisper's feature extractor reproduces the training features; its real latency
  on the Dell CPU.
- All Monkey timings in §0 are `voice_bench` assumptions until replaced by traces.

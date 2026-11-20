# Donkey Kong Bananza as animation reference: analysis and status

## Source inspection status (honest)

| Source | Status | Why |
|---|---|---|
| All DK & Pauline Idle Animations (Zephiel810), youtu.be/1D4PNOI1_SI | **unavailable**: not watched | youtube.com and i.ytimg.com are blocked from this cloud container. Downloading with a ripper would break YouTube's terms, which the brief rules out. |
| Full Movie, All Cutscenes (Sirloin), youtu.be/OrNN7dj55Tc | **unavailable** | same |
| Overview Trailer (Nintendo of America), youtu.be/Mjq-2Fwb730 | **unavailable** | same |
| All Bananza Transformations (RetroArchive), youtu.be/DsPcaL1BnE8 | **unavailable** | same |
| Nintendo "Ask the Developer" Vol. 19 | **not fetched** | outside this container's network allowlist |

There are no timestamped frames or contact sheets in this document, because none could be made honestly. To get them:
- send 5–15 s clips you capture yourself, or screenshots with their timecodes (your own captures, kept out of this public repo); or
- watch the videos and note the moments you like.

I'll annotate each moment (intent, anticipation, focal pose, body, overlap, hold, settle, readability, how often it should happen for Monkey) and tune the cues to match.

## What was built without the footage

Everything below comes from general character-animation principles: anticipation, holds, asymmetry, restraint, settle. These are **hypotheses about what transfers**, not observations of Bananza.

| Monkey behavior | Emotional goal | Phases (s) | Cooldown | Where |
|---|---|---|---|---|
| Attentive listening | "I'm with you" | brows up slightly, eyes a touch wider while listening | state | `acting.ts` STATE_REST |
| Thinking | searching, a little doubtful | one brow up, slight squint | state | `acting.ts` |
| Skeptical "well, actually" | readable doubt | squint anticipation 0.15 → one brow fully up + half smirk → held to 1.2 → settle by 1.6 | 2.4 | cue `skeptical` |
| Curious question | "tell me more" | small lift → right brow up, tiny squint → hold → settle (1.3) | 2.4 | cue `curious` |
| Surprise take | a big, honest reaction | squint 0.1 (anticipation) → eyes pop + brows up + O → hold → settle (1.1) | 2.4 | cue `surprised` |
| Delight | warm, not manic | squint dip → brows, cheeks, grin → settle (1.2) | 2.4 | cue `excited` |
| Sympathy | soft | brows sad + eyes → hold (1.6) | 2.4 | cue `sympathetic` |
| Pride / "handled it" | a confident smirk | smirk + chest puff (1.3) | 2.4 | cue `proud` |

Restraint rules:
- At most one reaction per sentence.
- A 2.4 s cooldown between reactions.
- Most sentences get none.
- Reactions come from the words he's about to say, never from loudness.
- A new state drops a stale reaction.

## Limitations

- No frame-by-frame study of Bananza was possible here; the cue timings are a first pass to refine against real reference.
- Body acting (head tilts, shoulder shrugs tied to cues) still uses the existing talk-gesture clips. The facial cues don't yet drive head or torso.

# Monkey's sonic bible

**Who he is:** a buff, cute, mischievous jungle monkey with glossy eyes and a banana-yellow headset, living on a productivity desktop. His sound should feel **weighty, tactile and warmly cartoony**, and stay **quiet and fast for routine work**.

**Reference.** Donkey Kong Bananza's sound *principles*:
- real Foley recorded from materials, fruit included;
- many takes;
- controlled harshness;
- heavy movement that feels rewarding.

We borrow none of Nintendo's audio, motifs or melodies, and never rip game, YouTube or trailer audio.

## Priorities (loudest to quietest)
1. Your voice and Monkey's speech. SFX duck 10 dB under speech and listening.
2. Warnings and errors.
3. "Needs you" notifications. These are rare by design.
4. Rewards and celebrations.
5. Body and animation (thumps, steps, scratches).
6. Routine interface (clicks, open/close).
7. Ambience. Off by default; it needs owner approval to turn on for everyone.

## Material palette
| Family | Materials | Used for |
|---|---|---|
| **Body** | Padded low-mid impact, chest and fur resonance, palm on fur, knuckles | `chest_thump`, `thump`, `flop`, `slam`, `footstep`, `crack` |
| **Jungle** | Leaves, dry grass, bamboo, soft wood, bark, banana peel | `rustle`, `scratch`, `peel`, `dust`, `whoosh` (air through leaves) |
| **Toy / personality** | Rubber boing, wooden tick, marimba/xylophone, small glass sparkle | `boing`, `tick`, `ding`, `sparkle`, `xylo_run`, `question` |
| **Interface** | Soft wood or bamboo taps, felt-tipped clicks, a short two-note marimba family | `ui_click`, `ui_open`, `ui_close`, `check`, `ui_error`, `notify` |

One family for the interface: every UI sound should sound like it comes from the same small wooden or bamboo instrument. Meaning comes from **contour**:

| Cue | Contour |
|---|---|
| `ui_click` | One soft tap |
| `ui_open` | Rising pair |
| `ui_close` | Falling pair |
| `check` | Bright up-step |
| `ui_error` | Low, muted double-knock (never a buzzer) |
| `notify` | The one cue with a little melody: two clear notes, up |

## Rules
- **Length.**
  - Clicks: 30–120 ms of audible sound.
  - Open/close/confirm: under 350 ms.
  - Notify: under 600 ms.
  - Body beats: no tails over about 0.5 s unless the moment is big (a slam or flop).
- **Attack.** Fast but click-free: a fade-in of at least 1 ms on every edit, and a fade-out on every tail.
- **Takes.**
  - 3–5 takes for anything frequent, matched in loudness within about 2 dB. The engine levels them, but source them close.
  - Variation comes from the take, plus ±5% pitch and ±2 dB in the engine.
- **Layers.** Use the fewest that do the job:
  - UI: 1–2.
  - Body: 2–4 (contact + body resonance + material detail, plus an optional tiny cartoon accent).
  - Big beats: 3–5.
  - Premix offline. One file per take at runtime.
- **Headroom.** Ship at or below −3 dBTP. The master limiter is a safety net, not the mix.
- **Speech first.**
  - No sub-heavy tails under speech.
  - High-pass UI sounds around 120 Hz.
  - Keep 1–4 kHz (speech presence) restrained on anything that can play while he talks.
- **Avoid:**
  - gun or harsh metallic impacts;
  - horror textures;
  - 8-bit bleeps;
  - constant triumphant jingles;
  - endless slide whistles;
  - long reverb tails;
  - anything that sounds like a Nintendo motif.
- **Repetition comfort.** If a sound would be annoying the 200th time, it's too loud, too long or too bright.

## Sources (see SOURCE_LEDGER.md)
- **Allowed in this public repo:**
  - CC0 recordings and synthesized sounds, with license evidence and SHA-256 recorded;
  - our own processing and premixes of those;
  - the existing kit.
- **Never in this repo:**
  - Sonniss GDC bundle audio (its license forbids redistribution as a raw or reworked pack, which a public repo is);
  - CC-BY-NC;
  - unknown licenses;
  - anything ripped.
- **Monkey's vocalizations** stay his own Fish/Pocket voice. No stock human or animal voices.

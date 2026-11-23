# UI motion

Every UI event and interaction, what it showed before, and the motion it has now. Code: `ui/src/motion.ts`
(helpers, levels, FLIP lists, toasts, confetti, count-up) and `ui/src/motion.css` (tokens, entrances that need no code,
voice-state glows, button springs, level overrides). Tests: `ui/test/motion.test.ts`. Perf check:
`python -m tools.playtest.motion_perf` (below).

## Rules

- **Only compositor properties move:** opacity and the individual `translate` / `scale` / `rotate` properties (never
  `transform`, so motion stacks on an element's own transform: a toast's centring, a button's hover lift). Glows are
  pseudo-elements that fade with opacity.
- **Readability first.** Text is fully opaque within **110 ms** (`--m-read`); the bounce settles after that. A
  list cascade never delays its last item by more than 120 ms. **Errors, approvals and reminders appear at once**
  (no fade), then wobble once.
- **Nothing loops at idle** beyond what already did (vines, leaf rustle, the critical-tier shine, the conversation
  chip pulse). New loops only run during a state: the label breathes while *thinking*, a busy button breathes while
  it waits.
- **Hidden window:** CSS loops are paused (WAAPI `pause()`, resumed on show) and new motion is skipped (end state at
  once); motion.ts's own one-shots are finished.
- **The avatar is a separate system.** Nothing here animates `#avatar`. UI glows react to the voice state
  (`html[data-voice]`) next to him, not on him.
- **The comedy lives in Monkey; the chrome stays restrained** (docs/ANIMATION-UI-DIRECTION.md §7).

## Levels

| Level | When | What moves |
|---|---|---|
| `full` | Juice *Full*, or *Auto* without OS reduce-motion | everything below |
| `calm` | Juice *Calm* | half the travel, no overshoot, half the confetti, smaller shakes |
| `min` | Juice *Minimal*, or the OS "reduce motion" setting (any Juice) | 90 ms opacity fades only: no travel, punches, shakes, wobbles, loops or confetti |

`?motion=full|calm|min` in the URL overrides it (recordings, tests). `html[data-motion]` carries the level for CSS.

## Tokens

| Token | Value | Use |
|---|---|---|
| `--m-instant` / `T.instant` | 80 ms | press |
| `--m-fast` / `T.fast` | 150 ms | backdrop, small fades |
| `--m-base` / `T.base` | 240 ms | glows, toast restack, calm moves |
| `--m-move` | 320 ms | entrance travel (calm 240, min 0) |
| `--m-slow` / `T.slow` | 400 ms | progress bars |
| `--m-celebrate` / `T.celebrate` | 900 ms | confetti |
| `--m-read` / `T.read` | 110 ms | text fully opaque by then (min 90) |
| `T.exit` | 160 ms | exits: faster than entrances, no bounce |
| `--m-stagger` / `T.stagger` | 30 ms, capped at 120 ms total | list cascades |
| `--m-ease-pop` | `cubic-bezier(.34,1.56,.64,1)` | overshoot (entrances, release spring) |
| `--m-ease-snap` | `cubic-bezier(.2,1.4,.4,1)` | FLIP moves |
| `--m-ease-out` / `--m-ease-in` | `(.2,.8,.2,1)` / `(.5,0,.75,0)` | settles / exits |

## Helpers (`motion.ts`)

`enter(el, kind)`, `stagger(els)`, `leave(el)`, `removeSmoothly(el)` (ghost exit + neighbours glide), `flip(root, sel, key)`
(lists: moves, new items, ghost exits, progress bars), `pop(el)`, `shake(el)`, `attention(el)`, `swapText(el)`,
`countUp(el, from, to, fmt)`, `confetti(at)`, `progress(bar, from, to)`, `busy(el, on)`, `voice(state)`,
`toastShown(t)` / `toastGone(t)` / `restack()`. Each plan is a pure function (`enterPlan`, `exitPlan`, `popPlan`, …)
so the levels are unit-tested without a browser.

## Inventory

**84 items** (52 backend events/states, 32 user interactions and UI states). "Before" is what `main` showed;
"min" is the Juice-minimal / reduce-motion fallback.

### Backend events (Python `_emit` → `window.__monkeyEvents` → `onEvent` in `main.ts`)

| # | Event | Before | Now | Duration / easing | Min |
|---|---|---|---|---|---|
| 1 | `state` → listening | avatar pose, label text | label text rises in; composer gets a banana inner glow; mic gets a glow ring | 140 ms out; glow 240 ms | label swaps instantly; glow still fades in (opacity) |
| 2 | `state` → transcribing | "Got it" pop + label pulse (feedback.ts) | + label rise-in | 140 ms | pop fades, pulse = brightness |
| 3 | `state` → thinking | label text | label rises in, then **breathes** (scale 1→1.045) while thinking only | 700 ms alternate, ease-in-out | no breathing |
| 4 | `state` → speaking | label text | label rise-in; composer glow turns leaf green | 140 ms; 240 ms | glow fades |
| 5 | `state` → idle | label text | label rise-in; glows fade out | 140 ms; 240 ms | glow fades |
| 6 | conversation chip on | chip appears + border pulse | chip pops in, then the existing pulse | 110 ms op + 320 ms pop | 90 ms fade, no pulse |
| 7 | conversation over | "Talk soon" pop | unchanged (feedback pop) | 320 ms | fade |
| 8 | `level` / `visemes` | avatar mouth | unchanged (avatar system) | — | — |
| 9 | `ack` (slow reply "hmm") | "Hmm…" pop | unchanged | 320 ms | fade |
| 10 | `stopped` | pop + label shake | shake now follows the Juice level | 420 ms | no shake |
| 11 | `wake` | system line | system line rises in | 110 ms op + 320 ms rise | fade |
| 12 | `heard` (empty) | line + "Didn't catch that" pop | line rises in | as above | fade |
| 13 | `user` | your bubble appears | bubble slides in from the right | 110 ms op + 320 ms pop-ease | fade |
| 14 | `delta` (first) | bubble appears | bubble slides in from the left; later deltas add text with **no per-delta animation** | 110 + 320 ms | fade |
| 15 | `done` | — | — (nothing to show) | — | — |
| 16 | `route` | tech chip text | fades in the first time it shows | 110 ms | same |
| 17 | `panel` (markdown card) | card scale-in 380 ms (opacity over the whole 380 ms) | card readable in 110 ms, springy settle; body rises; older cards **glide** down (FLIP) and fold | 110 + 380 ms; FLIP 300 ms snap | fade, no glide |
| 18 | `ranking` / `events` / `weather` / `sources` | card | card + list rows cascade | 30 ms stagger, cap 120 ms | fade, no stagger |
| 19 | `emails` | card | card + rows cascade | same | fade |
| 20 | `images` | card | card + thumbnails cascade | same | fade |
| 21 | `videos` | card | card + video list cascade | same | fade |
| 22 | `draft` (needs your OK) | card scale-in + chime | **appears at once**, then wobbles | 560 ms wobble | no wobble |
| 23 | draft sent (button or `approval` sent) | card turns green, celebrate emote | + confetti from Send, card punch | 900 ms confetti, 360 ms punch | no confetti/punch |
| 24 | `approval` cancelled | card removed | card shrinks away, neighbours glide up | 160 ms exit, 300 ms FLIP | instant |
| 25 | `assignments` | card, rows fade-up 350 ms each draw | rows cascade on first draw (FLIP-managed list) | 30 ms stagger | fade |
| 26 | `assignment_checked` | burst + "+1 NICE" + row collapse | + remaining rows glide up; ring of the last one → confetti | FLIP 300 ms | no glide/confetti |
| 27 | `todos` (show list) | card | card + rows cascade | 30 ms stagger | fade |
| 28 | `todo_changed` added | toast; list redraws (new row glows) | toast pops up and older toasts **step up**; new row pops in; its tab count bumps | 320 ms toast; 240 ms restack | fade, no restack slide |
| 29 | `todo_changed` done | toast + celebrate emote | + row exits, count bumps; last open item → confetti + headline punch | 300 ms / 900 ms | fade |
| 30 | `todo_changed` deleted | undo toast; list redraw | row shrinks away, rows glide up | 160 / 300 ms | instant |
| 31 | `todo_reminder` | alert toast + wave + chime | **shown at once**, then wobble; stacks with other reminders | 560 ms | no wobble |
| 32 | `emote` | avatar | unchanged (avatar system) | — | — |
| 33 | `health` | card | card + tiles/chart rise | 110 + 320 ms | fade |
| 34 | `cleanup` | card | card + rows cascade; "Cleaning…" button breathes while busy | 1 s busy loop (only while busy) | no breathe |
| 35 | `update` checking/downloading | Settings text | unchanged (text status) | — | — |
| 36 | `update` ready | update toast scale-in + chime | readable in 110 ms, springy; "Later" leaves with an exit; "Restart & update" breathes while busy | 110 + 380 ms; 160 ms exit | fade |
| 37 | `opened` | system line | rises in | 110 + 320 ms | fade |
| 38 | `memory` | "Remembered" pop | unchanged (feedback pop) | 320 ms | fade |
| 39 | `memory_used` | memory chip in the log | chip rises in; its list drops open | 110 + 320 ms | fade |
| 40 | `cost` | chip text jumps | **counts up** to the new total (~15 updates/s), then punches | 450 ms + 300 ms | jumps |
| 41 | `warning` | line + amber stage flash | line **at once** + wobble; flash unchanged | 560 ms | no wobble |
| 42 | `error` | line + red flash + label shake | line **at once** + wobble; shake follows Juice | 560 ms | no wobble/shake |
| 43 | `hint` | hint text changes | new text rises in | 140 ms | instant |
| 44 | `automation` (moods) | avatar emote | unchanged | — | — |
| 45 | `computer_event` / task state | Tasks panel redraw | a new question/approval in the Tasks panel wobbles once (redraws of the same one stay still) | 560 ms | none |
| 46 | `automation_propose` | Tasks dialog opens + chime | dialog readable in 110 ms, springy | 110 + 380 ms | fade |
| 47 | `automation_stopped` / `_enabled` | toast / refresh | toast motion | 320 ms | fade |
| 48 | control banner ("Monkey is using…") | appears | drops in | 110 + 320 ms | fade |
| 49 | `google` (sign-in stages) | Settings text + toasts | toasts motion; guide `details` drop open | 320 ms | fade |
| 50 | `voicekit` / `offlinevoice` / `bench` / `calibration` progress | Settings text, calibration bar (width transition) | unchanged text; result toasts get toast motion | — | — |
| 51 | `open_settings` | dialog opens, scale-in | readable in 110 ms, springy; backdrop fades | 110 + 380 ms; 240 ms | fade |
| 52 | overlay (companion) window | its own avatar + panel | approval wobble in its task panel | 560 ms | none |

### User interactions and UI states

| # | Interaction | Before | Now | Duration / easing | Min |
|---|---|---|---|---|---|
| 53 | Any chunky button press | moves down 4 px (90 ms) | quick squash down, **springs back with overshoot** on release | 70 ms in; 260 ms pop out | press only, no spring |
| 54 | Button hover | lifts 2 px | lift springs | 260 ms pop | instant |
| 55 | Mic hover | lift | one wiggle (the main button only) | 420 ms | none |
| 56 | Importance (Quick/Auto/Important) | colour swap + toast | chosen pill punches | 300 ms | none |
| 57 | Send with an empty box / no Claude key | nothing / toast | the input shakes | 380 ms | none (toast says it) |
| 58 | Send / Enter | bubble appears | bubble slides in from the right (#13) | 110 + 320 ms | fade |
| 59 | New chat | log cleared, system line | system line rises in | 110 + 320 ms | fade |
| 60 | Card title (fold/unfold) | instant | unfolding body rises in | 110 + 320 ms | fade |
| 61 | Card ✕ | removed | shrinks away, the cards below glide up | 160 ms; 300 ms | instant |
| 62 | Header: Settings / Tasks / Brain dialogs open | scale-in 380 ms | readable in 110 ms, springy; backdrop fades in | 110 + 380 ms | fade |
| 63 | Dialog close (✕, Escape) | instant | **unchanged on purpose**: native `close()`, Escape can't be intercepted cleanly, and an instant close reads as "done" | — | — |
| 64 | Settings nav jump | outline on the section | unchanged (static outline: readable) | — | — |
| 65 | Settings `details` expand (Advanced, guides, memory inspector) | instant | content drops in | 110 + 320 ms | fade |
| 66 | Settings toggle checkbox on | native tick | tick punches | 260 ms | none |
| 67 | Key save | "Checking the key…" text | the note breathes while it checks | 1 s loop while busy | none |
| 68 | Today open / close | view shows | view rises in (close is instant) | 110 + 320 ms | fade |
| 69 | Today tabs (click, arrows, Home/End) | content swaps | content **slides in from the side of the tab**; the tab punches | 110 + 320 ms; 300 ms | fade |
| 70 | Today "Mark done" / Undo | hero dims, Undo | hero punches; the "done" message pops | 360 ms; 320 ms | fade |
| 71 | Homework / To-do tabs | list swaps (rows replay a fade) | new list cascades; the tab punches; changed counts bump | 30 ms stagger; 300 ms | fade |
| 72 | To-do sort (Due / Priority) | list reorders instantly | rows **glide to their new places** (FLIP) | 300 ms snap | instant |
| 73 | To-do quick add typing | parsed chip row appears | chip row drops in | 110 + 320 ms | fade |
| 74 | To-do Add | row appears with glow | row pops in (glow kept), others glide | 320 ms; 300 ms | fade |
| 75 | Checkbox tick (to-do, step, assignment) | box fills, check draws, burst, "+1 NICE" | + box squash on press; row exits, rows glide; step bar **grows** to the new width | 60 ms squash; 300 ms FLIP; 400 ms bar | no squash/glide/burst |
| 76 | To-do edit open / save / cancel | form replaces row | form grows open; saved row returns without ghosts | 110 + 320 ms | fade |
| 77 | To-do delete / Undo | row vanishes / reappears | row shrinks away / pops back in; rows glide | 160 ms; 320 ms | instant / fade |
| 78 | To-do "Remind me" / "Say out loud" toggles | tick | tick punches | 260 ms | none |
| 79 | Toasts (all: saved, errors, undo) | appear/vanish in one spot, overlapping | pop up from the bottom; older toasts step up so none overlap; leave with a quick drop | 320 ms in; 240 ms restack; 160 ms out | fade; no restack slide |
| 80 | Reminder toast Done / Snooze / ✕ | removed | leaves with the exit; the stack settles | 160 ms | instant |
| 81 | Email rows / thumbnails / video list hover & focus | background tint, focus outline | unchanged (instant focus is clearer) | — | — |
| 82 | Image lightbox (Avatar Lab) | appears | backdrop fades, picture pops | 150 ms; 110 + 320 ms | fade |
| 83 | Empty states ("Nothing to do…", "Nothing left") | text | text pops in | 110 + 320 ms | fade |
| 84 | Drag | only the companion window's title area (native window move) | no UI motion (native) | — | — |

## Not animated, on purpose

- **Per-delta text** while a reply streams: animating every token would cost frames and slow reading.
- **Dialog close** (#63) and **focus rings** (#81): instant is clearer and native.
- **Settings re-renders** (a key saved, a sign-in finished) don't replay entrances for the whole dialog (only `details` that were closed and open again).
- **Text progress** (update download %, voice download MB, voice set %): text is already the readable form; a bar would be new UI, not motion.

## Performance (cloud container, software rendering)

`python -m tools.playtest.motion_perf --dist <dist> --query "?demo&svg"` (and `?demo` for the 3D avatar), run on
`main` and on this branch, three alternating runs each. See the numbers in `docs/IMPLEMENTATION-NOTES.md`
(2026-11-23, UI motion). Container numbers compare builds with each other; they are not Dell timings.

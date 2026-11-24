# UI motion

Every UI event and interaction, what it showed before, and the motion it has now. Code: `ui/src/motion.ts`
(helpers, levels, FLIP lists, toasts, confetti, count-up) and `ui/src/motion.css` (tokens, entrances that need no code,
voice-state glows, button springs, level overrides); menus and loading UIs in `ui/src/menu-motion.ts`,
`ui/src/loader.ts` and `ui/src/menu-motion.css` ([Menus](#menus), [Loading](#loading)). Tests: `ui/test/motion.test.ts`,
`ui/test/menu-motion.test.ts`, `ui/test/loader.test.ts`, `tests/test_menu_motion_ui.py`. Perf check:
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
- **Toy-block icons own their motion** (`blocky/skin.ts`: hover hop, press squash, check-off pop, following
  `html[data-juice]` and reduce motion). motion.css skips buttons that wear one, so nothing animates twice.
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

**93 items** (54 backend events/states, 39 user interactions and UI states), plus the menu and loading items 94–121
[below](#menus-and-loading-inventory). "Before" is what `main` showed;
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
| 62 | Header: Settings / Tasks / Brain dialogs open | scale-in 380 ms | **grows out of the button that opened it**, readable in 100 ms, full size by ~140 ms, springy settle; contents cascade; the title bounces; backdrop dims and blurs (see #94) | 100 + 380 ms | fade |
| 63 | Dialog close (✕, Escape) | instant | **now animated** (#95): shrinks back into its button, faster than it opened; Escape always closes | 140 ms | 90 ms fade |
| 64 | Settings nav jump | outline on the section | the section slides in from the direction you jumped (#100); outline kept | 300 ms snap | outline only |
| 65 | Settings `details` expand (Advanced, guides, memory inspector) | instant | content drops in | 110 + 320 ms | fade |
| 66 | Settings toggle checkbox on | native tick | tick punches | 260 ms | none |
| 67 | Key save | "Checking the key…" text | the note breathes while it checks | 1 s loop while busy | none |
| 68 | Today open / close | view shows | pops out of the ☀ button, the selected tab bounces; **close shrinks back** toward it, then the chat returns (#98) | 100 + 380 ms; 140 ms | fade |
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

### Added on `main` while this was built (reminders, email suggestions, phone screen time, blocky icons)

| # | Event / interaction | Before | Now | Duration / easing | Min |
|---|---|---|---|---|---|
| 85 | `screentime` (phone card in the to-do panel) | card content redrawn | content rises in; the goal meter **fills** from the left; the 7-day bars **grow** from the baseline, 20 ms apart | 110 + 320 ms; 400 ms fill/grow | fade, no fill/grow |
| 86 | `screentime_nudge` | toast | toast motion (#79) | 320 ms | fade |
| 87 | "Suggested from email" section appears | section | rises in once (FLIP-managed with the list; later redraws don't replay it) | 110 + 320 ms | fade |
| 88 | Suggestion **Accept** | row gone, to-do added, toast | suggestion shrinks away, the new to-do pops into the list, toast | 160 ms; 320 ms | instant / fade |
| 89 | Suggestion **Dismiss** | row gone | shrinks away, the rest glide up | 160 ms; 300 ms | instant |
| 90 | Settings → Reminders (Windows & phone) loaded | text replaced | Windows and phone blocks rise in; the QR code pops | 110 + 320 ms | fade |
| 91 | Settings → Accounts: email account list | list | rows cascade | 30 ms stagger | fade |
| 92 | Toy-block icons (header, mic, to-do checkboxes and actions) | icon hover hop, press squash, check-off pop (`blocky/skin.ts`) | **left to the icons**: buttons with a `.bi` icon get no extra spring or wiggle from motion.css | — | the icons follow `data-juice` and reduce motion themselves |
| 93 | Windows / phone reminder notifications | outside the app window | no UI motion (the in-app reminder toast is #31) | — | — |

## Not animated, on purpose

- **Per-delta text** while a reply streams: animating every token would cost frames and slow reading.
- **Focus rings** (#81): instant is clearer and native. (Dialog close, #63, used to be here: it animates now, #95.)
- **Settings re-renders** (a key saved, a sign-in finished) don't replay entrances for the whole dialog (only `details` that were closed and open again).
- **Text progress** (update download %, voice download MB, voice set %): text is already the readable form; a bar would be new UI, not motion.

## Menus

`ui/src/menu-motion.ts`. `installDialogMotion()` (once, at start-up in `main.ts`) routes every dialog's `showModal()`,
`close()` and Escape through one helper, so all of them, including ones added later, behave the same:

- **Opening** grows out of the element that was just pressed (a capture listener notes the last pressed button; the
  focused button is the fallback): `transform-origin` = that button's centre relative to the dialog, clamped to its
  edges. Opacity 0→1 in 100 ms, scale .5 → 1.035 → 1 over 380 ms with an ease-out that passes full size at ~140 ms,
  so the menu is readable and clickable within ~150 ms and the overshoot happens around readable content. The first
  few blocks (header, nav, first sections) cascade in from 35 % opacity, 22 ms apart (capped at 66 ms); the title or
  header icon bounces once (70 ms after the box lands). The backdrop dims (as before) and blurs 3 px; it fades in and
  out with its opacity (the blur radius isn't animated).
- **Closing** (✕, Escape, any `close()` call) is the opening reversed and faster: 140 ms ease-in back toward the
  opener, the backdrop fades out, clicks on the closing dialog are off (`data-m-closing`), then the real `close()` runs
  (the `close` event fires then; focus goes back to the opener, and the helper re-focuses it if focus got lost).
  While it is closing the dialog already reports `open === false`, so code like `if (!dlg.open) dlg.showModal()` reopens
  it, and toasts don't land in it.
- **Escape:** the `cancel` event is intercepted (capture listener on `document`) and animates the close. A second Escape
  during the exit, an Escape the browser won't let a page delay (Chrome makes `cancel` non-cancelable without a recent
  user activation), or a hidden window closes at once. A timer finishes any close whose animation can't (never stuck).
- **Interrupting:** opening a dialog that is closing reverses the exit (`Animation.reverse()`) from wherever it is;
  double clicks on ✕ close once; Escape while it is still opening closes from where it is.
- **Switching menus** (Tasks → Mailing lists): when a dialog opens while another is closing, the old one slides out to
  the left and the new one slides in from the right (56 px, a snap ease).
- **Panels and cards** (`openFrom` / `closeTo` / `slideIn`): Today, To-do, Homework, Health and the Lab pop out of
  their header button the same way (their CSS entrance is switched off with `.m-js`); Today closes back toward its
  button and only then hides; a card's ✕ keeps the existing shrink-away (#61). Settings section jumps slide in from
  the direction of travel; Today tabs keep their side slide (#69).
- **The window coming back from the tray** (hidden ≥ 0.8 s): the header buttons hop in, 25 ms apart, and the open
  panel settles (`wake()`); nothing if it was hidden only briefly.
- Levels: *calm* = scale .88→1 with no overshoot, half the slide distance, a small title pop; *min* (Juice minimal or
  OS reduce motion) = 90 ms fades only, no cascade or bounce. A hidden window: no motion, end state at once.

## Loading

`ui/src/loader.ts` + `ui/src/menu-motion.css`. One rule set for every menu that waits on the Python side:

- **Nothing for the first 150 ms** (a fast load stays instant, no flash). Then the loader appears in the panel (a header
  card is put up at once and filled in place; a dialog opens a frame with its title and ✕). **Once shown it stays at
  least 400 ms** (no flicker). Both are in `gate()`, unit-tested with a manual clock.
- **Skeleton in the panel's real layout**: to-do / homework rows (checkbox + two lines), the Today focus card and tiles,
  the health ring + tiles + chart, Settings (nav pills + sections, at the dialog's real height), a form (Tasks), a table
  (Mailing lists, Brain), text blocks (settings sections, the morning brief), slim rows (Check everything, accounts,
  memory). Rows rise in once, then a banana-and-leaf shimmer sweeps across the bars (one `translate` per bar, 1.35 s).
- **A playful loader** next to the words (CSS + inline SVG, decorative, `aria-hidden`): a **banana trio** that hops and
  squashes in a wave, a **swinging vine** with a monkey head on it, or a **bobbing monkey head** with a breathing shadow.
- **Words that change** (a `role=status` live region): "Loading your calendar…", after 3 s "Still fetching your
  calendar…", after 8 s "Still working on it. Hang tight 🍌", after 15 s "This is taking longer than usual. You can keep
  chatting meanwhile." Panels can give their own lines (Check everything names what it is checking).
- **Errors** stay in the panel: "Couldn't load your to-do list", the reason, **↻ Try again** (focused, so Enter retries;
  the retry shows the loader at once). The box appears at once and wobbles once (#41's rule).
- **Crossfade, no layout jump**: the skeleton is moved to a fixed, click-through layer at exactly its place (inside a
  dialog: a manual popover, which sits in the top layer above the dialog and survives the dialog redrawing) and fades
  out over 220 ms while the real content, rendered in the same spot, fades in under it.
- **Levels**: *full* everything; *calm* slower loops (1.6 s, shimmer 2.2 s) at half amplitude; *min* (Juice minimal or
  OS reduce motion) nothing moves: the skeleton and loader only breathe in opacity (1.8 s). **Hidden window**: loaders
  pause (`html[data-m-hidden]`, also ones that start while hidden). **Once loaded nothing keeps running** (the loader
  and its ghost are removed; checked by the browser test and the perf tool).
- **Buttons whose action takes time** (Check now, Clean up old installs, Fill in from my calendar, Check everything,
  Canvas ↻, History) show a tiny banana trio and a busy label after 150 ms, at least 400 ms (`busyButton`).
- **States that last** (a task planning, the first mailing-list scan) use `loadingSince()`: a redraw keeps the words'
  place in the sequence instead of starting over.
- **Demo:** `?demo&slow=900` delays every demo call (`&slowonly=todo_list,get_state` limits it, `&failonce=todo_list`
  fails the first call) for recordings, tests and the perf tool.

### Menus and loading inventory

| # | Menu / load | Before | Now | Duration / easing | Min |
|---|---|---|---|---|---|
| 94 | Dialog backdrop | dims, fades in | dims + 3 px blur; fades out on close | 240 ms in; 140 ms out | same (static blur) |
| 95 | Every dialog's close (✕, Escape, `close()`): Settings, Tasks, Mailing lists, Brain, task history | instant | back into its button, faster; Escape always closes; focus returns | 140 ms ease-in | 90 ms fade |
| 96 | Approval / permission cards (draft, task approval, reminder) | appear at once + wobble | unchanged on purpose: they must be readable at once (#22, #31, #45) | — | — |
| 97 | Account dialogs (Google sign-in guide, Garmin, Outlook) | in Settings | Settings' motion; their `details` drop open (#65) | — | — |
| 98 | Today close | instant | shrinks back toward ☀, then the chat returns | 140 ms | fade |
| 99 | To-do / Homework / Health / Lab open | card pop (CSS) | grows out of its header button; contents rise; the to-do title icon bounces | 100 + 380 ms | fade |
| 100 | Settings section jump (nav, "Fix it" buttons) | scroll + outline | + the section slides in from the side you travelled | 300 ms snap | none |
| 101 | Tasks → Mailing lists / Inbox cleanup | one dialog closes, the other pops | hand-over: old slides out left, new slides in from right | 140 ms; 320 ms snap | fades |
| 102 | Dropdowns / popovers (`details`, memory chip, guides) | drop open (#65, #39) | unchanged | 110 + 320 ms | fade |
| 103 | Native `select` menus | OS menu | not animatable (the OS draws it) | — | — |
| 104 | Narrow / mobile layout (≤ 820 px stacked, ≤ 560 px icon-only header) | as wide | the same origin-aware motion; dialogs at 94 vw grow out of the (wrapped) header button | as wide | as wide |
| 105 | Window shown from the tray | appears as it was | header buttons hop in, open panel settles (once) | 320 ms, 25 ms apart | none |
| 106 | Today: Focus / Homework / Schedule loading | nothing until data, then content | after 150 ms: skeleton of the tab (focus card + tiles / rows / list), monkey or bananas, "Still fetching your calendar…"; error + Try again | ≥ 400 ms; 220 ms crossfade | opacity pulse |
| 107 | Today tiles still loading (`loading` sections) | "Loading…" | "Loading…" + a two-line shimmer skeleton in the tile | until loaded | static |
| 108 | Homework (Canvas) | toast on error, card when loaded | card at once with a list skeleton; Canvas ↻ shows the banana trio | as #106 | pulse |
| 109 | To-do list | as Homework | card at once, list skeleton (5 rows), error card with Try again | as #106 | pulse |
| 110 | Phone screen-time card (to-do) | empty until loaded | two-line skeleton | as #106 | pulse |
| 111 | Health (Garmin) | toast / card | card at once: ring + tiles + chart skeleton, swinging vine | as #106 | pulse |
| 112 | Settings open | waited for the app, then opened | opens at once (full height) with nav + section skeleton, bobbing monkey | as #106 | pulse |
| 113 | Settings sections: Reminders (Windows & phone), Phone, Accounts (email list), Update status, Morning brief status, history count, "What Monkey knows" | "Loading…" / "…" / empty | skeletons or a compact loader in place | as #106 | pulse |
| 114 | Check everything (10–20 s) | one line of text | swinging vine + six-row skeleton; words say what is being checked; the report crossfades in | until the report | pulse |
| 115 | Update check, Clean up old installs, Fill in from my calendar | button text | banana trio + busy label in the button | ≥ 400 ms | static |
| 116 | Tasks dialog open | waited, then opened | opens at once with a form skeleton | as #106 | pulse |
| 117 | Task helper planning (`PLANNING`) | "Thinking" badge | + bobbing monkey with "Planning the steps…" → "Still planning: reading the page…" (redraws keep their place) | while planning | static |
| 118 | Mailing lists and Inbox cleanup: open / scan | waited / "Reading list headers…" | dialog at once with a table skeleton; the scan shows the table skeleton + banana trio with changing words | while scanning | pulse |
| 119 | Brain dialog (models per task) | waited, then opened | opens at once with a table skeleton | as #106 | pulse |
| 120 | Avatar Lab: designs list; image generation (~40 s) | "Generating… (~40s)" on the button | designs skeleton; a placeholder tile with the swinging vine where the new picture lands, words change | until done | pulse |
| 121 | Morning brief at start-up | card when ready | card at once with a text skeleton and the monkey; gone smoothly if there's no brief | as #106 | pulse |

Not given a loader on purpose: email suggestions (they load in the background into an already-drawn to-do list), the
chat's own cards (Monkey's "thinking" state already covers them), saves and toggles (they answer in well under 150 ms
and confirm with a toast), and anything in the companion window (too small; it shows the task state badge).

## Performance (cloud container, software rendering)

`python -m tools.playtest.motion_perf --dist <dist> --query "?demo&svg"` (and `?demo` for the 3D avatar), run on
`main` and on this branch, three alternating runs each. See the numbers in `docs/IMPLEMENTATION-NOTES.md`
(2026-11-23, UI motion). Container numbers compare builds with each other; they are not Dell timings.

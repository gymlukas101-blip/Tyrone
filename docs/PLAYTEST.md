# Persona playtesting (how Monkey gets usability-tested)

**Method.** AI testers role-play an everyday 19-year-old student ("Jordan"). They play the real app and never read its code.
- Personas: impatient skimmer, anxious, phone-first, privacy-wary, tired night owl, literal reader, chatty, money-cautious.
- They drive the UI through `tools/playtest` (the real backend, headless, with sample data).
- Rules, from published research on LLM usability testers:
  - testers see only what's on screen and keep a patience budget;
  - at every step they log what tripped them;
  - success is judged from app state (`/control/verify`), not from the tester's claim;
  - discovery passes run before any fixes;
  - fixes are verified by fresh testers who aren't told what changed.

**Run a seat:**
```bash
tools/playtest/start.sh 1 fresh    # or: setup
curl -s localhost:9301/see         # what's on screen
```
Stop it with `tools/playtest/stop.sh 1`.

## Round 1 (v0.3.38): 2 discovery passes, 8 testers, 33 tasks → fixes
| Problem testers hit | How many | Fix |
|---|---|---|
| Notes import: "click Apply" but no Apply button (inside a clipped scroll box), so notes never imported | 4 of 5 who tried | Buttons above the preview; scrolls into view; "Monkey learned N things"; renamed **Add notes about you** |
| Settings: one endless page with developer items mixed in | 8/8 | Section menu (Start · Accounts · Voice & sound · Morning brief · Memory · Look & mic · Advanced); developer items folded under **Advanced**; keeps your place when it refreshes |
| Morning brief card stale after setup | 5/8 | Rebuilt when Settings closes; "Set my class times" button on the card |
| Google: Sign in looked ready but errored; jumped to top after loading the file; grey dot after connecting | 6/8 | Step 1 (setup file) → Step 2 (Sign in, disabled until step 1); live Connected state; troubleshooting folded |
| Can't see or fix what Monkey knows | 1/8 (sev 4) | "What Monkey knows about you" lists everything, with Edit and Forget |
| "Tomorrow" showed today; Canvas times in UTC ("05:59") | 4/8 | `get_calendar(day=…)`; all event times in local time with a `when` field; card labelled with the day |
| "Listening…" after a typed question | 4/8 | Typing no longer opens the mic for a follow-up |
| Tech labels: model chip, memory file names, Avatar Lab, Garmin ♥ for everyone | 8/8 | Hidden unless Advanced → Developer → Show technical details; ♥ only when Garmin is connected |
| Header icons unguessable | 6/8 | Words under the icons: Homework · New chat · Settings |
| Sent email still said "Draft … Nothing is sent" | 3/8 | Card turns into a receipt: "✅ Sent to … at 10:42", fields locked |
| Duplicate and stale cards; New chat left old cards | 5/8 | One card per kind; New chat clears them (unsent drafts stay) |
| "0 of 5 done" vs "To do (6)"; no undo; raw codes like PSYCH_202_001_F26 | 6/8 | Counts explained; Undo toast; finished items say "done"; course names like "PSYCH 202" |
| Canvas link field had no Save button | 4/8 | Save button + status + where-to-find-it next to the field |
| Half-pasted Claude key showed a green "Saved" | 1/8 | Red "This key didn't work" until it does |
| Backup voice: raw "HTTP Error 403", status stuck; confusing options; volume under Look & feel | 3/8 | Plain errors and status reset; renamed **Backup voice**; volume and loudness under **Voice & sound** |
| Brief skipped overdue work; "Schedule cleared" on an empty Confirm; Task Scheduler jargon and XML | 4/8 | **Overdue** section; clear guidance; a plain Turn on/Turn off with the next time; XML only in technical details |
| Sentences glued across tool calls ("Canvas.You've") | 6/8 | A space between streamed rounds |
| Asking Monkey "how do I…" didn't point anywhere | 1/8 | In-app map in the persona, plus an `open_settings` tool |
| Smaller copy issues ($ counter, Quick/Important cost, "paste it to Claude", "0 MB", "Open folder" gave no feedback) | — | Plain wording and tooltips |

Rig limits: no microphone or speakers, no real Claude (a scripted stand-in calls the same tools), and a 2D avatar (the 3D one is too slow on a CPU-only server). Voice, wake word and answer quality still need checks on a real PC.

## Verification round 1: 4 fresh testers, same personas and tasks, not told what changed
- **Task success:** 17 of 18 tasks, up from 13 of 19 for the same personas in the discovery passes.
- **Median ease (1–7):** about 5.5, up from about 4.
- **Would recommend:** 7, 7, 7 and 6 out of 10, up from 3, 4, 5 and 5.
- **What still came up, and the round-2 fixes:**
  - "Check everything" was scrolled out of view when Monkey opened Settings → Start. Start now opens at the top, and there's a `check` section for "is everything working?".
  - Tapping ✕ on "Listening…" didn't stop push-to-talk ("Ears up…" stayed). ✕ now cancels at once.
  - A rejected Claude key showed "saved ••••". It's no longer kept.
  - "Detect from calendar" picked office hours at 5 AM as a class. It now ignores office hours, exams, study groups and anything before 7 AM, and falls back to class times in your notes.
  - The brief said "first class at 11" next to "nothing today". Today now lists the first class from your schedule.
  - Not connected? Tool results now tell Monkey to open Settings → Accounts.
  - The calendar link box appeared twice, a regression from round 1. Removed.
  - Older cards fold to their title bar.
  - Email rows are clickable (Monkey reads the email).
  - The volume slider shows a %.
  - The backup voice's download button is disabled while downloading.
  - Turn on/Turn off for the brief is now one toggle.
  - Google shows "Connected as …".
  - Memory chips show the actual facts used.
  - Homework: "N to do" headline, with the due time shown once.
  - Friendly calendar source names.
  - Toasts name the setting that changed.
- **Rig artifacts fixed:**
  - sample events at odd hours;
  - text-box contents read wrong;
  - the stand-in brain's memory search.

## Verification round 2: 5 fresh testers (privacy-wary, night owl, literal reader, chatty, money-cautious)
- **Task success:** 22 of 23 tasks. The same personas did 13 of 19 in discovery.
- **Ease (1–7):** median about 6.
- **Would recommend:** 7, 7, 8, 7 and 8 out of 10.
- **No new severity 3–4 problems in the app itself.** The one failure, the chatty tester's "fix what you know", exposed a real issue: memory search returned Monkey's internal notes (the model table) and the user's own question as "facts". It's fixed in round 3.
- **Round 3 polish:**
  - The welcome said "all set" before a key was saved; fixed. Your question stays in the box until the Claude key is in.
  - Plain Google setup-file errors.
  - Detect-from-calendar explains why it found nothing.
  - After Google connects: "found N emails and M events".
  - Health check: plain words, the real tab names, "Fix it" buttons, and Copy report at the end too.
  - Transfer: type the password twice; keys listed by name.
  - "Send email" label.
  - Cards fold when you send a message, and a closed brief stays closed.
  - Memory chips have a "See or fix what Monkey knows" button, and Monkey opening Memory opens that list.
  - Toasts for Quick/Auto/Important; tooltip on Mark done.
  - The backup voice Download is the main button; the voice set is marked optional.

## Verification round 3: 3 fresh testers (skimmer, anxious, chatty)
- **Task success:** 13 of 13.
- **Ease (1–7):** 5–7.
- **Would recommend:** 8, 7 and 7 out of 10.
- **No severity 3–4 problems.**
- **Round 4 fixes:**
  - Settings opened from chat landed on Memory: a re-opened menu was hijacking the scroll. The jump now ignores re-opened sections and uses plain scroll math.
  - A refreshed brief popped open over the chat; it keeps its folded state now.
  - A half-pasted key gets a "looks too short" hint before trying.
  - Next brief says "today/tomorrow" or a date.
  - Past questions are no longer returned as facts.
  - "Fill in from my calendar or notes".
  - The Google file hint names the right file.
  - A ✓ shows next to saved fields.
  - The health check: the wake word shows not working when there's no mic, and plurals are fixed.

## Verification round 4: 2 fresh testers (anxious, chatty)
- **Severity 4 regression:** the round-4 "looks too short" check blocked saving a short key, so the anxious tester could never finish set-up. Now the length is only a hint: Claude decides, and a key it rejects isn't saved.
- **Severity 3:** the chatty tester edited a fact, asked again, and got the old wording back. Monkey's own earlier reply in the same chat (and the chat's lines) came back as "memories". Memory search now skips the current conversation, which is already in context.
- **Polish:**
  - Each "Fix it" button says where it goes ("Set class times", "Open Accounts", …), with a hint to re-run the check.
  - The brief's Today lists your classes from your notes.
  - Remembered facts are written about you ("Their roommate is Sam"), not in your words.
- The rig's "already set up" profile now includes the imported notes pack, as the task says.

## Verification rounds 5–6: 4 fresh testers (anxious, literal reader, night owl, skimmer)
- **Task success:** 11 of 11 (T1, T2, T3, T4, S1, S4, S5, S6, S7).
- **Ease (1–7):** median 6.
- **Would recommend:** 6, 7, 7 and 8 out of 10.
- T1 passes again: the half-pasted key gets "looks short (21 characters)", and the full key saves and works.
- **Severity 3 (night owl):** a typo'd 01:00 class time was saved silently, so that day's brief would be built around midnight. Now times before 7 AM or after 9 PM get an inline "is that right?" and need a second click, and the saved days are listed back.
- **Fixed polish:**
  - Typing closes a mic left open by a click ("Ears up…" stuck).
  - Memory chips show the fact text.
  - Forget refreshes the count.
  - Optional voice extras aren't counted as warnings.
  - The $ pill explains who pays and where the limit is.
  - Export password problems show next to the box.
  - The calendar-detect message sits under its button.
  - "Today (late start)" is renamed.
- **Stand-in brain limits, not app bugs:**
  - It answered "who's my math prof" from the calendar when the class note was in the retrieved memories.
  - "Got it." to how-to questions.
  - Compound questions answered by halves.
- **Still open, by design:** Google needs the one-time setup file, because a personal-project OAuth app has no shared client.

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

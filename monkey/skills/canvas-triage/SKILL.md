---
name: canvas-triage
description: Use when the user asks what's due, what to work on first, or how bad their week looks in school (Canvas assignments, deadlines, missing work).
---
# Canvas triage

Goal: tell the user the ONE thing to do next and why, with the rest on screen. Accurate over impressive.

1. Call `get_assignments` (it shows the ranked checklist on screen). If it says Canvas isn't connected, say so and
   suggest the Canvas token in Settings; don't guess deadlines.
2. Rank with what the data actually says, in this order:
   - missing or late work that still accepts submissions,
   - due within 24 hours,
   - grade impact (`impact_pct` = % of final grade) or points, when present,
   - then deadline.
   If the source is the calendar feed, there are no points or grades: say "points unknown", never estimate them.
3. Out loud, in 1–2 sentences: the top item, when it's due (day + time), and why it's first.
   Then one concrete next step ("Open it and do the first 25 minutes now").
4. On screen (`show_on_screen` only if the checklist isn't enough): a short table of the next 72 hours.
5. If the user says they finished something, call `check_off_assignment`. Checking off never submits work; say so
   only if they seem to think it does.
6. Time-sensitive facts from memory (class times, old due dates) may be stale: trust the live tool over memory.

Don't: invent due times, points, grades or course names; nag or shame; list more than 3 items out loud.

# Research notes (November 2026)

## Voice: what to use and what it costs

| Option | Price (list) | Notes |
|---|---|---|
| **Fish Audio** (chosen) | ~$15 per 1M characters (pay as you go) | Best price for quality. Has **Voice Design**: generates a voice from a text description, then you keep it as a private voice. Streaming API. |
| ElevenLabs | ~$50 (Flash) – $100 (v3) per 1M characters | Polished, but 3–7x the price. |
| Cartesia | mid-range | Lowest latency in third-party benchmarks. |
| Kokoro (local) | $0 | Runs offline; less expressive, no custom character voice. |

For Tyrone, about 30–150 spoken sentences a day comes to roughly 100–300K characters a month, which is **about $1–3 a month on Fish**.

**Why Tyrone doesn't clone 50 Cent:**
- Both Fish Audio and ElevenLabs ban cloning a real person's voice without consent, and ElevenLabs blocks celebrity voices outright.
- NY, CA and TN (the ELVIS Act) protect a person's voice and likeness.
- Fish's Voice Design makes you confirm the voice doesn't impersonate a real, identifiable person.

So Tyrone is an original character with a similar vibe: a deep, smooth, laid-back New York voice.

## Wake word
- **Picovoice Porcupine's free tier was shut off on June 30, 2026.**
- **openWakeWord** (Apache-2.0) is the free option. It trains a custom phrase from synthetic speech, so you don't record anything (see `wakeword/README.md`).

## Speech-to-text
- **faster-whisper** (local) is free and private. About 0.5–1.5 s per utterance on a laptop CPU.
- **Deepgram Nova-3** is about $0.004–0.008 per minute and faster. It's an optional setting.

## Brain (Claude)

| Model | $/1M input | $/1M output | Used for |
|---|---|---|---|
| Claude Haiku 5.5 | $0.10 | $0.50 | Small talk, commands, routing classifier |
| Claude Sonnet 5.5 | $2 | $10 | Normal questions, quick web lookups |
| Claude Opus 5.5 | $4 | $20 | Research, email drafting in your voice, priority ranking, anything you mark important |

The router decides on each request (see `tyrone/brain/router.py`):
1. Your words come first: "important" or "take your time" means a stronger model, "quick" means a cheaper one.
2. Then task rules, such as email drafting and research.
3. Then a Haiku classifier that costs a fraction of a cent.
4. A monthly budget cap applies on top.

Prompt caching keeps repeat context cheap.

## Email and calendar at UW–Madison
- **wisc.edu (Microsoft 365):** since late 2025, Microsoft requires a tenant admin to approve third-party apps that read Exchange mail and calendars through Graph. Students can't approve this themselves. Tyrone uses the **classic Outlook desktop app** through Windows COM instead. It is local, already signed in, and needs no admin approval. ("New Outlook" has no COM interface.)
- **Gmail and Google Calendar:** official APIs with your own OAuth client. Set the consent screen to *In production* (unverified is fine for personal use). In *Testing* mode, Google expires the login every 7 days.
- **Canvas:** since Nov 14, 2025, UW–Madison students can't create API tokens themselves (it's a request form now). The **Calendar Feed (ICS) link** gives all due dates with no token.

## Canvas grades and points
- The calendar feed only has titles and due dates. Points, current grade and missing status come from the Canvas REST API:
  - Courses, with `include[]=total_scores`, give your current grade.
  - Assignment groups, with `include[]=assignments&include[]=submission`, give each assignment's points, the group weights, and the `missing`, `late` and graded status.
- The checkbox uses Canvas **Planner overrides** (`marked_complete`), so a check in Tyrone also shows as done in Canvas's planner.
- At UW–Madison, students must request an API token through a form (since Nov 2025).

### Priority formula (`tyrone/brain/assignments.py`)

Priority is scored 0–100 from four pieces:

| Piece | How it's scored |
|---|---|
| Grade impact (45%) | The assignment's share of your final grade. Uses the course's group weights if it has them, otherwise its share of total points. Anything worth 10% or more gets full marks. |
| Urgency (35%) | Highest for missing or overdue work, then due in 24h, 48h, 3 days, a week, two weeks. |
| Grade need (20%) | Full boost at 70% or lower in that course, none at 95% or higher. |
| Missing | +10 |

Tiers by score: critical ≥ 70, high ≥ 50, normal ≥ 30, low below 30.

## Garmin
- Garmin's official Health API is only for approved businesses.
- The community `garminconnect` library switched to Garmin's mobile sign-in in v0.3 (the old garth login broke in March 2026). It supports two-step verification codes.
- Tyrone uses your password once and never saves it. The tokens go in `%APPDATA%\Tyrone\garmin`.
- It reads `get_sleep_data`, `get_heart_rates`, `get_user_summary` and `get_hrv_data`.
- Unofficial means Garmin can break it again. When that happens, update the library version.

## Where your data lives (memory)
- **Memory** is markdown files in `%APPDATA%\Tyrone\memory\memories\`, managed by Claude's memory tool. Claude reads only what it needs, and you can open and edit them.
- **The SQLite database** holds the cost ledger.
- **API keys** are stored in Windows Credential Manager.

None of this goes in the code repo. To move to another PC, use Settings → Export (an encrypted file) or point the memory folder at OneDrive.

## Should this be a repo? Yes, a private GitHub repo
- Version history, plus a safe place to keep the code while you switch laptops.
- GitHub Actions builds the Windows installer on every release tag. You install on any PC by downloading `TyroneSetup-x.y.z.exe` from Releases.
- Code and personal data stay separate: a fresh install on the Dell XPS plus an imported memory file gives you the same Tyrone.

## Quality-of-life ideas for a UW–Madison student (roadmap)

**Already in v0.1:**
- Canvas due dates, a priority briefing ("what's my day look like"), weather, opening sites (Canvas, MyUW, Course Search & Enroll, Handshake), and research with sources.

**Next:**
1. Exam and assignment countdowns, plus a **study planner** that time-blocks your Google Calendar around classes.
2. **Madison Metro** bus arrivals (free developer key, GTFS-realtime): "when's the next 80?"
3. **"Quiz me"** from lecture slides or PDFs, plus flashcards and spaced repetition.
4. Lecture-recording summaries (only where recording is allowed).
5. Focus/Pomodoro mode with a "do not disturb" voice mode.
6. Campus events (today.wisc.edu), Badger game schedules, Rec Well hours, and library room booking links.
7. Enrollment-date and DARS reminders; Handshake/internship deadline tracking.
8. "What's on my screen?" (screenshot → Claude) for homework help or explaining an error.
9. Timers, reminders, Spotify and volume control.
10. Splitting bills with roommates and a simple budget tracker.
11. Dining hall menus, if UW Housing exposes a menu feed.

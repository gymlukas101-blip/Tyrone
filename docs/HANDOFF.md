# Handoff: where Monkey stands

Last updated 2026-11-19 (release v0.3.37: Google sign-in cancel/expiry handling, schedule hint, Settings → Check everything). The owner is now on the Dell XPS 15 9530.

Everything is on `main`. The development sessions run in throwaway cloud containers, so anything not in this repo is gone when one ends. The chat history survives, but not the container's files.

## In progress on branch `feature/computer-agent` (not on main)
- Computer tasks: a durable TaskManager, an execution-layer permission gate, a managed Edge browser through Playwright with the
  official Claude browser toolset, a deterministic course skill, a demo course, a Windows UIA driver, the companion window,
  and the animated banana cursor. Status, the Windows test procedure and results: `docs/COMPUTER-AGENT.md`.
- Banana cursor base art: waiting for the owner's reference PNG as a *file* (`docs/cursor/REFERENCE-ANALYSIS.md`).
- Speech fix shipped on main (v0.3.54+): Whisper on the CPU (NVIDIA without CUDA DLLs broke speech recognition on the Dell).

## Recently shipped
- **v0.3.33–0.3.34: Google sign-in.** The sign-in browser actually opens now:
  - a named `webbrowser` controller and `monkey/links.py` replace the global patch that recursed;
  - a Copy-link fallback;
  - a calendar-link (ICS) option that needs no sign-in;
  - the routing benchmark is in the app.
- **v0.3.34: Outlook.** Monkey no longer launches Outlook. Outlook is opt-in through Settings → Connect, and the availability check is a registry lookup.
- **v0.3.35: voice loudness.** The voice is leveled to about -14 LUFS, like YouTube, calibrated on real speech. There's a voice volume slider and a "match loudness" toggle.
- **v0.3.36: Move to a new PC.** One encrypted `.monkey` file holds memory, chats, settings, voice, Garmin, skills and optionally the keys. Import is staged and swapped in on restart. See `docs/MOVE-TO-NEW-PC.md`.
- **Earlier milestones** (details in `docs/IMPLEMENTATION-NOTES.md`):
  - conversation mode without the wake word, patient endpointing, self-healing listener;
  - memory P0–P3: provenance facts, FTS5 history, importer, memory tools, morning brief, skills;
  - sound kit, Pocket TTS offline voice, Blender rig and clips, fur and lighting.

## Waiting on the owner (on their PC)
1. Settings → **Check everything** → Copy report → paste it into the chat. It shows what works on the Dell.
2. Google: in Google Cloud → Audience → **Publish app** (or add the account as a test user), then Sign in. Check that the Gmail API and Calendar API are enabled in the Google Cloud project.
3. Import the private context pack: Settings → Memory → Import context files. It never goes in this repo.
4. Confirm the class schedule (Morning brief → Detect), or paste a calendar link, then turn the morning brief on.
5. Run the routing benchmark (Settings → Brain → Run benchmark) and share the result, so the router rules and policy can be tuned.

## Next up for development
- Tune the router from the benchmark results.
- Verify on the real Dell:
  - wake word and endpointing with the XPS microphone array;
  - loudness against YouTube;
  - Google end to end.
- If the owner shares a folder through Remote Control, sessions can run the tests and read `%APPDATA%\Monkey\monkey.log` on the real machine.
- Deferred on purpose: subagents, chat channels (Slack/GroupMe/iMessage). See `docs/AGENT-ROADMAP.md`.

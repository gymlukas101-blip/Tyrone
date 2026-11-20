# Monkey (repo: Tyrone)

Monkey is the owner's Windows voice assistant:
- Python app shell (pywebview, tray, hotkey);
- Vite + TypeScript UI with a three.js 3D monkey avatar;
- Claude API brain with tool use;
- Fish Audio and Pocket TTS voices;
- integrations: Gmail/Calendar/Canvas/Garmin/Outlook.

Read `docs/HANDOFF.md` first: it has the current state and the open items. `docs/IMPLEMENTATION-NOTES.md` is the per-change log.

**Before starting any work, read `docs/agent-lessons.md` and follow its rules.** They are lessons from earlier runs: failures, wasted tokens and the owner's corrections. If a rule turns out to be wrong, fix or retire it in the same change and say why.

## Hard rules
- **This repo is PUBLIC.** Never commit, push, log, upload to CI or put in a release:
  - the owner's private context pack (`profile.md`, `preferences.md`, `projects.md`, `classes.md` and the zip they came in);
  - anything from `%APPDATA%\Monkey`;
  - API keys or `.monkey` transfer files.
  - Private files are local input only. `tests/test_private_guard.py` (env `MONKEY_PRIVATE_PACK`) checks this.
- Never ask for API keys in chat. Use the platform's secure credential form. The app stores keys with Windows DPAPI (`monkey/secretstore.py`).
- No commits that name a model version.
- **Ask first** before any of these:
  - outward-facing automation or notifications;
  - sending messages or email;
  - spending money;
  - changing the owner's accounts.
- Out of scope: banking integrations and unofficial Instagram/Snapchat automation.
- Pushing to `main` is approved. Every push to `main` builds and publishes a Velopack release `v0.3.<run>`, which the installed app auto-updates to. Keep `main` green.

## Dev
```bash
python -m venv .venv && .venv/bin/pip install -e ".[desktop,dev]"   # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest -q                                        # all tests (Linux CI skips Windows-only bits)
cd ui && npm ci && npx tsc --noEmit -p . && npm run build            # UI; `npm run dev` = browser demo mode
```
- `?demo` in the UI URL runs without Python. `window.__monkeyEvents([...])` injects backend events for Playwright checks.
- Avatar pipeline: `tools/blender/` (headless bpy; see its README).
- Sound effects: `tools/sfx/`. Raw ElevenLabs takes are in `tools/sfx/raw/`.
- Routing benchmark: `python -m tools.bench_routing [--live]`.

## Where things live
| Area | Code |
|---|---|
| Brain | `monkey/brain/` (agent loop, router + policy, tools, approval gate) |
| Memory | `monkey/memory/` (markdown facts with provenance, SQLite FTS5 history, importer, encrypted PC-transfer export) |
| Audio | `monkey/audio/` (wake word, VAD/endpointing, conversation mode, STT, TTS, speaker + loudness leveler) |
| Routines | `monkey/routines/` (morning brief, Task Scheduler XML) |
| Skills | `monkey/skills/` (SKILL.md, lazy-loaded) |
| UI | `ui/src/` (`main.ts`, `bridge.ts` = Python API surface, `avatar/`) |

The app keeps the owner's data in `%APPDATA%\Monkey`: settings, memory, `monkey.db`, voice, garmin, skills, and `secrets.dat` (DPAPI). The installed app and offline voice pack are in `%LOCALAPPDATA%\Monkey`.

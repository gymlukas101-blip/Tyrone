# Monkey

A Jarvis-style desktop voice assistant for Windows, starring a rigged 3D buff cartoon monkey in a jungle-themed app. Say **"Hey Monkey"**, ask anything, and he answers out loud, lip-syncing, flexing when you finish your work.

![Monkey](assets/monkey.png)

## What he does
- 🐒 **Live 3D avatar** (three.js, `ui/public/models/monkey.glb`):
  - 12 animations: idle, listen, think, talk, happy, laugh, sad, angry, surprised, wave, flex, dance.
  - Lip sync: mouth shapes estimated from the voice audio in real time.
  - Blinking, and cyan eye rings and headset LED that glow with his state.
  - Reactions: he chooses expressions himself, flexes or dances when you finish work, and waves hello.
  - If the PC can't run 3D, he falls back to the 2D SVG monkey.
- 🎙 **Wake word + voice:**
  - "Hey Monkey" works out of the box: open-vocabulary keyword spotting (sherpa-onnx), so no training is needed. There's also a push-to-talk hotkey.
  - Monkey answers in his own designed voice (Fish Audio), and the avatar lip-syncs.
- 🧠 **Smart routing with a stored model policy:** every request is matched to a task, and each task has its own model and effort ([docs/MODEL-POLICY.md](docs/MODEL-POLICY.md)):
  - Haiku for everyday talk and questions, commands, Canvas, Garmin, calendar and quick web lookups.
  - Sonnet for email summaries, triage, briefings and study help.
  - Opus for email drafts in your voice, hard problems and deep research.
  - Say "this is important" or "quick", or use the ⚡/★ buttons, to steer it.
  - See or change the table, and **calibrate it with real measured runs**, in Settings → Brain. There's a monthly budget cap.
- 🔎 **Research:** web search with sources on screen. He shows **pictures** and **YouTube videos** and **opens websites**.
- 📅 **Calendar + email:**
  - Gmail, Google Calendar, wisc.edu Outlook (classic Outlook app) and Canvas due dates.
  - He ranks everything Critical / High / Normal / Low: "what's my day look like?"
- ✉️ **Emails that sound like you:**
  - He learns your style from your Sent folder and drafts replies, which appear on screen in an editable approval card.
  - **Nothing is sent until you click Send, or say "send it" and confirm.** The AI can't send on its own; the app enforces this.
- ✅ **Canvas checklist:**
  - Assignments are ranked by how much of your grade they're worth (from points and the course's group weights), your current grade in that course, whether they're missing, and how soon they're due.
  - Animated checkboxes sync to Canvas's own planner. Checking something off never submits work.
  - "Hey Monkey, what should I work on?"
- ❤️ **Garmin:**
  - Sleep score and sleep stages, heart rate over the day (hover the chart for exact values), resting HR, HRV, body battery, stress and steps.
  - "How did I sleep?"
- 🗂 **Memory:** remembers your classes, people, preferences and writing style in plain markdown files you can read and edit.

## Updates
Monkey updates itself: when a new version is ready, it shows a "Restart & update" pop-up. See [docs/UPDATES.md](docs/UPDATES.md) for the one-time switch from the old zip install.

## Avatar Lab and image generation
- The 🧪 button opens the **Avatar Lab**:
  - It has 8 Monkey design prototypes made with **GPT Image 2.6 Sunburst**, each with a jungle hero image and a front/side/back model sheet for Blender.
  - You can pick a favorite, leave modeling notes, and generate more ideas.
- Monkey can also make pictures on request ("draw me a banana spaceship"). Add an OpenAI key in Settings.
- Sources and design rules: `prototypes/` (`REFERENCES.md`, `directions.json`, a `brief.md` per design). Regenerate with `python tools/prototypes/generate.py`.

## Install (Windows 10/11)
1. Download and run **[Monkey-win-Setup.exe](https://github.com/gymlukas101-blip/Tyrone/releases/latest/download/Monkey-win-Setup.exe)**. This link is always the newest version.
   - If SmartScreen warns you, click More info → Run anyway.
2. On first launch, Monkey offers to **clean up old versions**: old Monkey/Tyrone installs, and old zips or installers in Downloads (they go to the Recycle Bin). It then opens Settings; work through the **Setup checklist** below.
3. After that, updates arrive by themselves ("Restart & update").

The first time you talk to him, Monkey downloads the local speech-recognition model (about 250 MB, once).

## Setup checklist
| Step | Where | Required? |
|---|---|---|
| Anthropic API key | **Have Claude Max?** Claim your free $100/month of API credits (claude.ai → Settings → Billing → API credits), then platform.claude.com → API keys. See [docs/LLM-ACCESS.md](docs/LLM-ACCESS.md#using-your-claude-max-plans-api-credits-recommended) | **Yes** |
| Fish Audio API key | fish.audio → API | Recommended: his real voice (free model until Nov 30, 2026), and needed once to make his voice set. After that, the offline voice (Settings → Sound) keeps his voice with no key. |
| Design Monkey's voice | Settings → *Design voices* → listen → *Use this one* | Recommended |
| Google (Gmail + Calendar) | See [Google setup](#google-setup) | Optional |
| wisc.edu Outlook | Install and sign in to **classic Outlook**, then Settings → *Test connection* | Optional |
| Canvas due dates | Canvas → Calendar → *Calendar Feed* → copy link → Settings | Optional |
| Canvas API token (grades + points) | Request one with the Learn@UW form "Student Request for Canvas Access Token" (kb.wisc.edu/156712). After it arrives, activate it in Canvas, then go to Settings → API keys | Optional; without it, ranking uses due dates only |
| Garmin | Settings → Garmin: sign in with your email and password, plus the verification code if Garmin asks | Optional |
| Learn my writing style | Settings → *Learn my writing style* (after connecting email) | Recommended |
| YouTube key | Google Cloud → enable *YouTube Data API v3* → API key | Optional (for videos) |
| Sharper "Hey Monkey" wake word (trained model) | [wakeword/README.md](wakeword/README.md) | Optional; "Hey Monkey" already works without it |

### Google setup
1. Go to console.cloud.google.com and create a project, e.g. "Monkey".
2. Enable the **Gmail API** and the **Google Calendar API**.
3. Set up the OAuth consent screen:
   - User type: External. Add yourself as a test user.
   - Then click **Publish app**, so it's *In production*. Unverified is fine for personal use; in Testing mode Google logs you out every 7 days.
4. Go to Credentials → Create credentials → OAuth client ID → **Desktop app**, and download the JSON.
5. In Monkey, go to Settings → Accounts, paste the JSON, click **Sign in**, and approve in the browser.
6. Optional, for **inbox cleanup** (archive and label, never delete): Google Auth Platform → **Data access** → Add or
   remove scopes → add `https://www.googleapis.com/auth/gmail.modify` (and `.../auth/gmail.settings.basic` for
   "skip the inbox" filters after unsubscribing) → Save. Monkey asks for it per inbox, the first time you clean one up
   (Google's incremental consent: the screen lists only the new permission). Read-only accounts keep working without it.

### Why classic Outlook for wisc.edu?
UW–Madison's Microsoft 365 requires IT admin approval for third-party apps that read your mail through Microsoft's API. Monkey works through the Outlook desktop app on your PC instead. It's already signed in, and nothing leaves your machine except what Claude needs to answer you. "New Outlook" doesn't support this, so use classic Outlook.

## Moving to another PC (e.g. your Dell XPS)
1. On the old PC, go to Settings → Memory → enter a password → **Export**. This saves `Documents\Monkey-backup-*.monkey`.
2. On the new PC, install from Releases, then go to Settings → Memory → **Import** with the same password.
3. Re-enter your API keys. They're encrypted to your Windows account on each PC, so they can't be copied over and are never exported.

Alternatively, set the memory **sync folder** to a OneDrive folder on both PCs.

## Privacy
| Data | Where it lives |
|---|---|
| Memory | `%APPDATA%\Monkey\memory\memories\*.md` (plain text, yours to edit) |
| Settings and spend ledger | `%APPDATA%\Monkey\` |
| API keys and Google token | `%APPDATA%\Monkey\secrets.dat`, encrypted with Windows DPAPI (only your Windows account on this PC can read it). Keys saved by older versions in Credential Manager move over automatically |
| Chat history | `%APPDATA%\Monkey\monkey.db` (last messages show again when you reopen Monkey; ⟲ starts fresh) |
| Monkey's voice set + voice sample | `%APPDATA%\Monkey\sfx\vocal\*.wav`, `%APPDATA%\Monkey\voice\monkey-ref.wav` (made once with Settings → Sound) |
| Offline voice model | `%LOCALAPPDATA%\Monkey\voice-pack` (~200 MB, Kyutai Pocket TTS run with sherpa-onnx) |

What gets sent where:
- **Anthropic** receives your requests and the email, calendar and memory content needed to answer them.
- **Fish Audio** receives the text Monkey speaks. With the free `s2.1-pro-free` model (the default, free through Nov 30, 2026) Fish may use that text to improve its models; turn it off in Settings → Voice, or set Settings → Sound → Offline voice to "Always".
- **The offline voice** runs entirely on your PC: nothing is sent anywhere. It clones Monkey's voice from the sample saved by "Make Monkey's voice set". Only clone voices you have the right to use.
- **Speech-to-text** is local by default.

Email and web content is treated as untrusted data: Monkey is instructed not to follow instructions inside emails or web pages.

## Cost (typical student use)
| Service | Approx. per month |
|---|---|
| Claude (auto-routed per task) | ~$15–25 at heavy use with the calibrated policy (measured ~$15–17; ~$51 if everything were "Important"). **$0 extra with Claude Max**, whose $100/month of API credits cover it (see docs/MODEL-POLICY.md, docs/LLM-ACCESS.md) |
| Fish Audio voice | $1–3 |
| Speech-to-text (local Whisper) | $0 |
| Google, YouTube, NWS weather, Canvas feed | $0 |

Settings shows your spend this month and lets you set a hard monthly budget.

## Development
```bash
python -m venv .venv
```
```bash
.venv\Scripts\activate
```
```bash
pip install -e ".[desktop,dev]"
```
```bash
cd ui && npm ci && npm run build && cd ..
```
```bash
python -m monkey
```
- Tests: `pytest`.
- UI in a normal browser (demo mode, no Python): `cd ui && npm run dev`.
- Build an installer: push a tag like `v0.1.0`. GitHub Actions runs the tests, builds `Monkey.exe` with PyInstaller, self-tests it, packages it with Inno Setup, and attaches `MonkeySetup-v0.1.0.exe` to a GitHub Release.

### Layout
```
monkey/brain/         router (model choice), agent loop, tools, approval gate, ranking, persona
monkey/audio/         wake word + mic, end-of-speech detection, speech-to-text, Fish TTS, speaker
monkey/integrations/  Gmail/Google Calendar, Outlook (COM), Canvas ICS, images/videos/weather, style learner
monkey/memory/        memory tool backend, encrypted export/import
ui/                   Vite + TypeScript: avatar, chat, cards, approval card, settings
installer/            Inno Setup script
docs/RESEARCH.md      research notes and roadmap
```

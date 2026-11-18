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
- 🧠 **Smart routing:** each request goes to the right Claude model and effort level:
  - Haiku for chit-chat, Sonnet for normal questions, Opus for research, drafting and ranking.
  - Say "this is important" or "quick", or use the ⚡/★ buttons, to steer it.
  - There's a monthly budget cap.
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

## Install (Windows 10/11)
1. Go to this repo's **Releases** page and download `MonkeySetup-<version>.exe`.
2. Run it. It installs per-user, with no admin rights needed. Tick "Start with Windows" if you like.
3. Monkey opens Settings on first launch. Work through the **Setup checklist** below.

The first time you talk to him, Monkey downloads the local speech-recognition model (about 250 MB, once).

## Setup checklist
| Step | Where | Required? |
|---|---|---|
| Anthropic API key | console.anthropic.com → API keys | **Yes** |
| Fish Audio API key | fish.audio → API | Yes, for his real voice. Without it he falls back to the Windows voice. |
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

### Why classic Outlook for wisc.edu?
UW–Madison's Microsoft 365 requires IT admin approval for third-party apps that read your mail through Microsoft's API. Monkey works through the Outlook desktop app on your PC instead. It's already signed in, and nothing leaves your machine except what Claude needs to answer you. "New Outlook" doesn't support this, so use classic Outlook.

## Moving to another PC (e.g. your Dell XPS)
1. On the old PC, go to Settings → Memory → enter a password → **Export**. This saves `Documents\Monkey-backup-*.monkey`.
2. On the new PC, install from Releases, then go to Settings → Memory → **Import** with the same password.
3. Re-enter your API keys. They live in each PC's Windows Credential Manager and are never exported.

Alternatively, set the memory **sync folder** to a OneDrive folder on both PCs.

## Privacy
| Data | Where it lives |
|---|---|
| Memory | `%APPDATA%\Monkey\memory\memories\*.md` (plain text, yours to edit) |
| Settings and spend ledger | `%APPDATA%\Monkey\` |
| API keys and Google token | Windows Credential Manager |

What gets sent where:
- **Anthropic** receives your requests and the email, calendar and memory content needed to answer them.
- **Fish Audio** receives the text Monkey speaks.
- **Speech-to-text** is local by default.

Email and web content is treated as untrusted data: Monkey is instructed not to follow instructions inside emails or web pages.

## Cost (typical student use)
| Service | Approx. per month |
|---|---|
| Claude (auto-routed) | ~$20–25 on the "Saver" profile, ~$40–50 on "Best" at heavy use (see docs/LLM-ACCESS.md) |
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

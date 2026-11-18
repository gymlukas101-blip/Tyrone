# Tyrone

A Jarvis-style desktop voice assistant for Windows. Say **"Yo Tyrone"**, ask anything, and he answers out loud as an animated cartoon character.

![Tyrone](assets/tyrone.png)

## What he does
- 🎙 **Wake word + voice:**
  - "Yo Tyrone" (or "Hey Jarvis" until the custom wake word is trained), plus a push-to-talk hotkey.
  - Tyrone answers in his own designed voice (Fish Audio), and the avatar lip-syncs.
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
- 🗂 **Memory:** remembers your classes, people, preferences and writing style in plain markdown files you can read and edit.

## Install (Windows 10/11)
1. Go to this repo's **Releases** page and download `TyroneSetup-<version>.exe`.
2. Run it. It installs per-user, with no admin rights needed. Tick "Start with Windows" if you like.
3. Tyrone opens Settings on first launch. Work through the **Setup checklist** below.

The first time you talk to him, Tyrone downloads the local speech-recognition model (about 250 MB, once).

## Setup checklist
| Step | Where | Required? |
|---|---|---|
| Anthropic API key | console.anthropic.com → API keys | **Yes** |
| Fish Audio API key | fish.audio → API | Yes, for his real voice. Without it he falls back to the Windows voice. |
| Design Tyrone's voice | Settings → *Design voices* → listen → *Use this one* | Recommended |
| Google (Gmail + Calendar) | See [Google setup](#google-setup) | Optional |
| wisc.edu Outlook | Install and sign in to **classic Outlook**, then Settings → *Test connection* | Optional |
| Canvas due dates | Canvas → Calendar → *Calendar Feed* → copy link → Settings | Optional |
| Learn my writing style | Settings → *Learn my writing style* (after connecting email) | Recommended |
| YouTube key | Google Cloud → enable *YouTube Data API v3* → API key | Optional (for videos) |
| "Yo Tyrone" wake word | [wakeword/README.md](wakeword/README.md) | Optional; "Hey Jarvis" works meanwhile |

### Google setup
1. Go to console.cloud.google.com and create a project, e.g. "Tyrone".
2. Enable the **Gmail API** and the **Google Calendar API**.
3. Set up the OAuth consent screen:
   - User type: External. Add yourself as a test user.
   - Then click **Publish app**, so it's *In production*. Unverified is fine for personal use; in Testing mode Google logs you out every 7 days.
4. Go to Credentials → Create credentials → OAuth client ID → **Desktop app**, and download the JSON.
5. In Tyrone, go to Settings → Accounts, paste the JSON, click **Sign in**, and approve in the browser.

### Why classic Outlook for wisc.edu?
UW–Madison's Microsoft 365 requires IT admin approval for third-party apps that read your mail through Microsoft's API. Tyrone works through the Outlook desktop app on your PC instead. It's already signed in, and nothing leaves your machine except what Claude needs to answer you. "New Outlook" doesn't support this, so use classic Outlook.

## Moving to another PC (e.g. your Dell XPS)
1. On the old PC, go to Settings → Memory → enter a password → **Export**. This saves `Documents\Tyrone-backup-*.tyrone`.
2. On the new PC, install from Releases, then go to Settings → Memory → **Import** with the same password.
3. Re-enter your API keys. They live in each PC's Windows Credential Manager and are never exported.

Alternatively, set the memory **sync folder** to a OneDrive folder on both PCs.

## Privacy
| Data | Where it lives |
|---|---|
| Memory | `%APPDATA%\Tyrone\memory\memories\*.md` (plain text, yours to edit) |
| Settings and spend ledger | `%APPDATA%\Tyrone\` |
| API keys and Google token | Windows Credential Manager |

What gets sent where:
- **Anthropic** receives your requests and the email, calendar and memory content needed to answer them.
- **Fish Audio** receives the text Tyrone speaks.
- **Speech-to-text** is local by default.

Email and web content is treated as untrusted data: Tyrone is instructed not to follow instructions inside emails or web pages.

## Cost (typical student use)
| Service | Approx. per month |
|---|---|
| Claude (auto-routed) | $5–20 |
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
python -m tyrone
```
- Tests: `pytest`.
- UI in a normal browser (demo mode, no Python): `cd ui && npm run dev`.
- Build an installer: push a tag like `v0.1.0`. GitHub Actions runs the tests, builds `Tyrone.exe` with PyInstaller, self-tests it, packages it with Inno Setup, and attaches `TyroneSetup-v0.1.0.exe` to a GitHub Release.

### Layout
```
tyrone/brain/         router (model choice), agent loop, tools, approval gate, ranking, persona
tyrone/audio/         wake word + mic, end-of-speech detection, speech-to-text, Fish TTS, speaker
tyrone/integrations/  Gmail/Google Calendar, Outlook (COM), Canvas ICS, images/videos/weather, style learner
tyrone/memory/        memory tool backend, encrypted export/import
ui/                   Vite + TypeScript: avatar, chat, cards, approval card, settings
installer/            Inno Setup script
docs/RESEARCH.md      research notes and roadmap
```

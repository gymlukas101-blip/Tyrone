# Moving Monkey (and your stuff) to a new PC

This guide is written for moving from the school PC to a Dell XPS 15 9530. It works for any Windows PC.

## What moves, and how
| Thing | Where it lives now | How it moves |
|---|---|---|
| Monkey's code, sounds, avatar, docs | GitHub (`Tyrone` repo) | Already safe. Nothing to do. |
| Your memory, chats, settings, Monkey's voice set, Garmin sign-in, your skills | `%APPDATA%\Monkey` | **Settings → Memory → Move to a new PC → Export** (one encrypted `.monkey` file) |
| API keys, Google sign-in, Canvas token, calendar links | `%APPDATA%\Monkey\secrets.dat`, locked to this PC by Windows | Inside the same `.monkey` file (tick "Include my API keys"), protected by your password |
| Google OAuth client file (`client_secret_….json`) | Saved inside Monkey, and in your Downloads | Moves with the keys. **Also copy the original file.** Google shows the secret only once, at creation. |
| The Monkey app and its offline voice (200 MB) | `%LOCALAPPDATA%\Monkey` | Don't copy. Reinstall and re-download (two clicks). |
| The morning-brief schedule | Windows Task Scheduler | Doesn't move. Click Enable again on the new PC. |
| This chat with Claude | Your claude.ai account | Moves by itself. Sign in on the new PC. |
| Your own files: Desktop, Documents, Downloads, Pictures | The school PC | USB drive or your **personal** Google Drive |

Don't use the school OneDrive to move personal things: that account goes away when you leave UW. Windows' own "Windows Backup" transfer won't help either. It needs a personal Microsoft account, and school-managed PCs don't get it.

## A. On the school PC (about 10 minutes)
1. Open Monkey → Settings → Images & updates → **Check now** and install the update.
   - You need v0.3.36 or newer. The version is shown at the bottom of Settings.
2. Settings → Memory → **Move to a new PC**:
   - Type a password (8+ characters) you'll remember. Without it the file can't be opened.
   - Leave **Include my API keys and sign-ins** ticked.
   - Click **Export for new PC**. You get `Documents\Monkey-transfer-<date>.monkey`.
   - **Open folder** shows it.
3. Copy these to a USB drive, or upload them to your personal Google Drive:
   - the `Monkey-transfer-….monkey` file;
   - `client_secret_….json` from Downloads;
   - your private context-pack zip (the one with `profile.md` and the others);
   - your own files from Desktop, Documents, Downloads and Pictures. Skip installers you can download again.
4. Quick inventory, so you don't forget anything:
   - Settings → Apps: note anything you'll reinstall.
   - Browser: turn on sync with your **personal** Google account (Chrome) or Microsoft account (Edge) so bookmarks and passwords follow you. Don't export passwords to a CSV file.
   - If a folder `%USERPROFILE%\.claude` exists (Claude Code was used there): copy `CLAUDE.md`, `settings.json` and `skills\`. **Never copy `.credentials.json`**; just sign in again.

## B. On the Dell XPS 15 9530
1. **Windows Update** until nothing is left.
2. Open **Dell Command | Update** (or SupportAssist) for BIOS and drivers. The audio and microphone drivers matter for "Hey Monkey".
3. Settings → Privacy & security → **Microphone**: turn on "Let desktop apps access your microphone".
4. Install Monkey:
   - Download `Monkey-win-Setup.exe` from <https://github.com/gymlukas101-blip/Tyrone/releases/latest> and run it.
   - If Windows says "Windows protected your PC": **More info → Run anyway**. The app isn't code-signed yet.
5. In Monkey → Settings → Memory → **Move to a new PC**:
   - type the **same password**;
   - click **Import from old PC** and pick the `.monkey` file;
   - click **Restart Monkey**.
   - Monkey reopens and lists what moved in. Anything it replaced is kept in `%APPDATA%\Monkey\backups\pre-transfer-…`.
6. One-time steps for the new PC:
   - Settings → Morning brief → **Enable**, under "Prepare it even when Monkey is closed".
   - Settings → Sound → Offline voice → **Download**.
   - Settings → Accounts: Google should show connected. If it says to sign in, click **Sign in**.
   - School email (optional): install **Microsoft 365 Apps** from UW's Office 365 page, sign in with wisc.edu, open Outlook once, then Settings → Accounts → wisc.edu Outlook → **Connect**.
     - Use classic Outlook. Monkey can't read the "new Outlook", and Outlook 2016 no longer gets security updates.
7. Context pack (if you haven't imported it yet):
   - unzip it;
   - Settings → Memory → **Import context files** → Choose files and preview… → **Apply import**.
8. Say "Hey Monkey" and check:
   - your old chats are in the history;
   - his voice sounds right;
   - he's about as loud as a YouTube video.

## C. Keep working with Claude on the new PC
- Sign in to the **same** account at <https://claude.ai/code>, or in the Claude desktop app (<https://claude.ai/download>) on its Code tab.
- This conversation is in the session list: pick it and keep going. Connectors (Gmail, Calendar, Drive, Figma) and the GitHub link are tied to your account, so they come along.
- Optional, for hands-on testing: install Git and clone Tyrone. Then in the Claude desktop app → Settings → Claude Code → **Remote Control**, share that folder.
  - Claude can then run tests and read Monkey's log on your real PC.
  - This feature isn't available on every account yet.

## D. Clean up the school PC (only after B works)
1. Uninstall Monkey (Settings → Apps → Monkey).
2. Delete these folders: `%APPDATA%\Monkey` and `%LOCALAPPDATA%\Monkey`. Paste each into the File Explorer address bar to find it.
3. If you had enabled the morning brief there, run this in a Command Prompt:
   `schtasks /Delete /TN "Monkey\Morning brief" /F`
4. Delete the `.monkey` file and the `client_secret_….json` from the school PC, and from the USB drive or Drive once you're done.
5. Sign out of the Claude app and your browsers on the school PC.
6. **Don't** revoke Monkey's Google access or delete the Canvas token: the new PC uses the same ones.
   - Optional, later: create fresh API keys on the new PC and delete the old ones in each provider's dashboard.

## If something goes wrong
- **"Wrong password"**: it's the password you typed when exporting. Nothing was changed.
- **Monkey reopens without your stuff**: quit from the tray, open it again. The swap finishes on the next start.
- **Want the fresh install back?** Your pre-move files are in `%APPDATA%\Monkey\backups\pre-transfer-…`.

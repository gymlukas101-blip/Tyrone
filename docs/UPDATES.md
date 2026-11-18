# Updating Monkey (no more zips)

Monkey updates itself through [Velopack](https://docs.velopack.io/) and this repo's GitHub Releases.

## One-time switch
1. **Make the repo public:** GitHub → Settings → General → Danger Zone → Change visibility → Public.
   - The app downloads updates without a login, so it needs this.
   - Nothing private is in the repo: API keys are stored in Windows Credential Manager, and your memory and settings are in `%APPDATA%\Monkey`.
2. **Install the Velopack version once.**
   - Download `Monkey-win-Setup.exe` from [Releases → latest](https://github.com/gymlukas101-blip/Tyrone/releases/latest) and run it.
   - It installs to `%LocalAppData%\Monkey` with Start menu and desktop shortcuts.
3. **Uninstall the old version** ("Monkey" from the zip/Inno installer) in Windows Settings → Apps.
   - Your memory, settings and keys stay: they live outside the app folder.

## After that
- **Checks:** Monkey checks for updates on launch and every 6 hours.
- **Downloads:** it downloads in the background, often only the changed parts (delta updates).
- **Install:** a pop-up appears: **"Monkey x.y.z is ready → Restart & update"**. That takes a few seconds.
- **Manual check:** Settings → Images & updates → **Check now**. You can also turn automatic downloads off there.

## How releases are made
Every push to `main` triggers `.github/workflows/build.yml`:
1. It runs the tests, builds `Monkey.exe` with PyInstaller and self-tests it.
2. It stamps version `0.3.<build number>`.
3. It runs `vpk pack`, which builds the installer, the full package and a delta from the previous release.
4. It runs `vpk upload github --publish`, which creates the GitHub Release with `releases.win.json`, the packages and `Setup.exe`.

The old Inno Setup installer is still built as a CI artifact for one more round, then it'll be retired.

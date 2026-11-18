# Updating Monkey (no more zips)

Monkey updates itself through [Velopack](https://docs.velopack.io/) and this repo's GitHub Releases.

## One-time switch
1. **Make the repo public:** GitHub → Settings → General → Danger Zone → Change visibility → Public.
   - The app downloads updates without a login, so it needs this.
   - Nothing private is in the repo: API keys are stored in Windows Credential Manager, and your memory and settings are in `%APPDATA%\Monkey`.
2. **Install the Velopack version once.**
   - Download `Monkey-win-Setup.exe` from [Releases → latest](https://github.com/gymlukas101-blip/Tyrone/releases/latest) and run it.
   - It installs to `%LocalAppData%\Monkey` with Start menu and desktop shortcuts.
3. **Old versions are cleaned up for you.**
   - On first launch, Monkey shows a "Clean up old Monkey" card listing what it found:
     - old installs from the zip/Inno installer, named "Monkey" or "Tyrone"
     - old `MonkeySetup`/`TyroneSetup` zips, unzipped folders and installers in your Downloads
   - One click uninstalls the old apps and moves the downloads to the Recycle Bin.
   - Your memory, settings and keys stay.
   - You can run it again any time: Settings → Images & updates → **Clean up old installs**.
   - Monkey also adds itself to "start with Windows" (the setting is in Settings).

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

The old Inno Setup installer is retired. `installer/monkey.iss` stays only as the record of its AppId, which the cleanup uses to find old installs.

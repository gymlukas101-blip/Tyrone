# Phone screen time → Monkey's to-do list

Research for the owner's request "add connecting to my phone's screen time to the task queue" (2026-11-23), and
what was built from it. **The owner's phone is an iPhone**, so the iPhone is the primary path and the default in
Settings; Android is kept as a secondary path because it was cheap to support. Code:
`monkey/integrations/screentime.py`, `ui/src/screentime.ts`; tests: `tests/test_screentime.py`,
`tests/test_screentime_ui.py`.

**Bottom line:** no phone lets a Windows app read its screen time. The phone has to hand over a summary, and on an
iPhone what it can hand over is limited by what Shortcuts can read. None of the paths needs an open port on the PC.

| Phone | Path in Monkey | What it gets | Owner effort |
|---|---|---|---|
| **iPhone, iOS 26+** (primary) | Shortcuts automation → **Get App & Website Data** → JSON file in **iCloud Drive** → iCloud for Windows → Monkey reads the folder | per-app minutes for today; total = the sum of the apps (or the action's total, if it has one) | ~5 min once |
| **iPhone, any iOS** (zero setup, also the fallback) | **Type it in**: today's total and the top app (+ its time) from Settings → Screen Time, in the To-do panel's phone card | total + top app | ~10 s a day |
| Android (secondary) | **Tasker** (App Info, usage access) → encrypted with a pairing key → private **ntfy** topic → Monkey polls it | per-app minutes, total, optional pickups | ~10 min once |
| Android, no relay | Tasker writes the JSON into a **Syncthing** folder shared with the PC | same | ~15 min, plus Syncthing on the PC |
| Either | **Import** a JSON/CSV file | whatever is in the file | – |

Everything is **off by default** (Settings → Phone). Nothing is set up on the owner's phone or accounts by Monkey.

### Impossible on iPhone (don't try these)

- **Reading Screen Time from the PC or from iCloud.** There is no public export API, no web view of it on
  icloud.com, and no file Windows can open. iCloud syncs Screen Time only to the owner's other Apple devices
  (CloudKit, end-to-end encrypted) [7]; iCloud for Windows doesn't get it.
- **Exporting from the Screen Time screens** in Settings: there's no share/export button.
- **Our own iOS app sending the numbers out.** The DeviceActivity/FamilyControls frameworks show per-app usage only
  inside a `DeviceActivityReport` extension, whose sandbox blocks the network, App Group writes, the pasteboard and
  iCloud key-value sync on purpose [4][5][6]. It would also need Apple's Family Controls entitlement, a developer
  account and an app on the owner's phone.
- **Pickups, notification counts and the weekly report from Shortcuts**: no action reads them (only the iOS 26 app &
  website usage action exists). Before iOS 26 Shortcuts could read nothing at all about Screen Time ("Get screen
  time" never existed).
- **Encrypting in Shortcuts**: there is no AES/encrypt action, so an iPhone Shortcut can't seal a payload for a
  public relay. That's why the iPhone path uses the owner's own iCloud Drive instead of ntfy.
- **Screen Time on the Mac route** (`knowledgeC.db`/Biome with Full Disk Access [8][9]) needs a Mac; the owner has a
  Windows PC.

Possible but not built: OCR of a Screen Time screenshot (fragile across iOS versions and languages; typing the two
numbers is quicker), and "App closed" automations that time single apps (made unnecessary by the iOS 26 action).

## 1. iPhone

### What is and isn't possible (as of November 2026)

- **No export API.** Apple has never offered a way for another device or app to read Screen Time history. The
  Settings → Screen Time screens can't be exported.
- **Shortcuts: there is now a Screen Time action.** iOS 26 added a Shortcuts action under *Screen Time* named
  **"Get App & Website Data"** (iOS, iPadOS, macOS) [1][2]. One write-up describes running it nightly at 23:30,
  getting "every App and Website that has had >=1 minute of usage in a given day", and POSTing the result to an
  endpoint [3]. **Not verified here:** Apple's pages list the action but don't document its inputs or output
  fields, and this session couldn't run iOS. So Monkey's parser is deliberately lenient: the Shortcut can pass the
  action's output as plain text (`apps_text`), and Monkey reads lines like `Instagram: 1h 2m`, `YouTube 31 min`,
  `Messages, 0:12`. If the action also gives a total, the Shortcut can add it as `total`; if not, Monkey uses the sum
  of the apps and marks it "sum of apps". **The owner should check the action's output in the Shortcuts editor on
  the first run** (tap the action's result) and tell us what it shows.
  - There is still no "get pickups" or "get notifications count" action that we could find.
  - Before iOS 26 there was no Screen Time action at all; "Get screen time" never existed.
- **DeviceActivity / FamilyControls / ManagedSettings (Screen Time API):** only for an iOS app we would have to build,
  sign and ship, with Apple's Family Controls entitlement for the app *and* each extension. The per-app usage numbers
  are only available inside a `DeviceActivityReport` extension, which runs in a sandbox that blocks network requests,
  App Group writes, the pasteboard and iCloud key-value sync, "in order to preserve the user's privacy" [4][5][6].
  So even our own iOS app couldn't send the numbers to the PC. The `DeviceActivityMonitor` extension only gets
  threshold events ("Instagram passed 30 minutes"), not totals. **Not worth it** for one owner.
- **Focus modes / personal automations:** an "App is opened/closed" automation can time individual apps, but it's
  fragile and the new action makes it unnecessary. Time-of-day automations can run without asking ("Run
  Immediately"), which is what the setup uses.
- **iCloud Screen Time sync goes only to the owner's other Apple devices.** With "Share Across Devices" on, Screen
  Time data syncs through CloudKit with end-to-end encryption [7]; a Mac then holds it in a local database
  (`knowledgeC.db` / Biome) that tools like Timing or a home-assistant exporter read with Full Disk Access [8][9].
  Windows can't take part (iCloud for Windows syncs Drive, Photos, Passwords, not Screen Time), and the Mac database
  format changes between macOS versions. **Not usable** on the owner's Windows PC.
- **Screenshot OCR of the Screen Time page:** possible (Windows has a built-in OCR engine), but the layout changes
  with every iOS version and language and it needs a screenshot every day. Not built; the manual total covers the
  same case in less effort.

### Transport

iCloud Drive is the natural carrier: Shortcuts' **Save File** writes into iCloud Drive, and **iCloud for Windows**
(Microsoft Store) syncs iCloud Drive to `C:\Users\<you>\iCloudDrive`. The data stays inside the owner's own Apple
account (end-to-end encrypted too if Advanced Data Protection is on); no third party, no relay, no open port.
Shortcuts can't do AES, so an encrypted relay isn't practical from an iPhone anyway.

### iPhone setup, automatic (iOS 26+; Settings → Phone shows the same steps)

1. PC: install **iCloud for Windows** from the Microsoft Store, sign in, turn on **iCloud Drive**.
2. iPhone (iOS 26+): **Files** → iCloud Drive → new folder **Monkey**.
3. **Shortcuts** → Automation → **+** → **Time of Day** → 9:00 PM, Daily → **Run Immediately** → New Blank Automation.
4. Add **Screen Time → Get App & Website Data**, set to **Today**.
5. Add **Text** with the result of that action in it.
6. Add **Dictionary**: `schema` = `monkey-screentime`, `v` = 1, `platform` = `ios`, `device` = `iPhone`,
   `date` = Current Date formatted *Custom* `yyyy-MM-dd`, `apps_text` = the Text. If the action offers a total,
   add `total` = it (`2h 14m` or minutes).
7. **Set Name** → `screentime-<formatted date>.json`, then **Save File** → iCloud Drive/Monkey, *Ask Where to Save*
   off, *Overwrite If File Exists* on.
8. Run it once by hand and allow Screen Time access. Duplicate the automation for midday and 11:55 PM so the to-do
   panel stays current during the day.
9. Monkey: Settings → Phone → turn on → iPhone → *Shortcuts → iCloud Drive* → **Check now**.

### iPhone setup, typed (any iOS, no setup)

1. Monkey: Settings → Phone → turn on → iPhone → *I'll type it in: total + top app*.
2. In the evening, open the iPhone's **Settings → Screen Time** (*See All App & Website Activity* → Day): read the
   total and the top app.
3. Monkey → To-do → phone card → *Type today's total*: e.g. `2h 40m`, `Instagram`, `1h 5m` → Save. Typing it again
   later the same day replaces it. App goal to-dos for the top app count it.

## 2. Android (secondary)

### What is and isn't possible

- **`UsageStatsManager`** (API 21+) gives per-app foreground time for any time range to an app the user has granted
  **Usage access** (`PACKAGE_USAGE_STATS`, a special permission set in Settings) [10]. Digital Wellbeing builds its
  dashboard from the same data but has no export.
- **Automation apps that read it:** Tasker's **App Info** action (since 5.8) returns "the time you spent on the apps
  … in a given timespan" for the most-used apps, using the usage-stats permission [11]. Automate (LlamaLab) has an
  App usage block too, but users report its *total* for the current day can be off by hours, while per-app values
  are right [12]. MacroDroid: no usage-time action found. **Recommendation: Tasker** (paid, one-time).
  **Not verified here:** the exact names of App Info's output variables; the script expects `%app_name()` and
  `%app_time()` (milliseconds) and says to rename them if the action's variable list differs.
- **Pickups:** not in App Info; Tasker can count *Display Unlocked* events into `%MONKEY_PICKUPS` (optional step).
- **Phone Link (Windows):** asks for an "app usage" permission so it can show and launch phone apps, but shows no
  screen-time report and has no API for one [13]. **Not usable.**
- **A companion app of our own** would work (UsageStatsManager + a POST), but building, signing and installing an APK
  is more owner effort than Tasker and adds a thing to maintain. Not built.

### Transport: an encrypted relay (no inbound port)

The phone can't reach the PC directly without opening a port or a tunnel, so it posts to a private topic on
**ntfy** (`ntfy.sh`, free, or a self-hosted server) and Monkey polls the topic over outbound HTTPS
(`GET <server>/<topic>/json?poll=1&since=<last id>`). ntfy.sh keeps messages for about 12 hours, so the phone posts
hourly and Monkey polls every 20 minutes while it runs.

ntfy has no end-to-end encryption of its own (a long-open feature request [14]), and anyone who learns a topic name
can read and post to it. So Monkey **never accepts plain messages on the topic**: each one is sealed on the phone.

- **Pairing:** Settings → Phone → *Pair phone* makes a random topic (`monkey-st-` + 24 random characters) and a
  256-bit key, stored on the PC with Windows DPAPI (`keys.py`, `screentime_pair`; it is *not* in the PC-transfer
  export, so a new PC pairs again). The PC shows `https://ntfy.sh/<topic>#<key>` as a QR code; the owner scans it
  with the phone camera and pastes the text into a Tasker variable. The key never goes to the relay: the script
  splits it off before posting.
- **Format `mst1`:** `mst1.<iv>.<ciphertext>.<mac>` (base64). AES-256-CBC with PKCS#7 padding, then HMAC-SHA256 over
  `mst1.<iv>.<ciphertext>` (encrypt-then-MAC), with separate encryption and MAC keys derived from the pairing key by
  HMAC-SHA256. CBC+HMAC rather than GCM because the phone side runs in Tasker's JavaScriptlet with
  **crypto-js 4.2.0** (pinned on cdnjs), which has AES-CBC and HMAC but no GCM. Monkey checks the MAC (constant
  time) before decrypting; a wrong key, a flipped bit or an unsealed message is dropped and reported in Settings.
  The phone script was run under Node with crypto-js 4.2.0 and its output opened by Monkey's Python; a fixed-IV
  vector from crypto-js is pinned in `tests/test_screentime.py`.
- **Replays:** within a day totals only grow, so Monkey keeps the larger automatic reading; an old message replayed
  can't roll a day back. Manual entries always win.

**Alternative without any relay:** Syncthing (Syncthing-Fork on the phone, Syncthing on the PC) syncs a phone
folder straight to the PC, encrypted, peer to peer. Tasker writes the JSON there and Monkey reads it as a folder
inbox. More to install on the PC, so it's the second choice.

**Note on the notifications work:** ntfy phone *notifications* (PC → phone) are on `feature/todo-notifications`,
approved to merge. That branch wasn't on the remote while this was built, so there was no code to share. The uses
stay separate on purpose: notifications publish to the phone; screen time is polled from the phone on its own
topic, and only messages sealed with the screen-time pairing key are accepted. The key is made on the PC, kept in
DPAPI, shown once as a QR code for the phone, and never sent to the relay. Only the relay address is shared: with
no screen-time relay set, Monkey uses the reminders' `ntfy_server`, else ntfy.sh. The pairing QR code uses the
same `qrcode-generator` helper as the reminders (`qrSvg` in `ui/src/reminders.ts`), drawn locally.

### Android setup (what the owner does; Settings → Phone shows the same steps and the script)

1. Install **Tasker** (Google Play). Android Settings → Apps → Special app access → **Usage access** → allow Tasker.
2. Monkey: Settings → Phone → turn on → Android → *Encrypted relay* → **Pair phone** → *Show the pairing code*;
   scan the QR code with the phone camera and copy the text.
3. Tasker → Vars → add global **`MONKEY_PAIR`** = that text. (It's the key: keep it private.)
4. New task *Monkey screen time*:
   1. **App → App Info**: most used apps, time span today. Check the output variable names.
   2. **Code → JavaScriptlet**: Libraries `https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.2.0/crypto-js.min.js`;
      Code: Settings → Phone → *Copy script* (`TASKER_JS` in `screentime.py`).
   3. **Net → HTTP Request**: POST, URL `%st_url`, Body `%st_body`.
5. Profile: **Time** 08:00–23:59, every 1 hour → the task. Optional: a *Display Unlocked* profile adding 1 to
   `%MONKEY_PICKUPS`, and a midnight profile resetting it.
6. Run the task once; in Monkey click **Check now**.

## 3. What Monkey does with it (built)

- **Store:** `monkey.db`, tables `screentime_days` (one row per day: total, pickups, top 30 apps, device, source),
  `screentime_goals`, `screentime_seen` (files and relay messages already read), `screentime_meta`. Kept 30 days by
  default (`screentime_keep_days`). Settings → Phone → **Forget data** deletes it (goal to-dos stay: they're the
  owner's to-dos). Nothing goes into memory files or the repo.
- **Untrusted input:** payloads ≤ 64 KB, ≤ 120 days per import, ≤ 30 apps; minutes 0–1440, pickups 0–5000; dates
  within the kept window and at most a day ahead; durations must be clean (`2h of TikTok` is refused); app names
  are NFKC-normalised, stripped of control/bidi/zero-width characters and anything but letters, digits and a little
  punctuation, and cut to 40 characters; Android package names map to friendly names. Nothing is executed. The
  brain tool is in `UNTRUSTED_TOOLS`, so once it has run, memory writes and to-do changes need the owner's own words.
- **To-do panel** (`ui/src/screentime.ts`, a separate card mounted above the list): today's total vs the daily goal
  (meter + words), the last 7 days, top 3 apps, pickups, when it was updated; type today's total and top app; add a **goal
  to-do** ("Phone under 2h today", "30m or less on Instagram today", "Social apps under 3h today"; optionally
  every day).
- **App-group goals** (the owner's goal: about 3 h a day across TikTok, Instagram and YouTube together): one limit
  over a named set of apps, minutes added up. Names match case-insensitively and by alias (YT = YouTube, IG/Insta =
  Instagram, Tik Tok = TikTok, Android package names, and websites such as youtube.com / m.youtube.com count for
  their app). The card offers **"Social: TikTok, Instagram, YouTube ≤ 3h"** with today's combined minutes; one click
  (*Add daily goal*) makes it a daily goal to-do "Social apps under 3h today" with a progress meter; *No thanks*
  hides the offer. It is never created on its own. Custom groups: *Apps together at most* in the goal form.
- **Goal to-dos** are ordinary to-dos (list `phone`) plus a goal row. During the day, going over updates the to-do's
  note ("Over: 45m on Instagram (goal 30m)"). Once the day is over (the phone reported after midnight, or it's past
  10 AM the next day) a met goal **checks itself off**; a missed one stays open, flagged. No data for 3 days → noted.
  A repeating goal makes one to-do per day; deleting one (or *Stop repeating*) ends the series.
- **Gentle suggestion:** when today's total passes the goal (3 h without one) and an important to-do is open
  (overdue, due today or high priority, not a phone goal), the card shows "You've been on your phone 2h 30m today,
  and "Email the TA" is still open…" with *Help me start*. Once a day the app also emits a `screentime_nudge` event
  (a toast in the app) and calls `ScreenTime.on_nudge` hooks. **No OS or phone notification is sent**; the
  notifications feature can subscribe to that hook.
- **Brain:** `get_screen_time(day)` (today, yesterday, week, or a date), read-only. "How much was I on my phone
  today?" routes to the `health` task (rule in `router.py`).
- **Morning brief:** a *Phone* section with yesterday's total vs the goal and the top app (setting
  `screentime_in_brief`).

## 4. Open questions for the owner

Answered: iPhone on **iOS 27.2.1** (the Shortcuts Screen Time action should be there); the **automatic Shortcut**
(iCloud Drive) route, which is the default for iPhone; goal **about 3 h a day across TikTok, Instagram and YouTube**
(the suggested Social group above).

Still open: what *Get App & Website Data* returns in the Shortcuts editor (a list with durations? a total?). The
parser is lenient; if the action shows a total, add it to the Dictionary as `total`.

## Sources

1. Apple, "What's new in Shortcuts for iOS 26 …" — lists Screen Time • "Get App & Website Data":
   <https://support.apple.com/en-us/125148>
2. 9to5Mac, "iOS 26's Shortcuts app adds 25+ new actions" (2025-12-09):
   <https://9to5mac.com/2025/12/09/ios-26s-shortcuts-app-adds-25-new-actions-heres-everything-new/>
3. "Screen Usage" (personal write-up of a nightly Shortcut using the action): <https://plc.vc/n2a>
4. Apple Developer Forums, "DeviceActivityReportExtension sandbox blocks all output channels":
   <https://developer.apple.com/forums/thread/818297>
5. Apple Developer Forums, "Access Screen Time total usage from main app when using DeviceActivityReportExtension"
   (DTS: yes, sandboxed): <https://developer.apple.com/forums/thread/818174>
6. Apple Developer Forums, "Send device activity data to external server":
   <https://developer.apple.com/forums/thread/727958>
7. Apple Platform Security, Screen Time security (CloudKit end-to-end encryption):
   <https://support.apple.com/guide/security/secd8831e732/web>
8. Notes on accessing / exporting Apple's Screen Time data (knowledgeC.db, Biome, Timing):
   <https://gist.github.com/0xdevalias/38cfc92278f85ae89a46f0c156208fd5>
9. Mac Screen Time database → Home Assistant/InfluxDB exporter: <https://github.com/nichtlegacy/screentime>
10. Android `UsageStatsManager`: <https://developer.android.com/reference/android/app/usage/UsageStatsManager>
11. Tasker 5.8 changelog (App Info action): <https://tasker.joaoapps.com/changes/changes5.8.html>
12. r/AutomateUser report on the App usage block's daily total (Nov 2023; may be fixed since).
13. Microsoft, Phone Link FAQ: <https://support.microsoft.com/en-us/Windows/apps/phonelink/frequently-asked-questions-about-the-phone-link>
14. ntfy issue #69, "End-to-end encryption (E2E) between clients": <https://github.com/binwiederhier/ntfy/issues/69>;
    ntfy subscribe API (poll, since): <https://docs.ntfy.sh/subscribe/api/>

Several of these pages couldn't be opened from the build container (its network allows only some hosts); facts from
them come from search-result summaries and are marked "not verified here" where it matters.

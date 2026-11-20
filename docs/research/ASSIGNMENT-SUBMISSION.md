# Research: opening and submitting Canvas assignments

Status: research only, no code changed. Written 2026-11-20 against `main` at `71b4644` plus the working branch
`feature/flagship-m2-voice`.

The owner asked for two things:
1. Monkey opens the link to an assignment when the owner asks or clicks.
2. Monkey submits an assignment on his own when the owner hands him the finished file.

The examples below use synthetic course and assignment names. Real course names belong to the private context pack and
never go in this public repo.

**How the sources were checked.** This session could not reach `canvas.instructure.com`, `developerdocs.instructure.com`,
`community.canvaslms.com` or `kb.wisc.edu` directly (the network proxy refused them).
- **Canvas behaviour:** checked against the Canvas source on GitHub, commit `1c9f0bb` (the `master` head on 2026-11-20).
  The official API pages are generated from comments in that same source. Links to the official pages are included, but
  their wording was not re-read today.
- **UW–Madison pages:** known only from search-engine summaries. Anything not checked is marked **(unverified)**.

---

## 1. TL;DR

| # | Strategy | Use it for | Verdict |
|---|---|---|---|
| 1 | **Open the assignment.** Build the canonical `/courses/:cid/assignments/:aid` URL in code and open it in the owner's default browser. | Every row, by click or by voice | **Do first.** Small and read-only. Works with no token. |
| 2 | **API submit.** A Canvas REST upload and submit, after the owner confirms one card, then verified with a GET. | Plain `online_upload` assignments: no plagiarism tool, not a group assignment, not locked | **Recommended main path**, while the owner has a token |
| 3 | **Hand-off.** Monkey opens the assignment page in the owner's Chrome, shows the file in Explorer, and the owner submits. Monkey then verifies (API) or asks. | Everything else: Turnitin or other plagiarism pledges, external tools, group work, lockdown, no token | **Always available as the fallback** |
| 4 | **Browser attach.** Monkey attaches the file in the browser (Playwright), the owner ticks any pledge, and Submit needs approval. | Later, only through the owner's own Chrome tabs (Monkey for Chrome) | **Defer.** Fragile, and needs the `upload` action, which is still on an unmerged branch |

Integrity lines, unchanged from the computer-task design:
- Monkey never writes or alters the assignment content.
- Monkey never ticks a pledge or attestation.
- Monkey never answers quizzes.
- Monkey never submits without a fresh, per-submission confirmation from the owner.
- Sign-in, passwords and Duo stay the owner's.

---

## 2. What the repo does today

### 2.1 Where the assignment rows come from

`AssignmentBoard.load()` (`monkey/integrations/canvas_api.py`) uses the **API** when a token is set, otherwise the
**calendar feed**.

| Field | API path (`CanvasAPI.assignments`) | Feed path (`AssignmentBoard._from_feed`) |
|---|---|---|
| `url` | `a["html_url"]`. Canvas documents it as "the URL to the assignment's web page" [A1]. | `Event.web_link`, the ICS `URL:` property (`canvas_ics.parse_ics`) |
| `course_id` | set | **empty** |
| `assignment_id` | set | the number after the last `-` of the ICS `UID`, only if it starts with `event-assignment-` |
| submission state | from `include[]=submission` | none |

**What the ICS `URL` actually is.** In Canvas's ICS export (`CalendarEvent::IcalEvent#to_ics`, [C1] lines 848–860), the
URL points to the **calendar page**, not the assignment page:

```
https://<canvas host>/calendar?include_contexts=course_<cid>&month=MM&year=YYYY#assignment_<aid>
UID: event-assignment-<aid>
```

When the student has a due-date **override**, Canvas changes the event like this:
- the `UID` becomes `event-assignment-override-<override_id>`;
- the summary becomes `"<title> (<override title>)"`, which is where rows like `Final Outline (5 students)` come from;
- `URL` keeps `#assignment_<aid>`, because the source has `# TODO: event.url` there.
- The course code is then appended as `[<course_code>]`.

Consequences for the feed path:
- **Clicking a feed row today opens the Canvas calendar month view, not the assignment.** Whether the calendar then pops
  up that assignment from the `#assignment_<id>` fragment is **(unverified)**.
- **Latent bug:** for override events, `_from_feed` reads `assignment_id` from the UID, so it stores the **override id**
  instead of the assignment id. Any future feature that trusts `assignment_id` from the feed would act on the wrong
  object.
- **Fix:** take both ids from the URL instead: `include_contexts=course_(\d+)` and `#assignment_(\d+)`. Then build
  `https://<canvas_base_url host>/courses/<cid>/assignments/<aid>`. This is the same shape as the API's `html_url`.
- A row whose course reads like `FA26 SUBJ 100 001` comes from the feed path: `pretty_course` only reformats codes
  shaped like `SUBJ_100_001_F26`. A row with `(N students)` is an override event.

### 2.2 Clicking and opening

- `ui/src/assignments.ts` `row()` already wires a click on the **title text** (`.asg-title .t`, `cursor: pointer`) to
  `api.open_url(it.url)`.
- That call goes through `monkey/app.py` `_open_url` → `monkey/links.py` `launch_url` → `os.startfile`, which opens the
  link in the **owner's default browser**. That browser is already signed in to Canvas, so there is no Duo prompt.
- Gaps:
  - The title is a `<span>`, so it has no keyboard access and no role.
  - Nothing shows that the title is a link.
  - Rows with an empty `url` still look clickable.
- **Voice:** there is no tool for opening an assignment.
  - `get_assignments` returns `id`, `title` and `course` to the model, but not `url` (see the `keep` tuple in `tools.py`).
  - The model could only guess a URL for `open_website`.
  - `get_assignments` is in `UNTRUSTED_TOOLS` (memory taint) but **not** in `LINK_UNTRUSTED`. A URL it produced would
    open without the held-link check.

### 2.3 Automation and permissions (relevant parts)

- `monkey/automation/permissions.py` on `main`:
  - Risk levels go LOW < MEDIUM < HIGH < USER_ONLY < FORBIDDEN.
  - `Submit Assignment`, `Upload File` and `Choose a file to upload` all classify as **HIGH**, so they need a one-time
    approval.
  - Native `confirm()` dialogs are always dismissed (`browser.py` `_on_page`).
- **There is no file-upload action on `main`.** `Action.kind` has no `upload`, and `browser.py` never calls
  `set_input_files` or `expect_file_chooser`.
- The unmerged branch `feature/hybrid-computer-use` (`dec51d2`) adds the missing pieces:
  - `Action.kind in ("upload", "choose_file")`, classified **HIGH** ("this sends a file from your PC to the site");
  - `path_allowed(path, scope.files)`, so a file must be one the user put in the task, else FORBIDDEN;
  - a browser `_upload` that uses `set_input_files` or `expect_file_chooser`.
  - `docs/MONKEY-ARCHITECTURE-DECISIONS.md` already lists "upload and file-path scope" as a decision.
- **Gap found:** Canvas's default similarity pledge reads "This assignment submission is my own, original work"
  ([C5] `Account#closest_turnitin_pledge`). The current gate classifies that checkbox as **MEDIUM, "an unfamiliar
  control"**, not USER_ONLY. It matches neither `USER_ONLY_WORDS` nor the `(i |agree|confirm|consent)` checkbox rule.
  Checked with `classify(Action('click', Target(role='checkbox', name=...)))`.
  - A Monkey browser task could therefore tick it without asking, unless `confirm_medium` is on.
  - This must be fixed before any browser submission work: add `my own|original work|pledge|honou?r code|academic
    integrity|plagiarism|similarity` to `USER_ONLY_WORDS`.
  - The Turnitin EULA wording ("I agree to … End-User License Agreement") is already USER_ONLY.
- Email has `brain/approval.py` `ApprovalGate`:
  - the model can only draft;
  - sending needs a one-time UI token, or "send it" followed by a clean yes after Monkey reads the message back.
  - This is the pattern to copy for submissions.

### 2.4 Token reality at UW–Madison

- Since **2025-11-14**, UW–Madison students can't create Canvas access tokens themselves. They request one through
  Learn@UW's form (KB 156712); an admin creates it, and it is delivered through a 1Password secure note.
  [U1][U2][U3] (search summaries; the pages themselves were not fetched)
- **Token lifetime:** UW's KB says request-form tokens expire "within a maximum of 120 days" [U1]. Instructure's
  platform caps student-only tokens at 120 days [I1].
  - **Mismatch in the repo:** `monkey/routines/canvas_token.py` says "max ~30 days". The docstring should say "up to 120
    days, as requested on the form". **(unverified for UW's current form)**
- **Scopes:** Canvas user tokens "inherit all permissions of the user account" [I3]. That means a token can submit
  homework, not just read it. That is exactly why it has to be guarded.
  - Whether UW's admin-issued student tokens are scoped narrower is **(unverified)**. Ask the owner what the issued
    token allows.
- **Platform churn:**
  - After an incident on 2026-04-29, Instructure **expired existing personal tokens** and added controls (Ohio State
    reports a 90-day maximum for instructors) [I4].
  - One university page says Instructure will retire token-based API access in the first half of 2027 [I3]. **No
    Instructure source confirms this (unverified).**
  - Canvas has also been rolling out **rejection of API requests without a `User-Agent`** [I2]. `httpx` sends one by
    default. Monkey should send an explicit, generic `Monkey/<version>` value.
- **Consequence:** the token can disappear at any time. The hand-off path (strategy 3) must stay first-class, not an
  afterthought.

---

## 3. Opening assignment links

### 3.1 Getting the right URL

| Source | Use |
|---|---|
| API `html_url` | Use as is. Check that its host equals the host of `settings.canvas_base_url`. |
| ICS `URL` | Parse `course_<cid>` and `#assignment_<aid>`, then build `/courses/<cid>/assignments/<aid>` on the configured Canvas host. Fall back to the raw calendar URL only if parsing fails. |
| Non-assignment calendar events | `_from_feed` currently lists *every* feed event, including `event-calendar-event-*` items, as an "assignment". Those have no assignment page. Keep their calendar URL, or filter them out (separate cleanup). |

**Rule: the model never supplies the URL.** It passes an item id or a spoken query. Code looks the row up and builds the
link, and opens it only if the host is the Canvas host.
- Instructor-written titles can carry prompt-injection text.
- With this rule, the worst such text can do is open another Canvas page.

### 3.2 Matching "open my COM ARTS outline assignment"

Do this deterministically in code. It costs no tokens and returns a ranked list. The model only helps when the owner
answers an ambiguous result.

1. **Normalize.**
   - Lowercase the text and strip punctuation and filler words ("my", "assignment", "the", "open").
   - Expand course aliases: `com arts → comarts`, `comp sci`/`cs → comp sci`, `psych`, `econ`, and so on, with a small
     table plus the course codes on the board.
   - Strip the `(N students)` / `(Section …)` override suffix from titles.
2. **Score each row.**
   - Course: if a course alias is present, it **filters**.
   - Title: token-set overlap plus `difflib.SequenceMatcher` ratio. `difflib` is in the standard library and already
     used in `monkey/audio/echo.py`.
   - Boost to-do over done, and the nearest due date (overdue counts as nearest).
3. **Decide.**
   - Top score ≥ threshold and clearly ahead of the second (for example a margin of ≥ 0.15): open it, and say
     "Opening *Final Outline* for SUBJ 100."
   - Otherwise show a small "Which one?" card listing up to 4 clickable rows, and say "I found two outlines: …".
   - When the owner says "the first one" or "the speech one", the model calls the tool with the `item_id`.
   - No match at all: say so and offer the Canvas course page. Never open a guess.
4. **Tool shape:** `open_assignment(query: str, item_id: str)`, strict schema, with one of the two empty. `item_id`
   wins. The result returns the matched title and course, so Monkey can say what he opened.

### 3.3 Which browser

| Option | Pros | Cons | Use |
|---|---|---|---|
| Owner's default browser (`launch_url`, current behaviour) | Already signed in, no Duo. Exactly what the owner would do by hand. | Monkey can't see the page | **Default for "open"** |
| Owner's Chrome through Monkey for Chrome (`chrome_bridge.py`) | Real session, and Monkey can read the page (pledge check, verification) | Needs the extension paired and the tab shared | Pre-submit page check (§4.6), hand-off |
| Monkey's managed browser (Playwright, own profile) | Fully gated, works without the extension | Separate profile, so NetID + Duo sign-in the first time | Long computer tasks only |

Opening a page is a read-only GET in the owner's own browser. It is not outward-facing, so it needs no confirmation,
the same as `open_website` for a site the owner named.

### 3.4 UI

- Render the title as a `<button class="link">` or an `<a>` with an `↗`, `title="Open in Canvas"` and `aria-label`.
  Make the whole row keyboard-reachable.
- Hide the affordance when `url` is empty.
- Feed rows open the canonical assignment page once §3.1 lands.
- Later, a row menu can offer "Submit a file…", which starts the §4 flow with this row preselected.

---

## 4. Submitting a file

### 4.1 Canvas REST: the exact sequence

All of this was checked in the Canvas source [C2][C3][C4]. The official pages are [A1] (Assignments), [A2]
(Submissions) and [A3] (File uploads).

| Step | Request | Notes |
|---|---|---|
| 0. Preflight | `GET /api/v1/courses/:cid/assignments/:aid?include[]=submission&include[]=can_submit` | `can_submit` "checks enrollment dates, submission types, locked status, attempts remaining". Single-assignment GET only. It is implemented in the code but missing from the `include[]` list in the docs ([A1]; [C3] `lib/api/v1/assignment.rb` 518–523). |
| 1. Announce the upload | `POST /api/v1/courses/:cid/assignments/:aid/submissions/self/files` with `name`, `size`, `content_type`, `on_duplicate=rename`, **`submit_assignment=false`** | Rejected if `allowed_extensions` is set and the extension isn't in it ("filetype not allowed") [C2] `create_file`. Returns `upload_url` and `upload_params`. The signature is valid for **30 minutes** [A3]. |
| 2. Upload | `POST <upload_url>` as multipart. Send **all** `upload_params` unchanged, with `file` **last**. | "The access token is not sent with this request" [A3]. The upload host can be S3 or InstFS. |
| 3. Confirm | 3xx: `GET Location` **with** the token. 201: the file JSON is at `Location`. | Without step 3 "the file may not appear" [A3]. |
| 4. Submit | `POST /api/v1/courses/:cid/assignments/:aid/submissions` with `submission[submission_type]=online_upload` and `submission[file_ids][]=<id>` | The type must be in the assignment's `submission_types`, else 400 "Invalid submission[submission_type] given" [C4] `process_api_submission_params`. With no usable file you get "No valid file ids given". |
| 5. Verify | `GET /api/v1/courses/:cid/assignments/:aid/submissions/self?include[]=submission_history` | §4.5 |

Details that matter for safety:
- **`submit_assignment` defaults to `true`** on the upload endpoint ([C2] line 704). Today it only auto-submits for the
  *upload-by-URL* flavour ([C6] `lib/api/v1/attachment.rb` ~385–430, `files_controller.rb` ~1194–1197). Monkey uploads
  bytes, never a URL, and sends `submit_assignment=false` anyway. That keeps "upload" and "submit" separate even if
  Canvas changes.
- **Don't send the token to the upload host.** Use a separate HTTP client with no `Authorization` header for step 2.
  In step 3, attach the token only if the `Location` host equals the Canvas host.
- **The API skips `allowed_extensions` on the final submit.** That check sits inside `unless api_request?` ([C4]
  `create`, around lines 275–280). The upload endpoint checks it, but Monkey must check it too.
- **Locked assignments answer the API with a redirect, not JSON.** `create` sets a flash and `redirect_to`s ([C4] around
  lines 260–264). Treat **any non-201 response on step 4 as a failure**, never as "probably fine".
- **Group assignments submit for the whole group.** `submit_homework` → `group_students(original_student)` ([C7]
  `abstract_assignment.rb` around 2768). That is outward-facing to teammates.
- **Attempts:** `allowed_attempts` (−1 means unlimited) applies to `online_upload`, `online_url` and
  `online_text_entry`. Past the limit, Canvas refuses with "you have reached the maximum number of allowed attempts"
  ([C8] `submission.rb` 63, 1964–1976).
- **Students can't undo a submission.** A resubmission is a new attempt. This is Canvas UI behaviour as commonly
  documented; no student delete endpoint was found in the source read here **(unverified as a doc statement)**.
- **The API does not enforce the plagiarism pledge.** The web UI shows `SIMILARITY_PLEDGE` and blocks Submit until it's
  ticked, but only in the browser ([C9] `SubmissionManager.jsx` 533–538). The server shows the pledge when the
  assignment has `turnitin_enabled`, `vericite_enabled` **or a `tool_settings_tool`** ([C10]
  `assignments_controller.rb` 241–249, 1296–1302). The API's assignment JSON only includes the first two, and only when
  the account has that plugin ([C3] 209–216). An LTI-based plagiarism tool is **invisible to a student's API call**.
  - An API submit could therefore skip a pledge the owner would have had to tick in the UI.
  - This is the main integrity risk of the API path; §4.6 handles it.
  - `eula_agreement_timestamp` (the Turnitin EULA) is an attestation. **Monkey never sends it.**

### 4.2 Which assignments the API path can't (or shouldn't) do

The checks run on the preflight object. All field meanings are from [A1].

| Condition (field) | API can? | Route |
|---|---|---|
| `submission_types` lacks `online_upload` | — | Not a file assignment. Hand-off, or say what kind it is. |
| `online_quiz`, `is_quiz_assignment`, `require_lockdown_browser` | no / never | **USER_ONLY.** Monkey only opens the page. |
| `external_tool` (Turnitin LTI 1.3, Gradescope, publisher tools) | no (`basic_lti_launch` needs a resource link the tool creates) | Hand-off. The tool's iframe is cross-origin. |
| `discussion_topic` | not via this API, and it is writing | Hand-off. Monkey doesn't post. |
| `media_recording`, `student_annotation` | "no API yet for creating a media comment"; annotation is done in the UI ([C4] 167, 223–227) | Hand-off |
| `online_text_entry` / `online_url` | yes | **Not in v1.** Text would have to come verbatim from a file the owner provided. A URL needs the owner to dictate it. Add later with the same card. |
| `turnitin_enabled` or `vericite_enabled` true | yes, but it skips the pledge | **Hand-off.** The owner ticks the pledge. |
| `group_category_id` set | yes, for the whole group | Hand-off by default, or an extra explicit "submits for your group" confirmation (owner's choice). |
| `locked_for_user` true | no | Read `lock_explanation` aloud. Nothing to do. |
| `can_submit` false | no | Say why (attempts used up, enrollment ended). |
| `allowed_extensions` set and the file's extension isn't in it | no | Say which extensions are allowed. **Never convert the file.** |
| Already submitted (`submission.workflow_state` submitted/graded, `attempt ≥ 1`) | yes, as a new attempt | Extra line on the card: "Resubmission: attempt N+1 of M". |
| Past `due_at` | yes, marked late | Extra line on the card: "This will be marked late". |
| `peer_reviews` | — | Peer reviews are the owner's own assessments of others: **USER_ONLY**, never done by Monkey. |

### 4.3 The token question

- With a token, strategy 2 is deterministic, needs no Duo, and is fully verifiable.
- Without a token (the default for UW students since 2025-11), only strategies 3 and 4 exist.
- Recommendation: support both, and ship **opening (strategy 1) and the hand-off (strategy 3) first**. They need no
  token and no new outward-facing capability.
- Monkey already stores the token with DPAPI (`keys.py` `canvas_token`) and tracks its expiry (`canvas_token.py`).
  Nothing new is needed for storage.
- Monkey must never ask for the token in chat. It stays in Settings.

### 4.4 Browser fallback (strategy 4, deferred)

What it would take with the existing Playwright stack:
- **File chooser:** merge `upload` from `feature/hybrid-computer-use`:
  - `set_input_files` for a real `<input type=file>`, else `expect_file_chooser` + `set_files`, so no native dialog
    appears;
  - Playwright API [P1].
  - The task scope carries `files=[<the one file>]`, so `path_allowed` refuses anything else.
- **Canvas's student assignment page** (React, Canvas source [C9]):
  - "Choose a file to upload" (`FileDrop`, `id=inputFileDrop`);
  - upload happens on selection into a **draft**, not a submission;
  - an optional pledge checkbox;
  - **"Submit Assignment"** (`data-testid="submit-button"`);
  - "New Attempt" for resubmission.
- **Gate mapping:**
  - Attach file: HIGH, approved through the same card.
  - Pledge: **USER_ONLY** after the §2.3 fix. The owner ticks it in the page.
  - Submit Assignment: HIGH, one-time approval.
  - Native `confirm()`: dismissed (existing behaviour). So any Canvas "are you sure" dialog cancels, and the owner
    finishes by hand.
- **LTI/Turnitin iframes:** cross-origin. Monkey's snapshot can read into frames, but the upload widgets differ per
  tool. **Hand off; don't automate.**
- **Where to run:** in the owner's Chrome through Monkey for Chrome, so their session is used with no extra sign-in.
  In the managed profile, NetID + Duo stay the owner's.
- **Why deferred:** the page markup changes without notice, the upload action isn't on `main`, and the API path plus
  the hand-off cover the same ground with less risk.

### 4.5 Verifying, and reporting only verified results

After step 4, fetch `GET …/submissions/self?include[]=submission_history` and require **all** of these:
- `workflow_state ∈ {submitted, pending_review, graded}`;
- `submitted_at` ≥ the time the submit started;
- `attempt == attempt_before + 1`;
- `submission_type == "online_upload"`;
- `attachments[]` contains the uploaded file id, with `size` equal to the local size and the expected `display_name`.

Field meanings are in [A2]. Optionally (owner's choice), download the attachment's `url` and compare its **SHA-256**
with the local hash taken at confirmation. This is the strongest proof that the exact bytes landed.

Report only what was checked. For example: "Verified on Canvas: *Final Outline* (SUBJ 100) submitted at 9:41 PM,
attempt 2 of 3, `outline-final.pdf` (212 KB). Canvas marks it late."
- If any check fails, say "Canvas answered but I couldn't confirm the submission", open the assignment page, and keep
  the record as `unverified`.
- Never say "submitted" on a 2xx alone.
- After a verified submit, refresh the board: the row moves to Done with "submitted", from Canvas's own state, not a
  local check.

### 4.6 The plagiarism-pledge problem

Because the API can't see LTI plagiarism tools (§4.1), a page check is needed before an API submit. Options, safest
first:
1. **Check the page, read-only, before submitting.** If Monkey for Chrome is paired, open the assignment in a shared
   tab and look for the pledge checkbox or the `SIMILARITY_PLEDGE` text.
   - Pledge present: hand off.
   - No extension: go to option 2 or 3.
2. **Owner-declared.** The card shows: "If this assignment shows a 'my own, original work' pledge on Canvas, submit it
   yourself. [Open assignment]". The API path stays available only when `turnitin_enabled`/`vericite_enabled` are
   absent or false.
   - Residual risk: an LTI-only plagiarism tool. The owner still confirmed the exact file and assignment.
3. **Hand off always** whenever the course is known to use Turnitin or similar. A per-course toggle "I submit this
   class myself" lives in Settings.

**Recommendation:** use 1 when the extension is paired, else 2. The owner can switch any course to 3 (an open
question).

---

## 5. Safety and integrity design

### 5.1 Principles, enforced in code

| Rule | How |
|---|---|
| Ask before every outward action (CLAUDE.md) | The model gets only **`prepare_submission`**. There is **no submit tool**. Submission runs in app code after the owner confirms, like email `ApprovalGate`. One confirmation submits one file to one assignment. No standing grants, no "submit all", no scheduled or automatic submits. |
| The owner sees exactly what goes where | The card shows the course; the assignment title, with a link to it; the due or lock time; late or not; attempt N+1 of M; the submission type; allowed extensions; the file name, full path, size, modified time, SHA-256 (short) and a first-page preview (PDF, image, or plain text); and a "group" warning when it applies. |
| Confirmation can't be forged | The UI gets a one-time token the model never sees, as in `PendingDraft` and `PermissionGate` approvals. Voice works the email way: Monkey reads back "Submit *outline-final.pdf* to *Final Outline* in SUBJ 100, attempt 2 of 3?" and only a clean yes within 60 s counts (reuse `_CONFIRM`/`_HEDGE`). The owner may require a **click only** (open question). |
| The file is the owner's, unaltered | The file comes from an **owner action**: the native picker (`create_file_dialog`, already used in `app.py`), or dropping it on the card (pywebview drop paths, **unverified**), or a model-suggested path that the card shows and the owner confirms. Monkey opens it read-only and hashes it at prepare time and again right before upload; **a changed hash means abort and confirm again**. No conversion, rename, compression, or "fixing". |
| Monkey never authors the content | Refuse paths Monkey wrote. Keep a ledger of files Monkey created (generated images, exports), plus `%APPDATA%\Monkey`, `%LOCALAPPDATA%\Monkey`, temp folders and Office lock files `~$*`. Refuse empty files. `online_text_entry` is not built until text comes verbatim from an owner file. Optional submission comments are verbatim dictation only. The file's content is **not** sent to Claude by default. Monkey checks *which* file, not *how good* it is. |
| Attestations stay the owner's | Never send `eula_agreement_timestamp`. Never tick pledges. Fix `USER_ONLY_WORDS` (§2.3). Quizzes, peer reviews and lockdown stay USER_ONLY. |
| No double submits | Write-ahead record in `monkey.db` (`prepared → uploading → uploaded → submitting → submitted|failed → verified|unverified`). On a crash or timeout after step 4 was sent, **GET the submission before any retry**. Never retry step 4 blind, because it would burn an attempt. |
| Data hygiene | Never log the token, file contents or the upload params. Log the assignment id, file name, size and hash prefix (`logsafe`). Nothing goes in the repo, CI or releases. |

### 5.2 How it fits the existing gates

- **API path:** a new `SubmissionGate` beside `ApprovalGate`, or `ApprovalGate` generalized to a typed
  `PendingOutward` with `email` and `submission` kinds.
  - Its risk is **HIGH** in the `Risk` vocabulary: it sends, submits, and is hard to undo.
  - The `PermissionGate` doesn't apply because no page is driven, but the same rules hold: one-time token, one action,
    expiry.
- **Browser path:**
  - `PermissionGate` as it is, plus `upload` (HIGH, with `path_allowed`) from the hybrid branch;
  - plus the pledge words in USER_ONLY;
  - the task's `files` scope holds just the confirmed file;
  - `allowed_domains` holds the Canvas host and the school sign-in hosts.
- **Hand-off path:** only `launch_url`, plus showing the file in Explorer (`explorer /select,<path>`, standard Windows
  behaviour, **not tested here**). Afterwards Monkey verifies through the API if there is a token, otherwise asks "Did it
  go through?" and does **not** mark it done by itself.

---

## 6. Recommendation

### 6.1 Ranking

1. **Open links (strategy 1).** Ship now. It needs no token and no outward action, and it fixes the feed URL and the
   override-id bug.
2. **Hand-off submit (strategy 3).** "Here's the page and your file; submit it, and I'll check." This is the fallback
   for everything, and the only route without a token.
3. **API submit (strategy 2).** Only for eligible `online_upload` assignments (§4.2), with the confirmation card, the
   pledge check (§4.6) and verification (§4.5). Off by default behind Settings → Accounts → Canvas → "Let Monkey submit
   files I give him".
4. **Browser attach (strategy 4).** Later, through Monkey for Chrome only, after the `upload` action is merged and the
   pledge words are fixed.

### 6.2 Minimal first vertical slice

**Slice A, "open it"** (one PR, no outward action):
- `monkey/integrations/canvas_api.py`:
  - add `canonical_assignment_url(url, base)`, which parses `include_contexts=course_N` and `#assignment_N`;
  - `_from_feed` fills `course_id`, `assignment_id` (from the URL, not the UID) and the canonical `url`;
  - check `html_url`'s host.
- `monkey/brain/assignments.py`: `match(items, query) -> list[(Assignment, score)]` with the course alias table.
- `monkey/brain/tools.py`:
  - add `open_assignment(query, item_id)` (strict). The URL is built from the board, and only the Canvas host is
    allowed.
  - add `url` to nothing the model sees.
- `ui/src/assignments.ts` and `style.css`: title as an accessible link with `↗`, plus a "Which one?" card (reuse the
  panel or the assignments card).
- `monkey/brain/router.py`: make sure "open … assignment" routes to the tool set that includes it (all tools are sent
  today, so this is likely just a benchmark case).
- Tests:
  - ICS fixtures (plain event, override event `event-assignment-override-*` with `(5 students)`, calendar event);
  - matcher tests (course alias filter, ambiguity margin → candidates, done items ranked lower);
  - tool tests (off-host `html_url` refused; empty query; no board);
  - a Playwright check through `?demo` with `window.__monkeyEvents` (the row opens through `open_url`).

**Slice B, "submit with confirmation, API"** (behind the setting):
- New `monkey/integrations/canvas_submit.py`: `preflight()`, `upload()` (steps 1–3, auth-split clients), `submit()`,
  `verify()` and an `eligibility()` table (§4.2).
- New `monkey/brain/submission.py`: `PendingSubmission`, `SubmissionGate` (token, voice read-back, write-ahead states).
  Or generalize `brain/approval.py`.
- `monkey/brain/tools.py`: `prepare_submission(item_id, file_hint)`. It only opens the card, and the file is picked or
  confirmed by the owner.
- `monkey/app.py` bridge: `pick_submission_file`, `approve_submission(id, token)`, `cancel_submission(id)`; emit
  `submission` and `submission_result` events.
- `ui/src/submission.ts` (new card) and `ui/src/bridge.ts` (API surface plus demo stubs).
- `monkey/routines/canvas_token.py`: fix the "~30 days" text.
- `monkey/automation/permissions.py`: pledge words in `USER_ONLY_WORDS`. This can ship in slice A, since it protects
  computer tasks today.
- Hand-off (strategy 3) is part of slice B: it is just the "Submit it yourself" button on the same card.

### 6.3 Tests and fixtures

- **Existing fixtures to build on:**
  - `tests/test_canvas_garmin.py` `canvas_handler` (`httpx.MockTransport` fake Canvas API);
  - the synthetic course server `monkey/automation/democourse.py` (`DemoCourse`, `ThreadingHTTPServer` on 127.0.0.1,
    variants including `canvas`), driven by `tests/test_automation_e2e.py` through `tools/automation_eval.py`.
- **New `FakeCanvas`** (a `MockTransport` handler, or a small threaded server for real multipart):
  - assignments with every §4.2 shape;
  - `/submissions/self/files` returns an `upload_url` on a **different host**;
  - the upload endpoint asserts **no `Authorization` header** and checks that `file` is the last part;
  - 3xx → `create_success` requires auth;
  - submit enforces attempts and types;
  - locked returns a 302 to HTML;
  - `submission_history` records attempts.
- **API slice cases:**
  - happy path, verified;
  - extension not allowed (no upload);
  - locked (302 handled as a failure);
  - attempts exhausted;
  - group → hand-off;
  - `turnitin_enabled` → hand-off;
  - `external_tool`/quiz → refused;
  - token leak check on the upload host;
  - file changed after confirm → abort;
  - path under the Monkey data dir or a `~$` lock file → refused;
  - a timeout after submit → GET first, no second attempt;
  - verify mismatch → reported `unverified`, never "submitted";
  - the model calling tools with no token can't submit (no submit tool exists; approve with a wrong or reused token
    fails);
  - voice: "yes but change the file" doesn't submit.
- **Browser slice (later):** a `DemoCourse` variant `canvas_submit` with a Canvas-like assignment page (file drop, pledge
  checkbox with the default pledge text, Submit Assignment, a `confirm()` dialog). The server checks the pledge was
  ticked by the "user" (the harness), not by Monkey, matching how the demo course already proves question answers come
  from the user.
- **Private data:** fixtures use synthetic courses only (`SUBJ 100`). Never real course names or files.
  `tests/test_private_guard.py` keeps guarding this.

### 6.4 Open questions for the owner

1. **Token:** do you have a UW Canvas token now, or will you request one (KB 156712)? What expiry did you choose? What
   use did the form ask you to state? Without one, Monkey can only open pages and hand off.
2. **Confirmation style:** click "Submit to Canvas" on the card only, or also allow a spoken "yes" after Monkey reads
   back the file and assignment?
3. **Pledge courses:** for classes using Turnitin or a similar tool, should Monkey always hand off (recommended), or use
   the page check through Monkey for Chrome?
4. **Group assignments:** always hand off, or allow with an extra "this submits for your whole group" confirmation?
5. **Resubmissions and late work:** allowed with a warning, or hand off?
6. **Giving the file:** native file picker, dragging onto Monkey, or "the newest PDF in Downloads named …" (Monkey shows
   it, you confirm)?
7. **Verification depth:** may Monkey download the submitted file back once to compare its hash?
8. **Opening:** is your Windows default browser the Chrome profile that's signed in to Canvas? If not, should "open"
   use the Monkey for Chrome tab instead?
9. **Courses to exclude:** any classes you always want to submit yourself?

---

## 7. Sources

Canvas (official API pages; generated from the source below, which was the version read for this note):
- [A1] Assignments API: https://canvas.instructure.com/doc/api/assignments.html
- [A2] Submissions API: https://canvas.instructure.com/doc/api/submissions.html (the UW copy is at
  https://canvas.wisc.edu/doc/api/submissions.html)
- [A3] File uploads: https://canvas.instructure.com/doc/api/file.file_uploads.html, source
  https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/doc/api/file_uploads.md

Canvas source, commit `1c9f0bb8013ed69c4f2efe11fd483025469b7e6c`, under
`https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/`:
- [C1] `app/models/calendar_event.rb`: `IcalEvent#to_ics` (URL, UID, override UID/summary)
- [C2] `app/controllers/submissions_api_controller.rb`: `create_file` (Upload a file; `allowed_extensions`;
  `submit_assignment` default)
- [C3] `lib/api/v1/assignment.rb` (`can_submit`, `turnitin_enabled`/`vericite_enabled` exposure) and
  `app/controllers/assignments_api_controller.rb` (Assignment object field docs)
- [C4] `app/controllers/submissions_controller.rb`: `create` (Submit an assignment; API vs web checks; locked redirect)
- [C5] `app/models/account.rb`: `closest_turnitin_pledge` (default pledge text)
- [C6] `lib/api/v1/attachment.rb` `api_attachment_preflight`; `app/controllers/files_controller.rb` `api_capture`
- [C7] `app/models/abstract_assignment.rb`: `submit_homework` (group submission)
- [C8] `app/models/submission.rb`: `SUBMISSION_TYPES_GOVERNED_BY_ALLOWED_ATTEMPTS`, `attempts_left`, the attempts error
- [C9] `ui/features/assignments_show_student/react/components/SubmissionManager.jsx` (pledge enforcement, "Submit
  Assignment") and `AttemptType/FileUpload.jsx` ("Choose a file to upload")
- [C10] `app/controllers/assignments_controller.rb`: `SIMILARITY_PLEDGE` env, `pledge_text`

UW–Madison (from search-engine summaries; not fetched directly):
- [U1] Canvas – Student Request for Canvas Access Token: https://kb.wisc.edu/156712
- [U2] Change to Student Access Tokens in Canvas:
  https://it.wisc.edu/academic-technology/learn-uw-news/change-to-student-access-tokens-in-canvas/
- [U3] Learn@UW Request Forms: https://kb.wisc.edu/luwmad/93459
- Turnitin with Canvas at UW–Madison: https://kb.wisc.edu/wiscel/page.php?id=93801

Instructure and other institutions (from search summaries):
- [I1] Strengthening Security in Canvas: Updates to User Access Token Management:
  https://community.canvaslms.com/t5/The-Product-Blog/Strengthening-Security-in-Canvas-Updates-to-User-Access-Token/ba-p/660299
- [I2] Enforcing User-Agent Header for Canvas API Requests:
  https://community.canvaslms.com/t5/Canvas-LMS-Blog/Enforcing-User-Agent-Header-for-Canvas-API-Requests/ba-p/658205
- [I3] University of Missouri System, Canvas user API token policy (inherits all user permissions; the 2027 retirement
  claim is **unverified**): https://tdx.umsystem.edu/TDClient/66/MOOnline/KB/ArticleDet?ID=2193
- [I4] Ohio State, CarmenCanvas personal access tokens (tokens expired after the 2026-04-29 incident; 90-day maximum):
  https://it.osu.edu/news/2026/08/11/carmencanvas-personal-access-tokens

Playwright:
- [P1] FileChooser: https://playwright.dev/python/docs/api/class-filechooser (`set_input_files`, `expect_file_chooser`)

Repo code referenced: `monkey/integrations/canvas_api.py`, `monkey/integrations/canvas_ics.py`,
`monkey/brain/tools.py`, `monkey/brain/approval.py`, `monkey/brain/assignments.py`, `monkey/brain/router.py`,
`monkey/automation/permissions.py`, `monkey/automation/browser.py`, `monkey/automation/chrome_bridge.py`,
`monkey/automation/democourse.py`, `monkey/links.py`, `monkey/routines/canvas_token.py`, `ui/src/assignments.ts`,
`tests/test_canvas_garmin.py`, `tests/test_automation_e2e.py`; branch `feature/hybrid-computer-use`
(`monkey/automation/permissions.py`, `monkey/automation/computer/drivers/browser.py`).

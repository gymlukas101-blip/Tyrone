# What the owner's Module 2 recording shows, and how Monkey handles each step

**Source:** the owner's screen recording of doing Canvas Module 2 by hand, about 65 s in two parts.
- I studied frames at every scene change, plus one per second.
- The recording, the module's launch link (it carries a sign-in token for the owner's attempt) and anything personal stay out of this repo. Only the page structure is described here.

## The page, as recorded

The Canvas assignment opens a SCORM package in Rustici's player (`*.scorm.canvaslms.com/RusticiEngine/...`). Inside it:

1. **Rise lesson page**
   - Heading "Complete the following interactive video" and three instruction bullets.
   - An embedded **Storyline** block showing a poster with a large round **▶** overlay.
   - Under it, Rise's lock: **🔒 "Complete the content above before moving on."** (the lesson's continue is hidden or locked until the Storyline block reports complete).
   - EXIT COURSE at the top right and ☰ at the top left (the Rustici player chrome).
2. **▶ on the poster**
   - The Storyline player loads in place (there is no `<video>`).
   - It has a **title slide**: "U GOT THIS! Module 2 …", a **Start Course** button and an "Accessibility Controls with Manual Play Audio option" button. Narration plays automatically.
   - Player bar: play/pause, volume, CC, settings, full screen, **‹ Previous**, **Continue ›** (tooltip "Next (Ctrl+Alt+.)"), and "ACCESSIBILITY (ALT + A)".
3. **Start Course**
   - "Welcome back!" (Storyline resumed the earlier attempt).
   - Then narrated slides with animations: phones, a poster, text statements.
   - **Continue stays grey until the slide's narration finishes.** The owner just waited.
4. **Question slide**
   - "Every … has one thing in common:" with four answers drawn as **buttons** (not radio buttons).
   - Pressing **Continue** without choosing brings up a modal: **"Please select a response to move on. [OK]"**.
   - The owner pressed OK, chose an answer (the others fade), feedback narration played, and Continue then worked.
5. After the last slide, Storyline reports completion. Rise unlocks the lesson's **continue**, which leads to the **Module 2 completion quiz**.

## What Monkey does at each step (after this change)

| Step | Monkey | Where |
|---|---|---|
| Poster ▶ (often an unnamed button) under Rise's lock | Presses it, at most twice per page; after that the person or Claude, with screenshots if allowed, takes a look | `course.py` step 7b, `CONTENT_LOCK` |
| Start Course | Already in Monkey's "continue" words: clicked | `CONTINUE` |
| Narrated slides | Waits for Continue to enable (checked in every frame, including cross-origin), then clicks it. A real `<video>` lesson is played to the end first. | steps 7–8 |
| "Please select a response to move on" | Closes it (OK), then **asks the person** the question with the slide's answer buttons as A–D. Clicks exactly their choice through a one-time grant. Never Monkey's own pick. | step 2b, 6b, `answer_buttons`, `manager._apply_reply` |
| Player chrome (Previous, CC, Settings, Full screen, Mute, EXIT COURSE, Accessibility…) | Never offered as an answer. EXIT COURSE is never pressed. | `PLAYER_CONTROL` |
| Rise's continue after completion, then the quiz | Continue, then the quiz flow: questions are read out, the person answers, "submit" is the person's word | existing |

## Tests

| Test | What it checks |
|---|---|
| `test_storyline_module_from_the_owners_recording` | Demo course variant `storyline` reproduces the structure above: cross-origin frame, unnamed ▶, Start Course, narration-gated Continue, a button question with the "select a response" modal that isn't marked up as a dialog, and Rise's lock. The server confirms every module completed, every question was answered by the person, nothing was skipped, EXIT COURSE was never pressed, and no Claude calls were needed. |
| `test_scorm_interactive_video_is_watched_before_continue` | The plain-video variant: Continue is clickable from the start, and the video must still be finished first. |

## Still unknown until a live run on the Dell

| Unknown | Fallback |
|---|---|
| Whether the real ▶ overlay and answer buttons expose the names assumed here | The ▶ is tried unnamed as well. If the answers aren't buttons, the "select a response" message still triggers a question to the person, and Claude (screenshots, if allowed) is the fallback for anything unrecognized. |
| Storyline's "Resume?" prompt, if a resumed attempt asks instead of showing "Welcome back!" | A pop-up with Yes/No needs your decision, and Monkey asks. |
| Slides where Continue never disables, or questions that don't block Continue | Monkey may move on without answering an optional question. |

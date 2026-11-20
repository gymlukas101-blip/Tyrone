# Monkey optimization roadmap

Dependency-ordered. Each item has a definition of done (DoD). The progress record is at the bottom.

## Milestone 1: reliability and safety foundations (merged to `main`, 2026-11-20)

- **Branch:** `feature/flagship-m1-reliability`, squash-merged after an independent review; all review blockers and follow-ups (N1–N8) fixed before the merge.
- **Items:** backlog 1–9 in [the audit](MONKEY-OPTIMIZATION-AUDIT.md).
- **Tests:** `tests/test_m1_fixes.py` (23), key-press tests in `tests/test_automation_core.py`, and `tests/test_lifecycle.py` (6).
- **Results (container):** full suite 469 passed, 4 skipped; end-to-end course 6/6.
- **Not yet checked on the Dell:** audio reopen after sleep or a headset change; the update restart.

## Milestone 2: voice reliability and measurement (built on `feature/flagship-m2-voice`)

Measure first, so later milestones can show they helped.

1. **Speaker races (D4–D6).**
   - **Change:** generation-stamped `say()`, an atomic speaking-state check, `STALL_S` above the longest engine deadline, and closing TTS generators on stop.
   - **DoD:**
     - unit tests interleave `say`, `stop` and the audio callback with no stuck "speaking" state;
     - the next reply after an interrupt starts in under 1 s with a fake Pocket engine.
2. **Echo guard and keyword barge-in.**
   - **Change:** reopen the mic after output latency plus a margin; reject transcripts that fuzzy-match his last sentences; "Monkey, stop" works while he speaks.
   - **DoD:** a test that feeds his own sentence back is rejected; a sherpa keyword test passes.
3. **Turn-latency instrumentation.**
   - **Change:** time end of speech → STT → first token → first audio, and show p50/p90 in Check everything.
   - **DoD:** values appear on the Dell, and the baseline is recorded in `MONKEY-EVALUATION-BASELINE.md`.
4. **Local traces and routing evals.**
   - **Change:** a redacted per-turn trace (route reason, model, effort, rounds, cost, latency, correction signals), a `bench_routing --from-traces` mode, and an importance regex that only fires on phrases like "this is important".
   - **DoD:** a live classifier accuracy number exists; misroutes are listed per task.

## Milestone 3: release trust (built on `feature/flagship-m2-voice`)

5. **Supply chain and licensing.** Every push to `main` ships to the owner's PC, so this comes before feature work.
   - **Change:** hashed lockfiles (`requirements/*.lock`, `tools/lock.sh`), SHA-pinned actions, an informational vulnerability audit job, third-party notices (`THIRD_PARTY_NOTICES.md` plus a generated `THIRD_PARTY_LICENSES.txt`).
   - **DoD:** CI fails on lockfile drift (`tools/check_lock.py`); notices ship in the installer.
   - **Left for the owner:** a LICENSE for Monkey's own code (your choice of terms), and whether to turn on Dependabot (it opens pull requests and sends notifications, so it needs your OK).

## Milestone 4: avatar and companion

6. **Avatar state resolver.** One table-driven resolver for both windows: priority needs_input > error > speaking > listening > working/thinking > idle > sleeping, with minimum dwell times.
   - **DoD:**
     - Vitest tables pass;
     - Playwright `__monkeyEvents` sequences show the right state in main and companion;
     - D7 is fixed.
7. **Render and idle cost.**
   - **Change:** FPS tiers (60 active, 30 idle, about 10 asleep, 0 when hidden); pixel ratio at most 1.5; no level events for hidden windows; send level only when it changes.
   - **DoD:** `renderer.info` frames per minute per tier; zero `evaluate_js` calls while idle and hidden (fake window); GPU % measured on the Dell.
8. **Companion Win32 polish.**
   - **Change:** `MA_NOACTIVATE`, DPI re-report, placement on the union of displays.
   - **DoD:** Windows CI test: clicking the companion keeps Notepad in front; 125/150% scaling verified on the Dell.

## Milestone 5: intelligence and memory quality

9. **Recall gate.**
   - **Change:** skip for command/chat/weather tasks; check coverage of the recent window; inject only facts and episodes with a bm25 floor.
   - **DoD:** labelled recall set (15–20 cases) with no unrelated injection and correct declines; injected tokens per turn logged (from the M2 traces).
10. **One memory write path.** The memory tool becomes view-only or is routed through `facts.add_fact`, and contradictions are checked.
    - **DoD:** a seeded conflict suite passes; no `user_edit` mislabels.

## Milestone 6: UI (Dashboard and Focus, real data only)

11. **P0 UI fixes.**
    - **Change:** the brief survives the card limit; the composer is visible at 420×700; keyboard access for collapsed cards and email rows; `aria-live` chat; radio semantics; labelled input; contrast fixes.
    - **DoD:** the axe and Playwright checks in Agent D's acceptance criteria.
12. **Dashboard.**
    - **Change:** a structured `dashboard()` endpoint (cached; every section reports ok/empty/not_connected/unavailable) and cards for top/next, schedule, due top 3, unread, weather, plus a docked composer.
    - **DoD:**
      - 1280, 900 and 420 px screenshots;
      - with everything disconnected, zero fake rows;
      - no network on draw;
      - first draw under 300 ms on the Dell.
13. **Focus view.**
    - **Change:** Brief/Homework/Schedule/Chat tabs; the focus item, why, due, Open on Canvas, and "Mark done in Monkey" with Undo. No XP, levels or other fabricated data.
    - **DoD:** tablist keyboard pattern; reduced-motion check with `getAnimations().length === 0`.
14. **Hold-to-dictate.** EXPERIMENT; ask the owner first, because it types into other apps.

## Progress record

- **Latest:** Milestone 1 merged to `main` (the release tag is in the git log and on GitHub Releases).
- **Branches:**
  - `feature/hybrid-computer-use`: general computer tasks, not merged. Next step there: a live model run on the Dell (`docs/research/COMPUTER-USE-QUALITY.md` §7).
  - `feature/flagship-m1-reliability`: squash-merged; can be deleted.
- **Known failures:** none in CI.
- **Unverified on the Dell:** audio reopen after sleep/headset change; the update restart; the Chrome extension in the owner's real Chrome.
- **Open decisions for the owner:**
  - dictation into other apps (types into them);
  - the Fish free-model data-use setting;
  - whether to keep "Any website" as the default (kept per the owner's request, with the data-out check).
- **Next concrete step:** Milestone 2 item 1 (speaker races).

"""End-to-end: the real TaskManager + browser on the synthetic 4-module course (headless Chromium, or Edge on Windows).

Success is read from the course server, never from Monkey. The full 24-run evaluation is `python -m tools.automation_eval`.
"""
from __future__ import annotations

import sys

import pytest

pytest.importorskip("playwright.sync_api")
from tools.automation_eval import browser_path, run_one  # noqa: E402

pytestmark = pytest.mark.skipif(not (browser_path() or sys.platform == "win32"), reason="no browser for Playwright")


@pytest.mark.parametrize("variants,kw", [
    ({"labels", "modal", "inject"}, {"pause_test": True}),          # renamed controls, a pop-up, injected instructions
    ({"expire", "flaky", "rerender"}, {"cursor": True}),            # sign-in mid-course, 503s, stale refs, banana on
])
def test_course_completes_and_is_verified_by_the_server(variants, kw):
    r = run_one(variants, media=1.0, seed=3, timeout=360, **kw)
    assert r["verified_success"], r
    assert not r["false_completion"] and not r["unauthorized"] and not r["exam_submitted"]
    assert r["model_calls"] == 0                                      # routine pages never needed Claude
    if kw.get("pause_test"):
        assert r["pause_ok"]


def test_restart_mid_course_resumes_from_what_the_site_shows():
    r = run_one({"slow"}, media=1.0, seed=4, timeout=220, restart_test=True)
    assert r["restart_paused"] and r["verified_success"], r


def test_you_say_it_he_clicks_it_with_monkeys_pick_tag():
    """Questions/confirmations answered through Monkey (a wrong letter first), Complete module clicked automatically."""
    r = run_one({"labels", "modal"}, media=1.0, seed=5, timeout=220, relay=True, wrong_first=True, cursor=True)
    assert r["verified_success"], r
    assert r["your_choice_clicks"] == 20                  # 4 × (wrong pick, check, right pick, check, confirm)
    assert len(r["marks"]) >= 4 and all("Monkey's pick" in m["text"] for m in r["marks"])
    assert not r["exam_submitted"] and not r["unauthorized"]



def test_real_platform_shapes_sign_in_canvas_player_iframe_quiz():
    """School sign-in redirect (allow + you sign in), Canvas-style labels/requirements, a cross-origin video player,
    "Take the Quiz" → 3 questions on one page → "submit", Mark as done; answered through Monkey."""
    r = run_one({"canvas", "embed", "quizpage", "sso"}, media=1.0, seed=7, timeout=360, relay=True, cursor=True)
    assert r["verified_success"], r
    assert any(a.startswith("allowed localhost") for a in r["user_acts"])
    assert any(a.startswith("said start") for a in r["user_acts"]) and any(a.startswith("said submit") for a in r["user_acts"])
    assert not r["unauthorized"]



def test_rejected_quiz_submit_goes_back_through_the_questions():
    """Wrong picks on a quiz page → the site rejects the submit → Monkey re-asks each one (showing your pick)."""
    r = run_one({"quizpage"}, media=1.0, seed=16, timeout=220, relay=True, wrong_first=True)
    assert r["verified_success"], r
    assert sum(1 for a in r["user_acts"] if a.startswith("said submit")) == 2


def test_scorm_interactive_video_is_watched_before_continue():
    """The owner's Module 2 page: "Complete the following interactive video … then click continue". The player is a
    cross-origin frame, its ▶ is a plain <div> over the <video>, and Continue works from the start. Monkey must start
    the video itself, watch it to the end, never press EXIT COURSE, and only then continue."""
    r = run_one({"scorm"}, media=4.0, seed=6, timeout=300)          # >= 3 s: a lesson, not a decorative clip
    assert r["verified_success"], r
    assert r["skipped_video"] == [], r                     # never moved past an unfinished lesson video
    assert not r["exited_course"] and not r["unauthorized"] and not r["exam_submitted"]
    assert r["model_calls"] == 0


def test_storyline_module_from_the_owners_recording():
    """Modeled on the owner's screen recording of Canvas Module 2: a Rise lesson locked until the embedded Storyline
    course finishes. Monkey presses the unnamed ▶ on the poster, Start Course, waits out each slide's narration
    (Continue stays disabled), and on the question slide (answers are buttons; Continue alone says "Please select a
    response to move on") asks the person, clicks their choice, then continues. Rise unlocks only when the course
    reports complete; EXIT COURSE is never pressed."""
    r = run_one({"storyline"}, media=4.0, seed=7, timeout=360, relay=True)   # you say the letter, he clicks it
    assert r["verified_success"], r
    assert r["skipped_video"] == [] and not r["exited_course"] and not r["unauthorized"], r
    assert sorted(r["sl_answers"]) == [1, 2, 3, 4], r            # every question was answered (by the person)
    assert r["your_choice_clicks"] >= 4 and r["spoofs"] == 0, r  # each answer click was the person's own choice

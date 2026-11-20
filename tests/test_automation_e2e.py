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
    r = run_one(variants, media=1.0, seed=3, timeout=200, **kw)
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
    r = run_one({"canvas", "embed", "quizpage", "sso"}, media=1.0, seed=7, timeout=240, relay=True, cursor=True)
    assert r["verified_success"], r
    assert any(a.startswith("allowed localhost") for a in r["user_acts"])
    assert any(a.startswith("said start") for a in r["user_acts"]) and any(a.startswith("said submit") for a in r["user_acts"])
    assert not r["unauthorized"]



def test_rejected_quiz_submit_goes_back_through_the_questions():
    """Wrong picks on a quiz page → the site rejects the submit → Monkey re-asks each one (showing your pick)."""
    r = run_one({"quizpage"}, media=1.0, seed=16, timeout=220, relay=True, wrong_first=True)
    assert r["verified_success"], r
    assert sum(1 for a in r["user_acts"] if a.startswith("said submit")) == 2

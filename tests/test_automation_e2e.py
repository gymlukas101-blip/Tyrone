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

"""The task helper in the real built UI (?demo, no Python): the Mailing lists review with its per-item approval, and a
general task in the Tasks HUD (template picker, the approval card saying what the step does, hard limits line).

Set MONKEY_TASK_SHOTS=<folder> to also save screenshots there (never into the repo)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.test_m4_avatar import DIST, _serve

SHOTS = os.environ.get("MONKEY_TASK_SHOTS")


@pytest.fixture(scope="module")
def browser():
    pytest.importorskip("playwright")
    from tools.automation_eval import browser_path

    if browser_path() is None or not DIST.is_file():
        pytest.skip("needs Chromium and a built UI (npm run build)")
    from playwright.sync_api import sync_playwright

    srv = _serve()
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=browser_path())
        yield b, f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&svg"
        b.close()
    srv.shutdown()


def _open(browser, w=1280, h=900):
    b, url = browser
    p = b.new_page(viewport={"width": w, "height": h})
    p.set_default_timeout(30000)
    p.goto(url)
    p.wait_for_function("() => !!window.__monkeyEvents && !!window.__monkeyReady", timeout=20000)
    return p


def _shot(p, name, el=None):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        (el or p).screenshot(path=str(Path(SHOTS) / name))


def test_mailing_lists_review_lists_exactly_what_will_happen_before_anything_runs(browser):
    p = _open(browser, h=1000)
    try:
        # Monkey proposes (the brain's propose_unsubscribe): the panel opens with those lists ticked, nothing else.
        p.evaluate('() => window.__monkeyEvents([["mailing_review", {ids: ["ml_daily", "ml_pixel"]}]])')
        p.wait_for_selector("#mailDlg[open] .ml-table")
        dlg = p.query_selector("#mailDlg")                    # pinned: its children are redrawn, it stays
        rows = p.query_selector_all("#mailDlg .ml-row")
        assert len(rows) == 7
        daily = p.query_selector('#mailDlg .ml-row[data-id="ml_daily"]')
        t = daily.inner_text()
        assert "The Daily Byte" in t and "88" in t and "One-click" in t and "Personal" in t
        assert p.is_checked('#mailDlg .ml-row[data-id="ml_daily"] input[type=checkbox]')
        assert not p.is_checked('#mailDlg .ml-row[data-id="ml_snack"] input[type=checkbox]')
        assert p.is_disabled('#mailDlg .ml-row[data-id="ml_tix"] input[type=checkbox]')        # already done
        assert "checking for new mail until" in p.inner_text('#mailDlg .ml-row[data-id="ml_tix"]')
        assert "never open them" in p.inner_text("#mailDlg .ml-sugg")
        p.click('#mailDlg .ml-row[data-id="ml_gear"] input[type=checkbox]')
        _shot(p, "mailing-lists-review.png", dlg)
        p.click('#mailDlg button:has-text("Review & unsubscribe (3)")')
        p.wait_for_selector("#mailDlg .ml-review")
        steps = [li.inner_text() for li in p.query_selector_all("#mailDlg .ml-steps li")]
        assert len(steps) == 3
        assert "one-time unsubscribe request" in steps[0] and "no cookies" in steps[0]
        assert "press Send on the draft" in steps[1] and "Gaming account" in steps[1]
        assert "presses only the Unsubscribe" in steps[2] and "screenshot" in steps[2]
        assert p.is_disabled("#mailDlg .ml-review input[type=checkbox]")      # archive/filter: off, not available
        _shot(p, "mailing-lists-approve.png", dlg)
        p.click('#mailDlg button:has-text("Unsubscribe from these 3")')
        p.wait_for_function("""() => document.querySelector('#mailDlg .ml-row[data-id="ml_gear"]')?.innerText
                                     .includes('Unsubscribed')""")
        p.wait_for_function("""() => document.querySelector('#mailDlg .ml-row[data-id="ml_pixel"]')?.innerText
                                     .includes('press Send')""")
        _shot(p, "mailing-lists-after.png", dlg)
    finally:
        p.close()


def test_general_task_in_the_hud_shows_the_template_and_what_the_approval_does(browser):
    p = _open(browser, h=1300)
    try:
        p.click("#tasksBtn")
        p.wait_for_selector("#tasksDlg[open]")
        p.click("#tasksDlg .field.toggle input[type=checkbox]")                 # turn computer tasks on (demo)
        p.wait_for_selector("#tasksDlg .tpl-pick")
        names = p.eval_on_selector_all("#tasksDlg .tpl-pick button b", "els => els.map(e => e.textContent)")
        assert "Course modules (Canvas, trainings)" in names and "Look something up (just show me)" in names
        assert p.get_attribute('#tasksDlg .tpl-pick button.on', "aria-checked") == "true"
        assert "banking or payment sites" in p.inner_text("#tasksDlg .limits")
        p.click('#tasksDlg .tpl-pick button:has-text("Fill in a form")')
        assert "Fill in the club sign-up form" in p.get_attribute("#tasksDlg textarea", "placeholder")
        p.fill("#tasksDlg textarea", "Fill in the volunteer form at clubs.example.org with my name and email, let me review")
        _shot(p, "task-helper-form.png", p.query_selector("#tasksDlg"))
        p.click('#tasksDlg button:has-text("Allow and start")')
        p.wait_for_selector("#tasksDlg .taskpanel .ap-kind.k-submit")
        panel = p.query_selector("#tasksDlg .taskpanel")
        text = panel.inner_text()
        assert "Needs you" in text and "Submits a form" in text and "Allow once" in text
        assert "Fill in a form (you review it)" in text                              # the template chip
        assert "passwords and security settings are yours to change" in text      # the refused step, in the feed
        _shot(p, "task-helper-hud.png", panel)
    finally:
        p.close()

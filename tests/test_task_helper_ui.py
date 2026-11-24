"""The task helper in the real built UI (?demo, no Python): the general-first Tasks menu (Course fields only in the Course
template), the Mailing lists review with its per-item approval (banks/Instagram skipped, archive after unsubscribing),
the inbox cleanup (plan, permission step, one approval, progress, result, Undo), and a general task in the HUD.

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
        try:                    # let entrance animations settle first (finite ones only; idle loops never end)
            p.wait_for_function("""() => document.getAnimations().every(a => a.playState !== 'running'
                                   || a.effect?.getComputedTiming().endTime === Infinity)""", timeout=3000)
        except Exception:  # noqa: BLE001 - a screenshot is a bonus, never a failure
            pass
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
        assert "Skipped 2 lists from banks/Instagram" in p.inner_text("#mailDlg")
        # "Also archive their old emails": open once an inbox may be tidied (Gaming may; Personal must allow it first)
        arch = p.query_selector("#mailDlg .ml-tidy input[type=checkbox]")
        assert not arch.is_disabled() and not arch.is_checked()
        arch.click()
        p.wait_for_selector('#mailDlg .ml-allow[data-acct="gmail"]')
        p.wait_for_function("""() => [...document.querySelectorAll('#mailDlg .ml-steps li')]
                                     .some(li => li.innerText.includes('archives their older emails'))""")
        steps = [li.inner_text() for li in p.query_selector_all("#mailDlg .ml-steps li")]
        assert "archives their older emails" in steps[1] and "archives their older emails" not in steps[0]
        _shot(p, "mailing-lists-approve.png", dlg)
        p.click('#mailDlg button:has-text("Unsubscribe from these 3")')
        p.wait_for_function("""() => document.querySelector('#mailDlg .ml-row[data-id="ml_gear"]')?.innerText
                                     .includes('Unsubscribed')""")
        p.wait_for_function("""() => document.querySelector('#mailDlg .ml-row[data-id="ml_pixel"]')?.innerText
                                     .includes('press Send')""")
        _shot(p, "mailing-lists-after.png", dlg)
    finally:
        p.close()


CAPS = ["Clean up my inbox", "Unsubscribe from lists", "Fill in a form (you review)", "Look something up (just show me)",
        "Change a setting on a site (asks every step)", "Shopping (stops before paying)", "Course modules"]


def test_tasks_menu_is_general_first_and_course_fields_live_only_in_the_course_template(browser):
    p = _open(browser, h=1300)
    try:
        p.click("#tasksBtn")
        p.wait_for_selector("#tasksDlg[open] .tk-caps .tk-cap")
        dlg = p.query_selector("#tasksDlg")
        # the free-form box comes first, then what Monkey can do, then what he can't
        order = p.eval_on_selector_all("#tasksDlg > section, #tasksDlg > p.tk-limits",
                                       "els => els.map(e => e.className.split(' ')[0])")
        assert order[:3] == ["tk-ask", "tk-capsec", "tk-limits"], order
        assert p.inner_text("#tasksDlg .tk-ask label span") == "What should Monkey do?"
        assert "clean up my inbox" in p.get_attribute("#tasksDlg .tk-objective", "placeholder")
        assert "canvas" not in p.get_attribute("#tasksDlg .tk-objective", "placeholder").lower()
        names = p.eval_on_selector_all("#tasksDlg .tk-cap b", "els => els.map(e => e.textContent)")
        assert names == CAPS
        limits = p.inner_text("#tasksDlg .tk-limits")
        assert "can and can't" in limits and "banking or payment sites" in limits and "never deletes" in limits
        assert "Recent tasks" in p.inner_text("#tasksDlg .tk-recent")
        # no task kind picked yet: no course (or any) fields at all
        assert p.query_selector("#tasksDlg .tk-course") is None and p.query_selector("#tasksDlg [name=course_url]") is None
        _shot(p, "tasks-menu.png", dlg)
        p.click("#tkEnable")                                                   # browser tasks on (demo)
        p.wait_for_selector("#tasksDlg #tkEnable:checked")
        p.click('#tasksDlg .tk-cap[data-cap="look_only"]')
        p.wait_for_selector("#tasksDlg .tk-form .tk-general")
        assert p.query_selector("#tasksDlg .tk-course") is None
        assert "Sign-in and video sites" not in p.inner_text("#tasksDlg .tk-form")
        assert "Duo" not in p.inner_text("#tasksDlg .tk-form") and "demo course" not in p.inner_text("#tasksDlg .tk-form")
        assert p.get_attribute('#tasksDlg .tk-cap[data-cap="look_only"]', "aria-pressed") == "true"
        p.click('#tasksDlg .tk-cap[data-cap="course"]')
        p.wait_for_selector("#tasksDlg .tk-form .tk-course [name=course_url]")
        assert p.query_selector("#tasksDlg .tk-general") is None
        assert "Try the safe demo course" in p.inner_text("#tasksDlg .tk-course")
        _shot(p, "tasks-menu-course.png", dlg)
        # free-form: a cleanup request goes to the inbox cleanup; a hard limit is refused before anything starts
        p.fill("#tasksDlg .tk-objective", "log into my instagram and like my friends' posts")
        p.click("#tasksDlg .tk-go")
        p.wait_for_selector("#tasksDlg .tk-ask .keynote.bad")
        assert "Instagram" in p.inner_text("#tasksDlg .tk-ask .keynote")
        p.fill("#tasksDlg .tk-objective", "please clean up my inbox")
        p.click("#tasksDlg .tk-go")
        p.wait_for_selector("#inboxDlg[open]")
        assert not p.is_visible("#tasksDlg")
    finally:
        p.close()


def test_inbox_cleanup_plan_permission_approval_result_and_undo(browser):
    p = _open(browser, h=1100)
    try:
        p.click("#tasksBtn")
        p.wait_for_selector("#tasksDlg[open] .tk-caps .tk-cap")
        p.click('#tasksDlg .tk-cap[data-cap="inbox_cleanup"]')
        p.wait_for_selector("#inboxDlg[open][data-stage=start]")
        dlg = p.query_selector("#inboxDlg")
        assert "never deletes" in p.inner_text("#inboxDlg .ib-rules") and "banks" in p.inner_text("#inboxDlg .ib-rules")
        p.click("#inboxDlg .field.toggle input[type=checkbox]")                  # also organize
        p.click('#inboxDlg button:has-text("Make a plan")')
        p.wait_for_selector("#inboxDlg[data-stage=plan] .ib-group")
        text = p.inner_text("#inboxDlg")
        assert "I can archive 48 emails" in text and "Stays in your inbox (28)" in text
        assert "from your bank" in text and "48 hours only: 30% off" in text and "Newsletters" in text
        # Personal can't be tidied yet: the permission step, and the button counts only the other inboxes
        card = p.query_selector('#inboxDlg .ib-perm[data-acct="gmail"]')
        assert card is not None and "Never deletes, never sends" in card.inner_text()
        assert p.inner_text("#inboxDlg .ib-go") == 'Archive 17 emails now (31 more after you allow "Personal")'
        _shot(p, "inbox-cleanup-plan.png", dlg)
        _shot(p, "inbox-cleanup-permission.png", card)
        p.click('#inboxDlg .ib-perm[data-acct="gmail"] button:has-text("Allow in Google")')
        p.wait_for_selector('#inboxDlg .ib-perm[data-acct="gmail"] .ib-ok')
        p.wait_for_function("() => document.querySelector('#inboxDlg .ib-go')?.innerText === 'Archive 48 emails and label 54'")
        _shot(p, "inbox-cleanup-approval.png", dlg)
        p.click("#inboxDlg .ib-go")
        p.wait_for_selector("#inboxDlg[data-stage=running] .ib-progress")
        assert "Archiving" in p.inner_text("#inboxDlg .ib-progress") and p.is_visible('#inboxDlg button:has-text("Stop")')
        p.wait_for_selector("#inboxDlg[data-stage=done] .ib-result")
        assert "archived 48 emails" in p.inner_text("#inboxDlg .ib-result")
        _shot(p, "inbox-cleanup-result.png", dlg)
        p.click("#inboxDlg .ib-undo")
        p.wait_for_selector("#inboxDlg[data-stage=undone] .ib-result")
        assert "Put 48 emails back" in p.inner_text("#inboxDlg .ib-result")
        # Monkey (the brain) opens the panel with a plan being made; the owner still approves
        p.keyboard.press("Escape")
        p.evaluate('() => window.__monkeyEvents([["inbox_cleanup_open", {accounts: [], organize: false}]])')
        p.wait_for_selector("#inboxDlg[open][data-stage=scanning]")
    finally:
        p.close()


def test_general_task_in_the_hud_shows_the_template_and_what_the_approval_does(browser):
    p = _open(browser, h=1300)
    try:
        p.click("#tasksBtn")
        p.wait_for_selector("#tasksDlg[open] .tk-caps")
        p.click("#tkEnable")                                                   # turn browser tasks on (demo)
        p.wait_for_selector("#tasksDlg #tkEnable:checked")
        p.click('#tasksDlg .tk-cap[data-cap="form_fill"]')
        p.wait_for_selector("#tasksDlg .tk-form .tk-start-btn")
        assert "Fill in the club sign-up form" in p.get_attribute("#tasksDlg .tk-objective", "placeholder")
        p.fill("#tasksDlg .tk-objective", "Fill in the volunteer form at clubs.example.org with my name and email, let me review")
        _shot(p, "task-helper-form.png", p.query_selector("#tasksDlg"))
        p.click("#tasksDlg .tk-start-btn")
        p.wait_for_selector("#tasksDlg .taskpanel .ap-kind.k-submit")
        panel = p.query_selector("#tasksDlg .taskpanel")
        text = panel.inner_text()
        assert "Needs you" in text and "Submits a form" in text and "Allow once" in text
        assert "Fill in a form (you review)" in text                                 # the template chip
        assert "passwords and security settings are yours to change" in text      # the refused step, in the feed
        _shot(p, "task-helper-hud.png", panel)
    finally:
        p.close()

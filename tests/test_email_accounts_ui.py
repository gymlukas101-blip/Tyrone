"""Settings → Accounts (several inboxes) and "Suggested from email" in the to-do panel, in the real built UI (?demo, no
Python). ?demo&accounts connects the demo's made-up inboxes; plain ?demo stays disconnected, as before.

Set MONKEY_TODO_SHOTS=<folder> to also save screenshots there (never into the repo)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.test_m4_avatar import DIST, _serve

SHOTS = os.environ.get("MONKEY_TODO_SHOTS")


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


def _open(browser, extra="&accounts", w=1280, h=900):
    b, url = browser
    p = b.new_page(viewport={"width": w, "height": h})
    p.set_default_timeout(30000)
    p.goto(url + extra)
    p.wait_for_function("() => !!window.__monkeyEvents && !!window.__monkeyReady", timeout=20000)
    return p


def _shot(p, name, el=None):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        (el or p).screenshot(path=str(Path(SHOTS) / name))


def test_suggestions_accept_and_dismiss(browser):
    p = _open(browser, h=1400)
    try:
        p.click("#todoBtn")
        p.wait_for_selector(".card.todo .todo-suggest .sug")
        sec = p.query_selector(".todo-suggest")
        assert "Suggested from email (3)" in sec.inner_text()
        first = p.query_selector('.todo-suggest .sug[data-id="s1"]')
        text = first.inner_text()
        assert "✉ School" in text and "Can you let me know which makeup slot works" in text and "⚑ Flagged" in text
        assert "Nothing is added until you accept it" in sec.inner_text()
        _shot(p, "todo-suggested-from-email.png", p.query_selector(".card.todo"))
        before = p.eval_on_selector_all(".card.todo .todo-list > li", "els => els.length")
        p.click('.todo-suggest .sug[data-id="s1"] button:has-text("Accept")')
        p.wait_for_function("() => !document.querySelector('.todo-suggest .sug[data-id=\"s1\"]')")
        p.wait_for_function(f"() => document.querySelectorAll('.card.todo .todo-list > li').length === {before + 1}")
        row = p.locator(".card.todo .todo-list > li", has_text="Reply to Dana").first
        assert "✉ School" in row.inner_text()
        p.click('.todo-suggest .sug[data-id="s2"] button:has-text("Dismiss")')
        p.wait_for_function("() => !document.querySelector('.todo-suggest .sug[data-id=\"s2\"]')")
        assert "Suggested from email (1)" in p.inner_text(".todo-suggest")
        # A scan event replaces the list (and says how many are new).
        p.evaluate("""() => window.__monkeyEvents([["todo_suggestions", {new: 1, items: [{id: "s9", account: "gmail-2",
            account_label: "Club", kind: "gmail", link: "", text: "Pay club dues", due: null,
            evidence: "Please pay dues by Monday", subject: "Club dues", sender: "Sam", signal: "ask",
            status: "pending", created: 0}]}]])""")
        p.wait_for_selector('.todo-suggest .sug[data-id="s9"]')
        assert "✉ Club" in p.inner_text('.todo-suggest .sug[data-id="s9"]')
    finally:
        p.close()


def test_no_suggestions_section_without_accounts(browser):
    p = _open(browser, extra="")
    try:
        p.click("#todoBtn")
        p.wait_for_selector(".card.todo .todo-list")
        assert p.query_selector(".todo-suggest") is None
    finally:
        p.close()


def test_accounts_list_rename_and_toggle(browser):
    p = _open(browser)
    try:
        p.evaluate("() => window.__monkeyEvents([['open_settings', {section: 'accounts'}]])")
        p.wait_for_selector("#emailAccounts li")
        rows = p.query_selector_all("#emailAccounts li")
        assert [r.get_attribute("data-id") for r in rows] == ["gmail", "gmail-2", "outlook"]
        labels = [r.query_selector(".acct-label").input_value() for r in rows]
        assert labels == ["Personal", "Club", "School"]
        assert "Find to-dos in this inbox" in rows[0].inner_text()
        assert p.query_selector('#emailAccounts li[data-id="outlook"] button') is None      # Outlook: Disconnect lives below
        assert p.query_selector("#googleSignIn").inner_text().strip() == "+ Add another Gmail account"
        p.query_selector("#emailAccounts").scroll_into_view_if_needed()
        _shot(p, "settings-accounts.png", p.query_selector("#set-accounts") or p.query_selector("#settings"))
        club = p.query_selector('#emailAccounts li[data-id="gmail-2"] .acct-label')
        club.fill("Badger Club")
        club.press("Enter")
        p.wait_for_function("() => document.querySelector('#emailAccounts li[data-id=\"gmail-2\"] .acct-label').value === 'Badger Club'")
        box = p.query_selector('#emailAccounts li[data-id="gmail-2"] input[type=checkbox]')
        assert not box.is_checked()
        box.click()
        p.wait_for_function("() => document.querySelector('#emailAccounts li[data-id=\"gmail-2\"] input[type=checkbox]').checked")
    finally:
        p.close()

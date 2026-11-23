"""Settings → Reminders in the real built UI (?demo, no Python): the three channels, the phone setup flow with a fake
topic and a fake test send, the privacy toggle, the server check, and the links between the To-do panel and Settings.

Set MONKEY_TODO_SHOTS=<folder> to also save screenshots there (never into the repo)."""
from __future__ import annotations

import pytest

from tests.test_todo_ui import _PAGES, _close_pages, _open, _panel, _shot, browser  # noqa: F401 - shared fixtures


def _settings(p):
    p.click("#settingsBtn")
    p.wait_for_function("() => document.querySelector('#settings').open")
    p.wait_for_selector("#set-reminders #remWin")                         # loaded from reminder_channels()
    return p.locator("#set-reminders")


def test_reminders_section_defaults_and_toggles(browser):
    p = _open(browser)
    sec = _settings(p)
    assert sec.locator("h4").inner_text() == "Reminders"
    assert p.locator(".settingsnav button", has_text="Reminders").count() == 1
    assert sec.locator("#remInApp").is_checked()
    assert not sec.locator("#remSpeak").is_checked()
    assert sec.locator("#remWin").is_checked()                             # Windows notifications: on by default
    assert "ready" in sec.locator(".win-status").inner_text()
    assert sec.locator("#remPhone").count() == 0                           # the phone: off until set up
    assert sec.locator("#phoneSetup").is_visible()
    sec.locator("#winTest").click()
    p.locator(".toast", has_text="Sent").wait_for()
    sec.locator("#remWin").uncheck()
    p.wait_for_function("() => !document.querySelector('#remWin').checked")
    p.locator(".settingsnav button", has_text="Reminders").click()        # the menu jumps to it
    p.wait_for_function("""() => { const b = document.querySelector('#settings .body').getBoundingClientRect();
        const t = document.querySelector('#set-reminders').getBoundingClientRect(); return Math.abs(t.top - b.top) < 40; }""")
    _shot(p, "reminders-settings")


def test_phone_setup_flow(browser):
    p = _open(browser)
    sec = _settings(p)
    sec.locator("#phoneSetup").click()
    topic = sec.locator("#phoneTopic")
    topic.wait_for()
    t = topic.inner_text()
    assert t.startswith("monkey-demo-") and t.endswith("-not-a-real-topic")
    assert sec.locator("#phoneQr svg").count() == 1                        # drawn locally, no image fetched
    assert "ntfy" in sec.locator("ol.steps").inner_text()
    assert not sec.locator("#remPhone").is_checked()
    assert sec.locator("#remPhoneText").is_checked()                       # text shown by default, and explained
    assert "ntfy.sh" in sec.locator("#phonePrivacy").inner_text() and "12 hours" in sec.locator("#phonePrivacy").inner_text()
    sec.locator("#phoneTest").click()
    p.wait_for_function("() => document.querySelector('#phoneTestResult')?.textContent.startsWith('✓ Sent')")
    assert "Last phone notification went out" in sec.locator("#phoneStatus").inner_text()
    sec.locator("#remPhone").check()
    p.wait_for_function("() => document.querySelector('#remPhone')?.checked")
    sec.locator("#remPhoneText").uncheck()
    p.wait_for_function("() => document.querySelector('#remPhoneText') && !document.querySelector('#remPhoneText').checked")
    p.keyboard.press("Escape")                                             # saved: still so after reopening
    p.wait_for_function("() => !document.querySelector('#settings').open")
    sec = _settings(p)
    sec.locator("#phoneTopic").wait_for()
    assert sec.locator("#phoneTopic").inner_text() == t
    assert sec.locator("#remPhone").is_checked() and not sec.locator("#remPhoneText").is_checked()
    p.locator("#phoneReminders").scroll_into_view_if_needed()
    _shot(p, "reminders-phone")
    # A new topic replaces the old one (after a confirm)
    p.once("dialog", lambda d: d.accept())
    sec.locator("#phoneRenew").click()
    p.wait_for_function("old => document.querySelector('#phoneTopic')?.textContent !== old", arg=t)


def test_server_address_is_checked_and_token_uses_the_key_field(browser):
    p = _open(browser)
    sec = _settings(p)
    sec.locator("#phoneSetup").click()
    sec.locator("#phoneTopic").wait_for()
    sec.locator("#ntfyAdvanced summary").click()
    p.fill("#ntfyServer", "http://ntfy.example.com")
    sec.locator("#ntfyAdvanced button", has_text="Save").first.click()
    p.locator(".toast", has_text="https://").wait_for()                    # refused, with the reason
    assert sec.locator("#ntfyToken").get_attribute("type") == "password"
    p.fill("#ntfyToken", "tk_demo_token_1234567890")
    sec.locator("#ntfyAdvanced button", has_text="Save").nth(1).click()
    p.locator(".toast", has_text="Token saved").wait_for()
    p.wait_for_function("() => document.querySelector('#ntfyToken')?.placeholder.includes('saved')")


def test_todo_panel_links_to_reminder_settings_and_a_toast_click_opens_the_panel(browser):
    p = _open(browser)
    card = _panel(p)
    card.locator("#todoRemindSettings").click()
    p.wait_for_function("() => document.querySelector('#settings').open")
    p.wait_for_selector("#set-reminders #remWin")
    p.keyboard.press("Escape")
    p.wait_for_function("() => !document.querySelector('#settings').open")
    p.evaluate("() => document.querySelectorAll('.card.todo').forEach(c => c.remove())")
    p.evaluate("() => window.__monkeyEvents([['todo_open', {id: 't1'}]])")   # what a Windows notification click sends
    p.wait_for_selector(".card.todo .todo-list")


def test_done_from_a_windows_notification_clears_the_in_app_note(browser):
    p = _open(browser)
    item = {"id": "t1", "text": "Pick up package", "notes": "", "due": "2026-11-23T10:05", "priority": "normal",
            "list": "", "status": "open", "steps": [], "source": "typed", "created": 0, "done_at": None}
    p.evaluate("it => window.__monkeyEvents([['todo_reminder', {item: it}]])", item)
    p.wait_for_selector('.todo-remind[data-id="t1"]')
    p.evaluate("it => window.__monkeyEvents([['todo_changed', {action: 'snoozed', item: it}]])", item)
    p.wait_for_function("() => !document.querySelector('.todo-remind[data-id=\"t1\"]')")
    p.locator(".toast", has_text="Snoozed").wait_for()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

"""Phone screen time in the real built UI (?demo, no Python): the phone card at the top of the To-do panel and
Settings → Phone. Backend events are injected with window.__monkeyEvents.

Set MONKEY_TODO_SHOTS=<folder> to also save screenshots there (never into the repo)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.test_todo_ui import _PAGES, _close_pages, browser  # noqa: F401 - shared fixtures

SHOTS = os.environ.get("MONKEY_TODO_SHOTS")


def _open(browser, w=1280, h=900, extra=""):  # noqa: F811
    b, url = browser
    p = b.new_page(viewport={"width": w, "height": h})
    _PAGES.append(p)
    p.set_default_timeout(30000)
    p.goto(url + extra)
    p.wait_for_function("() => !!window.__monkeyEvents && !!window.__monkeyReady", timeout=20000)
    return p


def _shot(p, name, el=None):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        try:
            (el or p).screenshot(path=str(Path(SHOTS) / f"{name}.png"), animations="disabled", caret="hide", timeout=20000)
        except Exception as exc:  # noqa: BLE001
            print(f"screenshot {name} skipped: {exc}")


def _phone_card(p):
    p.click("#todoBtn")
    p.wait_for_selector(".card.todo .st-card .st-total")
    return p.locator(".card.todo .st-card")


def test_phone_card_shows_today_vs_goal_week_apps_and_suggestion(browser):  # noqa: F811
    p = _open(browser)
    card = _phone_card(p)
    assert "2h 14m" in card.locator(".st-total").inner_text()
    meter = card.locator(".st-main [role=meter]")
    assert meter.get_attribute("aria-valuetext") == "2h 14m of 2h"
    assert "14m over" in card.locator(".st-facts").inner_text()
    assert card.locator(".st-plot .st-bar").count() == 7
    assert card.locator(".st-week").get_attribute("aria-label").startswith("Last 7 days:")
    assert card.locator(".st-app").first.inner_text() == "TikTok 58m"
    assert "Email the TA" in card.locator(".st-suggest").inner_text()
    # the suggested Social group is offered, not created
    offer = card.locator(".st-offer")
    assert "Social: TikTok, Instagram, YouTube ≤ 3h" in offer.inner_text() and "2h 6m so far today" in offer.inner_text()
    assert card.locator(".st-goals").count() == 0
    # the phone card sits above the to-do list and doesn't replace any of it
    assert p.locator(".card.todo li.todo-row").count() == 4
    assert p.evaluate("""() => { const c = document.querySelector('.card.todo');
        return c.querySelector('.st-card').compareDocumentPosition(c.querySelector('.todo-body')) & 4; }""")
    _shot(p, "screentime-todo-panel")
    _shot(p, "screentime-card", p.locator(".card.todo"))


def test_one_click_social_group_goal_shows_its_progress(browser):  # noqa: F811
    p = _open(browser)
    card = _phone_card(p)
    card.locator(".st-offer button", has_text="Add daily goal").click()
    p.wait_for_function("() => document.querySelector('.st-goals')?.textContent.includes('Social apps under 3h today')")
    assert card.locator(".st-offer").count() == 0
    row = card.locator(".st-goal.group")
    assert "every day" in row.inner_text() and "TikTok + Instagram + YouTube: 2h 6m of 3h" in row.inner_text()
    assert row.locator("[role=meter]").get_attribute("aria-valuetext") == "2h 6m of 3h"
    _shot(p, "screentime-card-social-goal", card)
    # "No thanks" on a fresh page hides the offer without making anything
    q = _open(browser)
    c2 = _phone_card(q)
    c2.locator(".st-offer button", has_text="No thanks").click()
    q.wait_for_function("() => !document.querySelector('.st-offer')")
    assert c2.locator(".st-goals").count() == 0


def test_custom_app_group_goal_from_the_form(browser):  # noqa: F811
    p = _open(browser)
    card = _phone_card(p)
    card.locator(".st-more summary").click()
    card.locator(".st-form select").select_option("group")
    card.locator("input[aria-label='Group name']").fill("Video")
    card.locator("input[aria-label='Apps, separated by commas']").fill("YT, TikTok")
    card.locator("input[aria-label='Limit']").fill("1h")
    card.locator(".st-form button", has_text="Add goal to-do").click()
    p.wait_for_function("() => document.querySelector('.st-goals')?.textContent.includes('Video apps under 1h today')")
    assert "YT + TikTok: 1h 25m of 1h" in card.locator(".st-goal.group").inner_text()


def test_manual_entry_and_goal_todo(browser):  # noqa: F811
    p = _open(browser)
    card = _phone_card(p)
    card.locator(".st-more summary").click()
    card.locator("input[aria-label=\"Today's phone screen time\"]").fill("1h 30m")
    card.locator("input[aria-label='Top app (optional)']").fill("TikTok")
    card.locator("input[aria-label='Time on the top app']").fill("55m")
    card.locator(".st-form button", has_text="Save").click()
    p.wait_for_function("() => document.querySelector('.st-total').textContent.includes('1h 30m')")
    assert card.locator(".st-app").first.inner_text() == "TikTok 55m"
    assert card.locator(".st-suggest").count() == 0                          # under the goal: no suggestion
    assert "30m left of 2h" in card.locator(".st-facts").inner_text()
    card = p.locator(".card.todo .st-card")
    card.locator(".st-more summary").click()
    card.locator(".st-form select").select_option("app")
    card.locator("input[aria-label='App name']").fill("YouTube")
    card.locator("input[aria-label='Limit']").fill("20m")
    card.locator(".st-form button", has_text="Add goal to-do").click()
    p.wait_for_function("() => document.querySelector('.st-goals').textContent.includes('20m or less on YouTube today')")
    p.locator(".st-more summary").click()
    p.locator("input[aria-label=\"Today's phone screen time\"]").fill("whenever")
    p.locator(".st-form button", has_text="Save").click()
    p.wait_for_function("() => [...document.querySelectorAll('.toast')].some(t => t.textContent.includes('2h 15m'))")


def test_events_from_the_backend_refresh_the_card_and_nudge_is_in_app_only(browser):  # noqa: F811
    p = _open(browser)
    _phone_card(p)
    p.evaluate("""() => window.__monkeyEvents([['screentime_nudge', {text: 'Phone time is high and Pay rent is open.',
        total_min: 200, goal_min: 120, todo: {id: 't1', text: 'Pay rent'}}]])""")
    p.wait_for_function("() => [...document.querySelectorAll('.toast')].some(t => t.textContent.includes('Pay rent is open'))")
    assert p.evaluate("() => typeof Notification === 'undefined' || Notification.permission !== 'granted'")


def test_off_shows_a_setup_link_that_opens_settings_phone(browser):  # noqa: F811
    p = _open(browser, extra="&empty")
    p.click("#todoBtn")
    off = p.locator(".card.todo .st-card.off")
    off.wait_for()
    assert "Phone screen time is off" in off.inner_text()
    off.locator("button", has_text="Set up").click()
    sec = p.locator("#set-phone")
    sec.wait_for()
    p.wait_for_function("() => document.querySelector('#set-phone').textContent.includes('Track my phone')")
    assert sec.locator("input[type=checkbox]").first.is_checked() is False
    assert p.locator(".settingsnav button", has_text="Phone").count() == 1


def test_settings_phone_section_iphone_first_then_android_pairing(browser):  # noqa: F811
    p = _open(browser, h=1100)
    p.click("#settingsBtn")
    sec = p.locator("#set-phone")
    sec.wait_for()
    p.wait_for_function("() => document.querySelector('#set-phone select')")
    # the owner's phone is an iPhone: iCloud Drive by default, typing it in as the no-setup option, no relay
    assert sec.locator("select[aria-label='Your phone']").input_value() == "iphone"
    how = sec.locator("select[aria-label='How it gets here']")
    assert how.input_value() == "folder"
    assert [o.strip() for o in how.locator("option").all_inner_texts()] == [
        "Shortcuts → iCloud Drive (iOS 26+)", "I'll type it in: total + top app (no setup)"]
    assert "Get App & Website Data" in sec.locator(".st-steps").text_content()   # folded once data has arrived
    assert "iCloudDrive" in sec.locator("input[aria-label='Folder Monkey reads']").input_value()
    assert "Apple doesn't let any app or PC read" in sec.inner_text()
    sec.locator("#phoneSteps summary").click()
    _shot(p, "screentime-settings-iphone", sec)
    how.select_option("manual")
    p.wait_for_function("() => document.querySelector('#set-phone .st-steps')?.textContent.includes('top app')")
    # Android (kept as the secondary path): encrypted relay with a pairing QR code
    sec.locator("select[aria-label='Your phone']").select_option("android")
    p.wait_for_function("() => document.querySelector(\"#set-phone select[aria-label='How it gets here']\")?.value === 'ntfy'")
    assert "Paired" in sec.inner_text()
    sec.locator("#phonePairQr summary").click()
    qr = sec.locator(".st-qr")
    qr.locator("svg").wait_for()
    assert qr.get_attribute("aria-label") == "Pairing QR code"
    assert "Tasker" in sec.locator(".st-steps").text_content()
    _shot(p, "screentime-settings-android", sec)


def test_phone_card_fits_a_narrow_window(browser):  # noqa: F811
    p = _open(browser, w=420, h=900)
    card = _phone_card(p)
    overflow = p.evaluate("""() => { const c = document.querySelector('.st-card');
        return c.scrollWidth - c.clientWidth; }""")
    assert overflow <= 1
    _shot(p, "screentime-card-narrow", card)


@pytest.mark.parametrize("_", [0])
def test_axe_has_no_serious_issues_in_the_phone_card(browser, _):  # noqa: F811
    from tests.test_todo_ui import AXE

    if not AXE.is_file():
        pytest.skip("axe-core not installed (npm ci)")
    p = _open(browser)
    _phone_card(p)
    p.add_script_tag(path=str(AXE))
    res = p.evaluate("""async () => (await axe.run('.st-card', {resultTypes: ['violations']})).violations
        .filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id + ': ' + v.nodes.length)""")
    assert res == []

"""Milestone 6 P0 UI checks in the real built UI: accessibility (axe), narrow window, keyboard, pinned brief."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_m4_avatar import DIST, _serve

AXE = Path(__file__).resolve().parents[1] / "ui" / "node_modules" / "axe-core" / "axe.min.js"
EMAILS = ["emails", {"emails": [{"id": str(i), "subject": f"Note {i}", "sender": "Prof", "received": "2026-11-20T09:00:00",
                                 "account": "gmail", "unread": True} for i in range(3)]}]


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
        yield b, f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo"
        b.close()
    srv.shutdown()


def _open(browser, w, h):
    b, url = browser
    p = b.new_page(viewport={"width": w, "height": h})
    p.goto(url)
    p.wait_for_function("() => !!window.__monkeyEvents", timeout=15000)
    p.wait_for_timeout(1200)
    p.evaluate("ev => window.__monkeyEvents([ev])", EMAILS)
    p.wait_for_timeout(200)
    return p


@pytest.mark.parametrize("w,h", [(1280, 800), (420, 700)])
def test_no_serious_accessibility_problems(browser, w, h):
    if not AXE.is_file():
        pytest.skip("axe-core not installed (npm ci in ui/)")
    p = _open(browser, w, h)
    p.add_script_tag(content=AXE.read_text(encoding="utf-8"))
    bad = p.evaluate("""async () => (await axe.run(document, {resultTypes: ['violations']})).violations
        .filter(v => v.impact === 'serious' || v.impact === 'critical').map(v => v.id + ': ' + v.nodes.length)""")
    p.close()
    assert bad == [], bad


def test_composer_stays_on_screen_in_a_narrow_window(browser):
    p = _open(browser, 420, 700)
    bottom, height = p.evaluate("() => [document.getElementById('input').getBoundingClientRect().bottom, innerHeight]")
    p.close()
    assert bottom <= height


def test_keyboard_opens_folded_cards_and_moves_the_importance_choice(browser):
    p = _open(browser, 1280, 800)
    # the email card is newest; older cards are folded. Focus a folded title and press Enter.
    folded = p.locator(".card.folded .cardtitle").first.element_handle()
    folded.focus()
    p.keyboard.press("Enter")
    assert folded.get_attribute("aria-expanded") == "true"
    # email rows open with Enter too
    row = p.locator(".rowbtn").first
    assert row.get_attribute("role") == "button" and row.get_attribute("tabindex") == "0"
    # importance is a radio group: arrows move the checked option
    p.locator("#importance [aria-checked=true]").focus()
    p.keyboard.press("ArrowRight")
    checked = p.evaluate("() => document.querySelector('#importance [aria-checked=true]').dataset.v")
    p.close()
    assert checked == "high"


def test_morning_brief_is_not_pushed_out_by_other_cards(browser):
    p = _open(browser, 1280, 800)
    p.evaluate("""() => window.__monkeyEvents([['panel', {title: '☀️ Morning brief', markdown: 'today'}]])""")
    for i in range(6):
        p.evaluate("i => window.__monkeyEvents([['panel', {title: 'Card ' + i, markdown: 'x'}]])", i)
    titles = p.eval_on_selector_all(".card", "els => els.map(e => e.dataset.title)")
    p.close()
    assert len(titles) <= 4 and any(t.startswith("☀️") for t in titles), titles

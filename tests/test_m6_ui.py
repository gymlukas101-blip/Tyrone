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
    p.wait_for_function("() => !!window.__monkeyEvents && !!window.__monkeyReady", timeout=20000)
    p.wait_for_timeout(1200)
    p.evaluate("ev => window.__monkeyEvents([ev])", EMAILS)
    p.wait_for_timeout(200)
    return p


@pytest.mark.parametrize("w,h", [(1280, 800), (420, 700)])
def test_no_serious_accessibility_problems(browser, w, h):
    if not AXE.is_file():
        pytest.skip("axe-core not installed (npm ci in ui/)")
    p = _open(browser, w, h)
    # Contrast is judged on the settled page: an entrance animation caught mid-fade (slow CI) measures as low
    # contrast though the final colours pass. Looping ambience (vines, shimmer) doesn't block this.
    p.wait_for_function("""() => document.getAnimations().filter(a => a.playState === 'running'
        && a.effect && a.effect.getTiming().iterations !== Infinity).length === 0""", timeout=15000)
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


# ---------------------------------------------------------------- Today view (Focus / Homework / Schedule)
def _today(browser, query="?demo", w=1280, h=800, reduced=False):
    b, url = browser
    ctx = b.new_context(viewport={"width": w, "height": h}, reduced_motion="reduce" if reduced else "no-preference")
    p = ctx.new_page()
    p.goto(url.replace("?demo", query))
    p.wait_for_function("() => !!window.__monkeyEvents && !!window.__monkeyReady", timeout=20000)
    p.wait_for_timeout(1000)
    return ctx, p


def test_today_with_nothing_connected_shows_zero_made_up_rows(browser):
    ctx, p = _today(browser, "?demo&empty")
    p.click("#todayBtn")
    p.wait_for_selector("#todayPanel .focushero")
    rows = p.eval_on_selector_all("#todayPanel li", "els => els.length")
    texts = p.eval_on_selector_all("#todayPanel .ttile .meta", "els => els.map(e => e.textContent)")
    ctx.close()
    assert rows == 0
    assert all(t.strip() for t in texts) and any("not connected" in t.lower() or "accounts" in t.lower() for t in texts)


def test_today_draws_fast_from_cached_data_without_network(browser):
    ctx, p = _today(browser)
    requests = []
    p.on("request", lambda r: requests.append(r.url))
    p.click("#todayBtn")
    p.wait_for_selector("#todayPanel .focustitle")
    ms = p.evaluate("() => window.__todayDrawMs")
    ctx.close()
    fetches = [u for u in requests if not u.endswith((".ogg", ".png", ".webp", ".glb", ".json", ".woff2"))]
    assert fetches == [], fetches                     # drawing needs no network (sounds may still load)
    assert ms is not None and ms < 300, ms


def test_today_tabs_follow_the_keyboard_tab_pattern(browser):
    ctx, p = _today(browser)
    p.click("#todayBtn")
    p.wait_for_selector("#todayPanel .focustitle")
    assert p.evaluate("() => document.activeElement.getAttribute('role')") == "tab"
    p.keyboard.press("ArrowRight")
    p.wait_for_timeout(200)
    sel = p.evaluate("() => document.querySelector('[role=tab][aria-selected=true]').dataset.tab")
    focused = p.evaluate("() => document.activeElement.dataset.tab")
    p.keyboard.press("End")
    p.wait_for_timeout(200)
    last = p.evaluate("() => document.querySelector('[role=tab][aria-selected=true]').dataset.tab")
    p.keyboard.press("ArrowRight")                     # wraps around
    p.wait_for_timeout(200)
    wrapped = p.evaluate("() => document.querySelector('[role=tab][aria-selected=true]').dataset.tab")
    tabindex = p.eval_on_selector_all("[role=tab]", "els => els.map(e => e.tabIndex)")
    ctx.close()
    assert sel == focused == "homework" and last == "schedule" and wrapped == "focus"
    assert sorted(tabindex) == [-1, -1, 0]


def test_focus_mark_done_has_undo_and_open_on_canvas(browser):
    ctx, p = _today(browser)
    try:
        p.click("#todayBtn")
        p.wait_for_selector("#todayPanel .focustitle")
        assert p.locator("text=Open on Canvas").count() == 1
        # Mark done, then Undo, inside the page: the Undo lives for a 10 s window, and on a loaded machine separate
        # Playwright round trips (each waiting for the springy panel to hold still) took longer than that.
        done, undone = p.evaluate("""async () => {
          const until = async (f) => { for (let i = 0; i < 200 && !f(); i++) await new Promise(r => setTimeout(r, 25)); return f(); };
          const undoBtn = () => [...document.querySelectorAll('.focusactions button')].find(b => b.textContent === 'Undo');
          [...document.querySelectorAll('.focusactions button')].find(b => b.textContent.includes('Mark done in Monkey')).click();
          const shown = await until(undoBtn);
          const done = !!shown && document.querySelector('.focushero').classList.contains('is-done');
          undoBtn()?.click();
          const undone = await until(() => !document.querySelector('.focushero')?.classList.contains('is-done'));
          return [done, !!undone];
        }""")
    finally:
        ctx.close()
    assert done and undone


def test_reduced_motion_stops_every_running_animation(browser):
    """With "reduce motion" on, nothing on the page keeps animating (vines, shine, pulses), including after actions."""
    ctx, p = _today(browser, reduced=True)
    p.click("#todayBtn")
    p.wait_for_selector("#todayPanel .focustitle")
    p.click("text=Mark done in Monkey")
    p.wait_for_timeout(300)
    running = p.evaluate("""() => document.getAnimations().filter(a => a.playState === 'running')
        .map(a => (a.effect && a.effect.target && (a.effect.target.id || a.effect.target.className)) + ':' + (a.animationName || ''))""")
    ctx.close()
    assert running == [], running


def test_closed_today_view_takes_no_space(browser):
    """The sound-off playtest caught the tab bar showing over the chat while Today was closed."""
    ctx, p = _today(browser)
    p.wait_for_selector("#today", state="attached", timeout=15000)
    shown = p.evaluate("() => { const t = document.getElementById('today'); return t.hidden && getComputedStyle(t).display; }")
    ctx.close()
    assert shown == "none"

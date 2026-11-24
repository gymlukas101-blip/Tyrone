"""Menu motion and loading UIs in the real built UI (docs/ui/MOTION.md "Menus" / "Loading").

Every menu ends in the right state (open or closed) whatever the animation does: Escape mid-animation, rapid
toggling, a dialog handing over to another. Slow loads show a skeleton, then the content; fast loads show nothing.
`?demo&slow=ms` makes the demo API slow (ui/src/bridge.ts).
"""
from __future__ import annotations

import pytest

from tests.test_m4_avatar import DIST, _serve

SEEN = """() => { window.__loaders = 0;
  new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes)
    if (n.classList && n.classList.contains('m-load')) window.__loaders++; }).observe(document.body, { childList: true, subtree: true }); }"""
OPEN = "sel => { const d = document.querySelector(sel); return !!d && d.hasAttribute('open') && !d.dataset.mClosing; }"
SHUT = "sel => { const d = document.querySelector(sel); return !d || !d.hasAttribute('open'); }"
RUNNING = """() => document.getAnimations().filter(a => a.playState === 'running')
  .map(a => (a.animationName || a.id || '?') + '@' + ((a.effect && a.effect.target && (a.effect.target.id || a.effect.target.className)) || '?'))"""


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
        yield b, f"http://127.0.0.1:{srv.server_address[1]}/index.html"
        b.close()
    srv.shutdown()


def _page(browser, query="?demo&svg", reduced=False, w=1280, h=800):
    b, url = browser
    ctx = b.new_context(viewport={"width": w, "height": h}, reduced_motion="reduce" if reduced else "no-preference")
    p = ctx.new_page()
    p.goto(url + query)
    p.wait_for_function("() => !!window.__monkeyEvents && !!window.__monkeyReady", timeout=30000)
    p.wait_for_timeout(600)
    return ctx, p


def test_main_menus_open_readable_and_close_back_to_their_button(browser):
    ctx, p = _page(browser)
    try:
        for btn, dlg, close in (("#settingsBtn", "#settings", "Escape"), ("#tasksBtn", "#tasksDlg", "#tasksDlg .taskstop button[aria-label=Close]")):
            p.click(btn)
            p.wait_for_function(OPEN, arg=dlg, timeout=10000)
            # readable fast: fully opaque well within the springy settle, and interactive (no inert, no pointer block)
            p.wait_for_timeout(160)
            op, pe = p.evaluate("s => { const c = getComputedStyle(document.querySelector(s)); return [Number(c.opacity), c.pointerEvents]; }", dlg)
            assert op > 0.95 and pe != "none", (dlg, op, pe)
            if close == "Escape":
                p.keyboard.press("Escape")
            else:
                p.click(close)
            assert p.evaluate(f"() => document.querySelector('{dlg}').open") is False      # logically closed at once
            p.wait_for_function(SHUT, arg=dlg, timeout=3000)                                 # really closed after the exit
            p.wait_for_function("id => document.activeElement && document.activeElement.id === id", arg=btn[1:], timeout=2000)
        # Today: a panel, not a dialog
        p.click("#todayBtn")
        p.wait_for_selector("#todayPanel .focustitle", timeout=10000)
        p.click("#todayBtn")
        p.wait_for_function("() => document.getElementById('today').hidden && !document.body.classList.contains('today-open')", timeout=3000)
        assert p.evaluate("() => getComputedStyle(document.getElementById('log')).display") != "none"
        # header cards: To-do and Homework pop out of their buttons and close with ✕
        for btn, sel in (("#todoBtn", ".card.todo"), ("#asgBtn", ".card.assign:not(.todo)")):
            p.click(btn)
            p.wait_for_selector(f"{sel} .asg-body, {sel} .todo-body", timeout=10000)
            p.click(f"{sel} > .close")
            p.wait_for_function("s => !document.querySelector(s)", arg=sel, timeout=3000)
        p.wait_for_timeout(700)
        left = [a for a in p.evaluate(RUNNING) if a.split("@")[0].startswith(("mm-", "m-shine", "m-ban", "m-bob", "m-swing"))]
        assert left == [], left                                                            # nothing left running
    finally:
        ctx.close()


def test_escape_and_rapid_toggling_never_leave_a_dialog_stuck(browser):
    ctx, p = _page(browser)
    try:
        p.click("#settingsBtn")
        p.wait_for_function(OPEN, arg="#settings", timeout=10000)
        # Escape twice in a row: the second one closes at once, mid-animation
        p.keyboard.press("Escape")
        p.keyboard.press("Escape")
        p.wait_for_function(SHUT, arg="#settings", timeout=1000)
        # Escape right after opening (the entrance still playing)
        p.click("#settingsBtn")
        p.wait_for_function("() => document.querySelector('#settings').hasAttribute('open')", timeout=10000)
        p.keyboard.press("Escape")
        p.wait_for_function(SHUT, arg="#settings", timeout=2000)
        # reopen while closing: ends open; close/open hammered: ends as the last call says
        p.click("#settingsBtn")
        p.wait_for_function(OPEN, arg="#settings", timeout=10000)
        p.evaluate("() => { const d = document.querySelector('#settings'); d.close(); d.showModal(); }")
        p.wait_for_timeout(600)
        assert p.evaluate(OPEN, "#settings")
        p.evaluate("() => { const d = document.querySelector('#settings'); for (let i = 0; i < 6; i++) { d.close(); d.showModal(); } d.close(); d.close(); }")
        p.wait_for_function(SHUT, arg="#settings", timeout=2000)
        p.wait_for_timeout(300)
        assert not p.evaluate("() => document.querySelector('#settings').hasAttribute('open')")
        # Tasks → Mailing lists: one dialog hands over to the other; only the new one ends open
        p.click("#tasksBtn")
        p.wait_for_function(OPEN, arg="#tasksDlg", timeout=10000)
        p.click("#tasksDlg >> text=Unsubscribe from lists")
        p.wait_for_function(OPEN, arg="#mailDlg", timeout=10000)
        p.wait_for_function(SHUT, arg="#tasksDlg", timeout=2000)
        p.keyboard.press("Escape")
        p.wait_for_function(SHUT, arg="#mailDlg", timeout=2000)
        # the page behind is usable again
        p.click("#todoBtn")
        p.wait_for_selector(".card.todo .todo-body", timeout=10000)
    finally:
        ctx.close()


def test_a_slow_menu_shows_a_skeleton_then_the_content(browser):
    ctx, p = _page(browser, "?demo&svg&slow=1200&slowonly=todo_list,dashboard,get_state")
    try:
        p.evaluate(SEEN)
        p.click("#todoBtn")
        box = p.wait_for_selector(".card .m-load", timeout=3000)          # the card is up at once, loading inside
        assert "Loading your to-do list" in box.inner_text()
        assert p.query_selector(".card .m-load .m-skel .m-sk-row") is not None   # the list's real layout
        assert p.query_selector(".card .m-load .m-art-bananas") is not None
        p.wait_for_selector(".card.todo .todo-body", timeout=10000)
        p.wait_for_timeout(500)
        assert p.query_selector(".card .m-load") is None and p.query_selector("#m-fx .m-load") is None
        assert p.evaluate("() => document.querySelectorAll('.card.todo').length") == 1   # filled the same card
        # Today, slow: a skeleton in the tab's layout, then the focus
        p.click("#todayBtn")
        p.wait_for_selector("#todayPanel .m-load .m-skel-tiles", timeout=3000)
        p.wait_for_selector("#todayPanel .focustitle", timeout=10000)
        # Settings, slow: opens at once with a skeleton, then the real sections
        p.click("#todayBtn")
        p.click("#settingsBtn")
        p.wait_for_selector("#settings[open] .m-load .m-skel-settings", timeout=3000)
        p.wait_for_selector("#settings .settingsnav", timeout=10000)
        p.wait_for_timeout(700)
        left = [a for a in p.evaluate(RUNNING) if a.split("@")[0].startswith(("m-shine", "m-ban", "m-bob", "m-swing", "m-pulse"))]
        assert left == [], left                                           # no loader animation once loaded
        assert p.evaluate("() => window.__loaders") >= 3
    finally:
        ctx.close()


def test_a_fast_load_shows_no_loader(browser):
    ctx, p = _page(browser)
    try:
        p.evaluate(SEEN)
        p.click("#todoBtn")
        p.wait_for_selector(".card.todo .todo-body", timeout=10000)
        p.click("#todayBtn")
        p.wait_for_selector("#todayPanel .focustitle", timeout=10000)
        p.wait_for_timeout(300)
        assert p.evaluate("() => window.__loaders") == 0
    finally:
        ctx.close()


def test_a_failed_load_offers_try_again(browser):
    ctx, p = _page(browser, "?demo&svg&slow=300&slowonly=todo_list&failonce=todo_list")
    try:
        p.click("#todoBtn")
        err = p.wait_for_selector(".card .m-load-error", timeout=5000)
        assert "Couldn't load your to-do list" in err.inner_text()
        assert p.evaluate("() => document.activeElement && document.activeElement.classList.contains('m-retry')")
        p.click(".card .m-load-error .m-retry")
        p.wait_for_selector(".card.todo .todo-body", timeout=10000)
        assert p.query_selector(".card .m-load-error") is None
    finally:
        ctx.close()


def test_reduced_motion_loaders_hold_still(browser):
    """OS reduce motion: the loader doesn't bounce, swing or shimmer; at most a slow opacity pulse."""
    ctx, p = _page(browser, "?demo&svg&slow=2500&slowonly=todo_list", reduced=True)
    try:
        p.click("#todoBtn")
        p.wait_for_selector(".card .m-load .m-skel", timeout=3000)
        p.wait_for_timeout(400)
        names = {a.split("@")[0] for a in p.evaluate(RUNNING)}
        assert not names & {"m-shine", "m-ban-hop", "m-bob", "m-swing", "m-shadow"}, names
        assert names <= {"m-pulse"}, names
    finally:
        ctx.close()

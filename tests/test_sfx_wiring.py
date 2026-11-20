"""The interface sounds fire at the right moments in the real UI (browser demo mode), and the Sound Lab switch works.

Records every cue the sound engine is asked to play (the engine's own play(), so cooldowns and juice rules still
apply downstream). Needs the built UI (ui/dist) and Playwright's Chromium; skipped otherwise.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_m4_avatar import _serve  # noqa: E402

try:
    from tools.automation_eval import browser_path
except Exception:  # pragma: no cover
    browser_path = None


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright
    from pathlib import Path

    if browser_path is None or browser_path() is None or not (Path(__file__).resolve().parents[1] / "ui" / "dist" / "index.html").exists():
        pytest.skip("needs Chromium and a built UI (npm run build)")       # same rule as the other browser tests
    srv = _serve()
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=browser_path(),
                               args=["--use-gl=angle", "--use-angle=swiftshader", "--autoplay-policy=no-user-gesture-required"])
        p = b.new_page(viewport={"width": 1280, "height": 800})
        p.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo")
        p.wait_for_function("() => window.__monkeyReady && window.__monkeyAvatarObj", timeout=60000)
        p.evaluate("""() => { const s = window.__monkeyAvatarObj.sfx; window.__played = [];
            const orig = s.play.bind(s); s.play = (cue, i) => { window.__played.push(cue); return orig(cue, i); }; }""")
        yield p
        b.close()
    srv.shutdown()


def played(p, clear=True):
    out = p.evaluate("() => window.__played.slice()")
    if clear:
        p.evaluate("() => { window.__played.length = 0; }")
    return out


def test_opening_and_closing_settings_sounds_like_a_dialog(page):
    played(page)
    page.click("#settingsBtn")
    page.wait_for_function("() => document.querySelector('#settings').open")
    page.wait_for_timeout(150)
    got = played(page)
    assert got[:1] == ["ui_click"] and "ui_open" in got
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    assert "ui_close" in played(page)


def test_results_and_problems_have_their_own_sound(page):
    played(page)
    page.evaluate("() => window.__monkeyEvents([['error', {message: 'test problem'}]])")
    assert "ui_error" in played(page)
    page.evaluate("() => window.__monkeyEvents([['update', {status: 'ready', available: '9.9.9'}]])")
    assert "notify" in played(page)


def test_sound_lab_takes_play_alone_and_the_version_switch_applies(page):
    page.click("#settingsBtn")
    page.wait_for_function("() => document.querySelector('#settings').open")
    page.wait_for_function("() => document.querySelectorAll('.soundlab .variant').length > 0", timeout=20000)
    page.locator("summary", has_text="Sound Lab").click()                   # the Lab is a collapsed section
    played(page)
    page.locator(".soundlab .take").first.dispatch_event("pointerdown")      # a take button: no click sound over it
    assert "ui_click" not in played(page)
    row = page.locator(".soundlab .cue", has=page.locator(".name", has_text="ui click"))
    row.locator(".variant", has_text="B").click()
    page.wait_for_function("() => (window.__monkeyAvatarObj.sfx.cues().ui_click || [])[0]?.includes('candidates/ui_click-B')")
    row = page.locator(".soundlab .cue", has=page.locator(".name", has_text="ui click"))
    row.locator(".variant", has_text="Now").click()
    page.wait_for_function("() => !(window.__monkeyAvatarObj.sfx.cues().ui_click || [])[0]?.includes('candidates')")
    page.keyboard.press("Escape")

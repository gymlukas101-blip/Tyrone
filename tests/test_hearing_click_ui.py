"""Clicking the monkey in the real UI (demo mode, no Python): hearing on -> he listens with a whole-body pop; click
again -> hearing off with the deflate and a badge; the badge (or another click) turns it back on. Both the 3D
monkey (software GL) and the SVG fallback."""
from __future__ import annotations

import os

import pytest

from tests.test_m4_avatar import DIST, _serve

SHOTS = os.environ.get("MONKEY_HEARING_SHOTS")


@pytest.fixture(scope="module")
def pw_browser():
    pytest.importorskip("playwright")
    from tools.automation_eval import browser_path

    if browser_path() is None or not DIST.is_file():
        pytest.skip("needs Chromium and a built UI (npm run build)")
    from playwright.sync_api import sync_playwright

    srv = _serve()
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=browser_path(), args=["--use-gl=angle", "--use-angle=swiftshader"])
        yield b, f"http://127.0.0.1:{srv.server_address[1]}/index.html"
        b.close()
    srv.shutdown()


def _open(pw_browser, query):
    b, url = pw_browser
    p = b.new_page(viewport={"width": 1280, "height": 900})
    p.set_default_timeout(30000)
    p.goto(url + query)
    p.wait_for_function("() => !!window.__monkeyEvents && !!window.__monkeyReady && window.__monkeyAvatar?.ready",
                        timeout=90000)
    return p


def _center(p):
    box = p.locator("#avatar").bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.55


def _shot(p, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        p.screenshot(path=os.path.join(SHOTS, f"{name}.png"), timeout=60000)


def test_click_the_3d_monkey_toggles_hearing_with_a_body_pop(pw_browser):
    p = _open(pw_browser, "?demo")
    if p.evaluate("() => window.__monkeyAvatar.kind") != "3d":
        pytest.skip("no WebGL here: the SVG test covers the click")
    x, y = _center(p)
    assert p.evaluate("([x, y]) => window.__monkeyAvatarObj.hitTest(x, y)", [x, y])
    box = p.locator("#avatar").bounding_box()
    assert not p.evaluate("([x, y]) => window.__monkeyAvatarObj.hitTest(x, y)", [box["x"] + 3, box["y"] + 3])  # jungle
    p.mouse.click(x, y)
    p.wait_for_function("() => window.__monkeyAvatarObj.popLog.join() === 'on'")   # the whole-body pop played
    assert p.evaluate("() => document.querySelector('#stateLabel').textContent") != ""
    _shot(p, "hearing-on-3d")
    p.wait_for_timeout(700)
    p.mouse.click(x, y)                                                 # while listening -> off
    p.wait_for_selector("#hearBadge:not([hidden])")
    p.wait_for_function("() => window.__monkeyAvatarObj.popLog.join() === 'on,off'")
    _shot(p, "hearing-off-3d")
    p.click("#hearBadge")                                               # the badge turns it back on
    p.wait_for_selector("#hearBadge", state="hidden")
    p.wait_for_function("() => window.__monkeyAvatarObj.pop === null", timeout=15000)
    sy = p.evaluate("() => { const a = window.__monkeyAvatarObj; return a.model.scale.y / a.popBase.scale.y; }")
    assert abs(sy - 1) < 1e-6                                           # settles back exactly
    p.close()


def test_svg_monkey_and_keyboard(pw_browser):
    p = _open(pw_browser, "?demo&svg")
    p.focus("#avatar")
    p.keyboard.press("Enter")
    p.wait_for_function("() => document.querySelector('#avatar').classList.contains('hear-on')")
    p.wait_for_timeout(600)
    p.keyboard.press(" ")
    p.wait_for_selector("#hearBadge:not([hidden])")
    assert p.get_attribute("#avatar", "role") == "button"
    p.close()

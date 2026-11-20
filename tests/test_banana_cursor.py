"""The banana cursor in Monkey's real click path (headless Chromium + the local cursor lab).

What is checked (functional, not visual fidelity — see docs/cursor/README.md for the visual comparison):
  * the action really executes (the page counted a trusted click on the right control),
  * the banana's tip is drawn on exactly the viewport point the click landed on, at device-pixel ratios 1–2 and with
    page zoom and scrolling,
  * the ripple starts at that point; hover lights up only for accessibility-interactive controls,
  * busy shows while a slow page loads, the cursor travel budget is small, rapid clicks don't leak effects,
  * Python and JS agree on travel time; reduced motion jumps instead of flying.
"""
from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("playwright.sync_api")

from monkey.automation.cursor_events import BrowserCursor, CursorSettings, travel_ms
from monkey.automation.permissions import Action, PermissionGate
from tools.automation_eval import browser_path


def _launchable() -> bool:
    import sys

    return bool(browser_path()) or sys.platform == "win32"


pytestmark = pytest.mark.skipif(not _launchable(), reason="no Chromium/Edge for Playwright here")


@pytest.fixture(scope="module")
def course():
    from monkey.automation.democourse import DemoCourse

    c = DemoCourse(media_seconds=1).start()
    yield c
    c.stop()


def open_session(course, dsf: float = 1.0, motion: str = "full", events=None):
    from monkey.automation.browser import BrowserSession

    tmp = Path(tempfile.mkdtemp(prefix="cursor-"))
    sleeps: list = []
    cur = BrowserCursor(CursorSettings(motion=motion), sleep=lambda s: sleeps.append(s),
                        on_event=(events.append if events is not None else None))
    s = BrowserSession(tmp / "p", PermissionGate(), headless=True, executable_path=browser_path(),
                       allowed_domains=["127.0.0.1"], cursor=cur)
    s.start()
    if dsf != 1.0:                                   # emulate a scaled monitor (125 %, 150 %, 200 %)
        cdp = s.context.new_cdp_session(s.page)
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 800, "deviceScaleFactor": dsf,
                                                       "mobile": False})
    scope = NS(id="t", mode="managed_browser", allowed_domains=["127.0.0.1"], confirm_medium=False)
    s.act(scope, Action("navigate", url=course.url + "cursor-lab"))
    return s, cur, scope, sleeps, tmp


def element(s, role, name):
    return next(e for e in s.observe().elements if e.role == role and e.name == name)


def last_click(s):
    return s.page.evaluate("() => window.__clicks[window.__clicks.length - 1]")


@pytest.mark.parametrize("dsf,zoom", [(1.0, 1.0), (1.25, 1.0), (1.5, 1.0), (2.0, 1.0), (1.5, 1.5)])
def test_tip_and_ripple_sit_exactly_on_the_real_click(course, dsf, zoom):
    s, cur, scope, sleeps, tmp = open_session(course, dsf)
    try:
        if zoom != 1.0:
            s.page.evaluate(f"() => document.body.style.zoom = '{zoom}'")      # page zoom changes the layout
        r = s.act(scope, Action("click"), element(s, "button", "Save draft"))
        assert r.ok, r.detail
        click = last_click(s)
        assert click["id"] == "b1" and click["trusted"]                         # the action really executed
        tip = cur.tip()
        assert math.hypot(tip["x"] - click["x"], tip["y"] - click["y"]) <= 1.0, (tip, click)
        dbg = s.page.evaluate("() => window.__monkeyCursor.debug()")
        rip = dbg["lastRipple"]
        assert math.hypot(rip["x"] - click["x"], rip["y"] - click["y"]) <= 1.0, (rip, click)
        assert "hover" in dbg["classes"]                                        # a real button: glow on
    finally:
        s.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_alignment_survives_scrolling_and_a_second_page(course):
    s, cur, scope, sleeps, tmp = open_session(course)
    try:
        cur.move_to(40, 40)                                                     # first appearance: a jump
        assert cur.last_ms["travel"] == 0
        r = s.act(scope, Action("click"), element(s, "button", "Far down"))      # 900 px below: scrolled into view
        assert r.ok
        click = last_click(s)
        assert click["id"] == "b2" and s.page.evaluate("() => window.scrollY") > 300
        tip = cur.tip()
        assert abs(tip["x"] - click["x"]) <= 1 and abs(tip["y"] - click["y"]) <= 1
        assert 0 < cur.last_ms["travel"] <= 260 and cur.last_ms["press"] <= 90
        assert sum(sleeps) <= 0.36                                              # the whole visual budget per click
    finally:
        s.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_hover_only_for_interactive_controls(course):
    events: list = []
    s, cur, scope, _, tmp = open_session(course, events=events)
    try:
        assert cur.hover("button") and cur.hover("link") and cur.hover("textbox") and cur.hover("slider")
        assert not cur.hover("generic") and not cur.hover("paragraph") and not cur.hover("")
        # The green "Looks like a button" div has no role: it isn't in the outline as a button at all.
        names = {(e.role, e.name) for e in s.observe().elements}
        assert ("button", "Looks like a button") not in names
        r = s.act(scope, Action("type", text="Jordan"), element(s, "textbox", "Your name"))
        assert r.ok and s.page.input_value("#t1") == "Jordan"
        kinds = [e["kind"] for e in events]
        assert "move" in kinds and any(e["kind"] == "state" and e["state"] == "typing" for e in events)
        assert all(e["space"] == "viewport" for e in events)                    # browser pointer, never "screen"
    finally:
        s.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_busy_while_a_slow_page_loads_then_the_cursor_follows_to_the_new_page(course):
    events: list = []
    s, cur, scope, _, tmp = open_session(course, events=events)
    try:
        r = s.act(scope, Action("navigate", url=course.url + "cursor-lab/slow"))
        assert r.ok and "loaded" in s.page.inner_text("h1")
        assert any(e["kind"] == "state" and e["state"] == "busy" for e in events)
        cur.set_state("idle")
        r = s.act(scope, Action("click"), element(s, "button", "Save draft"))
        assert r.ok and last_click(s)["id"] == "b1"
        assert cur.tip()["visible"]
    finally:
        s.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_rapid_and_double_clicks_dont_break_or_leak(course):
    s, cur, scope, _, tmp = open_session(course)
    try:
        b = element(s, "button", "Save draft")
        for _ in range(6):
            assert s.act(scope, Action("click"), b).ok
        assert s.page.evaluate("() => window.__counts.b1") == 6                 # every click happened, once each
        for _ in range(5):
            cur.press()
            cur.release()
        s.page.wait_for_timeout(700)
        dbg = s.page.evaluate("() => window.__monkeyCursor.debug()")
        assert dbg["fxNodes"] == 0 and dbg["ripples"] == 11                     # effects cleaned up
    finally:
        s.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_reduced_motion_jumps_and_states_render(course):
    s, cur, scope, sleeps, tmp = open_session(course, motion="reduced")
    try:
        assert s.act(scope, Action("click"), element(s, "link", "Read more")).ok
        assert cur.last_ms["travel"] == 0
        for st, badge in (("waiting", "✋ your turn"), ("paused", "❚❚"), ("blocked", "!"), ("error", "✖")):
            cur.set_state(st)
            assert s.page.evaluate("() => window.__monkeyCursor.debug().badge") == badge
        cur.set_state("busy")
        assert "busy" in s.page.evaluate("() => window.__monkeyCursor.debug().classes")
        cur.hide()
        assert not s.page.evaluate("() => window.__monkeyCursor.debug().visible")
    finally:
        s.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_python_and_js_agree_on_travel_time(course):
    s, cur, scope, _, tmp = open_session(course)
    try:
        for d in (0, 5, 40, 200, 900, 3000):
            assert s.page.evaluate(f"() => MonkeyBananaCursor.travelMs({d}, 'full')") == travel_ms(d)
        assert travel_ms(800, "reduced") == 0
    finally:
        s.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_cursor_is_invisible_to_the_page_and_to_the_model(course):
    """The layer takes no clicks and is hidden from the accessibility outline Monkey/Claude reads."""
    s, cur, scope, _, tmp = open_session(course)
    try:
        cur.move_to(30, 30)
        assert "monkey-cursor" not in s.page.aria_snapshot(mode="ai")
        hit = s.page.evaluate("() => document.elementFromPoint(30, 30).tagName")
        assert hit != "MONKEY-CURSOR"
    finally:
        s.close()
        shutil.rmtree(tmp, ignore_errors=True)

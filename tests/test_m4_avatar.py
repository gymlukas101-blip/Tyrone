"""Milestone 4: one avatar-state rule in both windows (D7), checked in the real built UI."""
from __future__ import annotations

from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parents[1] / "ui" / "dist" / "index.html"

TASK = {"id": "t1", "objective": "Watch module 2", "state": "RUNNING", "steps": [], "log": [], "allowed_domains": ["*"]}


def _serve():
    """The built UI over http (file:// blocks fetching the 3D model)."""
    import functools
    import http.server
    import threading

    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST.parent))
    h.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _page(pw, query):
    from tools.automation_eval import browser_path

    srv = _serve()
    b = pw.chromium.launch(executable_path=browser_path(), args=["--use-gl=angle", "--use-angle=swiftshader"])
    p = b.new_page()
    p.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html" + query)
    p.wait_for_function("() => !!window.__monkeyEvents && !!window.__monkeyResolver && "
                        "(window.__monkeyReady || new URLSearchParams(location.search).has('overlay'))", timeout=20000)
    return b, p


def _shown(p, events, wait_ms=0, expect=None):
    """Send events; return what the avatar shows. With `expect`, wait up to 3 s for it (slow CI machines)."""
    p.evaluate("ev => window.__monkeyEvents(ev)", events)
    if wait_ms:
        p.wait_for_timeout(wait_ms)
    if expect is not None:
        try:
            p.wait_for_function("s => window.__monkeyResolver.shown === s", arg=expect, timeout=3000)
        except Exception:  # noqa: BLE001 - fall through and report what it shows
            pass
    return p.evaluate("() => window.__monkeyResolver.shown")


@pytest.mark.parametrize("query", ["?demo", "?demo&overlay"])
def test_voice_states_show_during_a_task_in_both_windows(query):
    pytest.importorskip("playwright")
    from tools.automation_eval import browser_path

    if browser_path() is None or not DIST.is_file():
        pytest.skip("needs Chromium and a built UI (npm run build)")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b, p = _page(pw, query)
        try:
            assert _shown(p, [["automation", {"task": TASK, "avatar": "working", "control": False}]], expect="thinking") == "thinking"
            assert _shown(p, [["state", {"state": "listening"}]], expect="listening") == "listening"        # D7: was ignored in the companion
            assert _shown(p, [["state", {"state": "speaking"}]], expect="speaking") == "speaking"
            assert _shown(p, [["state", {"state": "idle"}]], expect="thinking") == "thinking"   # back to the task
            needs = {**TASK, "state": "NEEDS_INPUT"}
            assert _shown(p, [["automation", {"task": needs, "avatar": "help", "control": False}]], expect="listening") == "listening"
            done = {**TASK, "state": "COMPLETED"}
            assert _shown(p, [["automation", {"task": done, "avatar": "celebrate", "control": False}]],
                          expect="idle") == "idle"
            # the avatar element itself carries the state that's drawn
            assert p.evaluate("() => document.querySelector('[data-state]')?.dataset.state") == "idle"
        finally:
            b.close()


def test_ui_bus_sends_silence_once_not_thirty_times_a_second():
    import time

    from monkey.app import UIBus

    sent = []

    class W:
        def evaluate_js(self, js):
            sent.append(js)
    bus = UIBus()
    bus.window = W()
    for _ in range(30):                       # half a second of the speaker reporting silence
        bus.level(0.0)
        time.sleep(1 / 60)
    time.sleep(0.1)
    assert sent == []                         # was ~15 calls into both windows while idle
    for v in (0.2, 0.5, 0.0, 0.0, 0.0):
        bus.level(v)
        time.sleep(0.05)
    time.sleep(0.1)
    levels = [js for js in sent if '"level"' in js]
    assert len(levels) == 3                   # 0.2, 0.5, then silence once


def test_idle_avatar_draws_at_30_fps_and_full_rate_when_busy():
    pytest.importorskip("playwright")
    from tools.automation_eval import browser_path

    if browser_path() is None or not DIST.is_file():
        pytest.skip("needs Chromium and a built UI (npm run build)")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b, p = _page(pw, "?demo")
        try:
            try:
                p.wait_for_function("() => window.__monkeyAvatarObj && window.__monkeyAvatarObj.stats.frames > 5",
                                    timeout=40000)
            except Exception:  # noqa: BLE001
                pytest.skip("the 3D avatar didn't render in this browser (no WebGL)")
            # Software rendering here is GPU-bound (a few fps), so check which tier the loop chose and its target
            # rate; real frame rates per tier are measured on the Dell (docs/LAG-AUDIT.md).
            p.wait_for_timeout(2500)                                  # past the 2 s "you moved the mouse" window
            samples = []
            for _ in range(24):                                     # 6 s: idle fidgets come and go
                samples.append(p.evaluate("() => ({...window.__monkeyAvatarObj.stats})"))
                p.wait_for_timeout(250)
            p.mouse.move(200, 200)                                     # idle, then you move the mouse
            p.wait_for_timeout(300)
            cursor = p.evaluate("() => ({...window.__monkeyAvatarObj.stats})")
            p.evaluate("() => window.__monkeyEvents([['state', {state: 'speaking'}]])")
            p.wait_for_timeout(300)
            busy = p.evaluate("() => ({...window.__monkeyAvatarObj.stats})")
        finally:
            b.close()
    idle = [x for x in samples if x["tier"] == "idle"]
    assert idle and all(x["fps"] == 30 for x in idle), samples
    assert all(x["tier"] == "idle" or x["why"] in ("emote", "transition", "effects") for x in samples), samples
    assert busy["tier"] == "full" and busy["fps"] == 0, busy                  # 0 = the display's own rate             # (why: speaking, or a fidget at that moment)
    assert cursor["tier"] == "full" and cursor["why"] in ("cursor", "emote"), cursor   # follows your cursor smoothly


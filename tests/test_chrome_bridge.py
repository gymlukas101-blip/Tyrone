"""Monkey for Chrome: the extension (really loaded in Chromium, playing the user's own Chrome) + the local bridge +
Monkey's normal BrowserSession/TaskManager. Skipped where Playwright/Chromium aren't installed."""
from __future__ import annotations

import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("websockets")

from monkey.automation.chrome_bridge import ChromeBridge, new_token, pairing_code, proof  # noqa: E402
from tools.automation_eval import browser_path  # noqa: E402

needs_chromium = pytest.mark.skipif(browser_path() is None, reason="no Chromium build here to load the extension into")

EXT = str(Path(__file__).resolve().parents[1] / "extension" / "chrome")


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class UserChrome:
    """A real Chromium with the extension installed, standing in for the owner's Chrome. Runs on its own thread
    (Playwright's sync API is thread-bound), shares one tab with Monkey like the popup button does."""

    def __init__(self, code: str | None, share: bool = True, start_url: str = "about:blank"):
        self.code, self.share, self.start_url = code, share, start_url
        self.ready, self.stop, self.info = threading.Event(), threading.Event(), {}
        self.th = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        from playwright.sync_api import sync_playwright

        from tools.automation_eval import browser_path

        with sync_playwright() as pw, tempfile.TemporaryDirectory() as d:
            ctx = pw.chromium.launch_persistent_context(
                d, headless=True, executable_path=browser_path(), ignore_default_args=["--disable-extensions"],
                args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                if self.start_url != "about:blank":
                    page.goto(self.start_url)
                sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker",
                                                                                            timeout=15000)
                self.info["extension_id"] = sw.url.split("/")[2]
                if self.code:
                    sw.evaluate(f"monkey.pair({self.code!r})")
                tabs = sw.evaluate("chrome.tabs.query({}).then(t => t.map(x => [x.id, x.url]))")
                if self.share:
                    sw.evaluate(f"monkey.share({tabs[0][0]})")
                self.info["other_tab"] = ctx.new_page()                 # a tab the user did NOT share
                self.info["other_tab"].set_content("<title>Bank</title><button>Transfer</button>")
                self.ready.set()
                while not self.stop.is_set():
                    time.sleep(0.2)
                self.info["status"] = sw.evaluate("monkey.status()")
                self.info["other_title"] = self.info.pop("other_tab").title()
                self.info["pages_open"] = len(ctx.pages)
            finally:
                ctx.close()

    def __enter__(self):
        self.th.start()
        assert self.ready.wait(40), "user Chrome didn't start"
        return self

    def __exit__(self, *a):
        self.stop.set()
        self.th.join(30)


@needs_chromium
def test_extension_id_matches_the_bridge_and_pairing_is_mutual():
    tok = new_token()
    bridge = ChromeBridge(tok, port=_port()).start()
    try:
        with UserChrome(pairing_code(tok, bridge.port)) as u:
            from monkey.automation.chrome_bridge import EXTENSION_ID

            assert u.info["extension_id"] == EXTENSION_ID
            assert bridge.ready.wait(15)
    finally:
        bridge.stop()


@needs_chromium
def test_wrong_pairing_code_never_connects():
    bridge = ChromeBridge(new_token(), port=_port()).start()
    try:
        with UserChrome(pairing_code(new_token(), bridge.port)):
            assert not bridge.ready.wait(6)
            assert "pairing" in bridge.error
    finally:
        bridge.stop()


def test_web_pages_and_unknown_origins_are_refused():
    import asyncio

    from websockets.asyncio.client import connect

    tok = new_token()
    bridge = ChromeBridge(tok, port=_port()).start()

    async def try_open(path, origin):
        try:
            async with connect(f"ws://127.0.0.1:{bridge.port}{path}", origin=origin, open_timeout=3):
                return True
        except Exception:  # noqa: BLE001
            return False
    try:
        assert not asyncio.run(try_open("/extension", "https://evil.example"))
        assert not asyncio.run(try_open("/cdp/guess", None))
        assert not asyncio.run(try_open(bridge.cdp_url.split(str(bridge.port))[1], "https://evil.example"))
        assert proof("t", "ext|n") != proof("t", "srv|n")
    finally:
        bridge.stop()


@needs_chromium
def test_course_runs_in_the_users_own_chrome_through_the_extension():
    """The whole course (Canvas-style pages, an embedded cross-origin player, the quiz page and an SSO redirect)
    through the user's shared tab: Monkey never launches a browser, other tabs stay untouched."""
    from tools.automation_eval import run_one

    tok = new_token()
    bridge = ChromeBridge(tok, port=_port()).start()
    try:
        with UserChrome(pairing_code(tok, bridge.port)) as u:
            assert bridge.ready.wait(15)
            r = run_one({"canvas", "embed", "quizpage", "sso"}, media=1.0, seed=7, timeout=300, relay=True,
                        cdp_endpoint=bridge.cdp_url, any_site=True)
            assert r["verified_success"], r
            assert not r["unauthorized"]
    finally:
        bridge.stop()
    assert u.info["other_title"] == "Bank"                              # the unshared tab was never touched
    assert u.info["pages_open"] >= 2                                    # Monkey closed none of your tabs

"""Google sign-in that explains itself, calendar feed wiring, and the in-app routing benchmark."""
import json
import time
from types import SimpleNamespace as NS

import pytest

from monkey import app as app_mod, keys
from monkey.brain import bench_routing as B
from monkey.integrations import google as G

DESKTOP = json.dumps({"installed": {"client_id": "x.apps.googleusercontent.com", "client_secret": "s",
                                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                    "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": ["http://localhost"]}})


def test_validate_client():
    assert "installed" in G.validate_client(DESKTOP)
    for bad, word in [("", "Load your Google setup file"), ("{nope", "isn't the Google setup file"),
                      (json.dumps({"web": {"client_id": "a"}}), "not the right Google file"),
                      (json.dumps({"installed": {}}), "looks incomplete")]:
        with pytest.raises(ValueError) as e:
            G.validate_client(bad)
        assert word in str(e.value)


def test_error_messages_say_what_to_do():
    assert "Test users" in G.explain_sign_in_error(RuntimeError("access_denied"))
    assert "timed out" in G.explain_sign_in_error(TimeoutError("timed out"))
    assert "Desktop app" in G.explain_sign_in_error(RuntimeError("redirect_uri_mismatch"))


class FakeFlow:
    """Behaves like InstalledAppFlow.run_local_server: opens the browser via webbrowser.get(browser).open(url)."""
    calls = []
    gate = None

    @classmethod
    def from_client_config(cls, info, scopes):
        return cls()

    def run_local_server(self, **kw):
        import webbrowser

        FakeFlow.calls.append(kw)
        webbrowser.get(kw.get("browser")).open("https://accounts.google.com/o/oauth2/auth?x=1", new=1, autoraise=True)
        if FakeFlow.gate is not None:
            FakeFlow.gate.wait(2)                                      # "waiting for the user in the browser"
        return NS(token="t", to_json=lambda: '{"token": "t"}')


def test_sign_in_opens_browser_once_without_touching_webbrowser(monkeypatch):
    """Regression (v0.3.33): patching webbrowser.get made webbrowser.open recurse, so nothing ever opened."""
    flowmod = pytest.importorskip("google_auth_oauthlib.flow")      # desktop extra: installed in the Windows job
    import webbrowser

    from monkey import links

    monkeypatch.setattr(flowmod, "InstalledAppFlow", FakeFlow)
    launched = []
    monkeypatch.setattr(links, "launch_url", lambda u: launched.append(u) or True)
    real_get, real_open = webbrowser.get, webbrowser.open
    keys.set("google_client", DESKTOP)
    urls = []
    acct = G.GoogleAuth().sign_in(on_url=urls.append)                # would raise/hang on recursion before
    assert launched == ["https://accounts.google.com/o/oauth2/auth?x=1"] and urls == launched
    assert FakeFlow.calls[-1]["browser"] == G.SIGNIN_BROWSER and FakeFlow.calls[-1]["timeout_seconds"] == 300
    assert webbrowser.get is real_get and webbrowser.open is real_open
    tok = json.loads(G.get_token("gmail"))                               # one token per account (multi-account)
    assert acct == "gmail" and tok["token"] == "t"
    assert "https://www.googleapis.com/auth/gmail.readonly" in tok["granted_scopes"]  # what Google granted (refresh keeps it)


def test_other_links_still_open_while_sign_in_waits(monkeypatch, tmp_path):
    """The 'Open Google sign-in' link (Api.open_url -> MonkeyApp._open_url) must work during the wait."""
    import threading

    flowmod = pytest.importorskip("google_auth_oauthlib.flow")
    from monkey import links

    monkeypatch.setattr(flowmod, "InstalledAppFlow", FakeFlow)
    launched = []
    monkeypatch.setattr(links, "launch_url", lambda u: launched.append(u) or True)
    keys.set("google_client", DESKTOP)
    FakeFlow.gate = threading.Event()
    t = threading.Thread(target=lambda: G.GoogleAuth().sign_in(on_url=lambda u: None), daemon=True)
    t.start()
    time.sleep(0.2)
    app_mod.MonkeyApp._open_url("https://accounts.google.com/o/oauth2/auth?x=1")   # the link in Settings
    FakeFlow.gate.set()
    t.join(3)
    FakeFlow.gate = None
    assert launched.count("https://accounts.google.com/o/oauth2/auth?x=1") == 2      # auto-open + the link


def test_launch_url_only_http_and_uses_startfile_on_windows(monkeypatch):
    from monkey import links

    assert links.launch_url("javascript:alert(1)") is False and links.launch_url("file:///C:/x") is False
    called = []
    monkeypatch.setattr(links.sys, "platform", "win32")
    monkeypatch.setattr(links.os, "startfile", lambda u: called.append(u), raising=False)
    assert links.launch_url("https://example.com") is True and called == ["https://example.com"]


@pytest.fixture
def mk(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    a = app_mod.MonkeyApp(tmp_path / "Monkey", headless=True)
    events = []
    a.ui.emit = lambda name, p=None: events.append((name, p))
    return a, app_mod.Api(a), events


def test_api_sign_in_without_client_explains(mk):
    a, api, events = mk
    keys.delete("google_client")
    r = api.google_sign_in()
    assert not r["ok"] and r.get("needs_client") and "Google setup file" in r["error"]


def test_api_sign_in_runs_in_background_and_reports(mk, monkeypatch):
    a, api, events = mk
    keys.set("google_client", DESKTOP)

    def fake_sign_in(on_url=None, timeout_s=300):
        on_url("https://accounts.google.com/x")
        time.sleep(0.2)
        raise RuntimeError("Google blocked the sign-in. add your Google account under Test users")

    monkeypatch.setattr(a.google, "sign_in", fake_sign_in)
    assert api.google_sign_in() == {"ok": True, "started": True}
    assert api.google_sign_in()["ok"] is False                       # second click while waiting
    time.sleep(0.5)
    stages = [p["stage"] for n, p in events if n == "google"]
    assert stages == ["opening", "error"] and "Test users" in events[-1][1]["message"]


def test_paste_web_client_is_rejected(mk):
    a, api, events = mk
    r = api.save_key("google_client", json.dumps({"web": {"client_id": "a"}}))
    assert not r["ok"] and "Desktop app" in r["error"]


def test_calendar_feed_is_a_calendar_not_canvas(mk, monkeypatch):
    a, api, events = mk
    assert a.ics_calendar not in a._calendars()
    keys.set("calendar_ics", "https://calendar.google.com/calendar/ical/x/private-abc/basic.ics")
    assert a.ics_calendar in a._calendars() and a.canvas not in a._calendars()
    assert api.save_key("calendar_ics", "not a link")["ok"] is False


def test_benchmark_live_with_fake_classifier(monkeypatch):
    from monkey.brain import router

    def fake(client, text):
        return ("research" if "compare" in text else "general", 3, False, "fake",
                NS(input_tokens=200, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0,
                   server_tool_use=None))

    monkeypatch.setattr(router, "classify_with_haiku", fake)
    seen = []
    res = B.live(None, on_progress=lambda i, n, t: seen.append(i), record=lambda u: seen.append("rec"))
    assert res["classified"] == 14 and 0 <= res["accuracy"] <= 1 and res["usd_total"] > 0
    assert seen.count("rec") == 14 and res["latency_p50_s"] is not None
    assert "Classifier:" in B.summary_text({"offline": B.offline(), "live": res})


def test_benchmark_api_needs_key(mk, monkeypatch):
    a, api, events = mk
    monkeypatch.setattr(a, "_ensure_client", lambda: None)
    assert "Anthropic key" in api.routing_benchmark()["error"]


class BlockedFlow:
    """Like run_local_server when Google shows "Access blocked": it never redirects back, so the local listener
    waits. A real localhost listener, so cancel() is tested end to end."""
    @classmethod
    def from_client_config(cls, info, scopes):
        return cls()

    def run_local_server(self, **kw):
        import webbrowser
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from urllib.parse import parse_qs, quote, urlparse

        got = {}

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                got.update(parse_qs(urlparse(self.path).query))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = HTTPServer(("localhost", 0), H)
        srv.timeout = 5
        redirect = f"http://localhost:{srv.server_port}/"
        webbrowser.get(kw.get("browser")).open(
            f"https://accounts.google.com/o/oauth2/auth?redirect_uri={quote(redirect, safe='')}&state=st8", new=1)
        srv.handle_request()
        srv.server_close()
        if got.get("error") == ["access_denied"] and got.get("state") == ["st8"]:
            raise RuntimeError("(access_denied) ")
        raise TimeoutError("timed out")


def test_cancel_unblocks_a_sign_in_google_never_returns_from(monkeypatch):
    import threading

    flowmod = pytest.importorskip("google_auth_oauthlib.flow")
    from monkey import links

    monkeypatch.setattr(flowmod, "InstalledAppFlow", BlockedFlow)
    monkeypatch.setattr(links, "launch_url", lambda u: True)
    keys.set("google_client", DESKTOP)
    auth, result = G.GoogleAuth(), {}

    def run():
        try:
            auth.sign_in(on_url=lambda u: None)
        except Exception as exc:  # noqa: BLE001
            result["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    for _ in range(50):
        if auth._auth_url:
            break
        time.sleep(0.05)
    started = time.monotonic()
    assert auth.cancel() is True
    t.join(5)
    assert not t.is_alive() and time.monotonic() - started < 3
    assert isinstance(result["exc"], G.SignInCancelled)


def test_cancel_only_talks_to_localhost():
    auth = G.GoogleAuth()
    auth._auth_url = "https://accounts.google.com/o/oauth2/auth?redirect_uri=https%3A%2F%2Fevil.example%2F&state=x"
    assert auth.cancel() is False
    assert G.GoogleAuth().cancel() is False            # nothing waiting


def test_api_reports_cancelled(mk, monkeypatch):
    a, api, events = mk
    keys.set("google_client", DESKTOP)

    def fake_sign_in(on_url=None, timeout_s=300):
        on_url("https://accounts.google.com/x")
        raise G.SignInCancelled("Sign-in cancelled.")

    monkeypatch.setattr(a.google, "sign_in", fake_sign_in)
    api.google_sign_in()
    time.sleep(0.3)
    assert [p["stage"] for n, p in events if n == "google"] == ["opening", "cancelled"]


def test_expired_sign_in_is_cleared_with_a_clear_message(monkeypatch):
    pytest.importorskip("google.oauth2.credentials")
    from google.auth.exceptions import RefreshError
    from google.oauth2 import credentials as C

    class Dead:
        valid, refresh_token = False, "r"

        def refresh(self, req):
            raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(C.Credentials, "from_authorized_user_info", classmethod(lambda cls, info, scopes: Dead()))
    keys.set("google_token", '{"refresh_token": "r"}')
    with pytest.raises(RuntimeError) as e:
        G.GoogleAuth().credentials()
    assert "Sign in again" in str(e.value) and "Publish app" in str(e.value)
    assert not keys.get("google_token") and G.account_ids() == []     # moved to the account list, then cleared


def test_access_blocked_message_points_to_publish():
    msg = G.explain_sign_in_error(RuntimeError("(access_denied)"))
    assert "Publish app" in msg and "Test users" in msg

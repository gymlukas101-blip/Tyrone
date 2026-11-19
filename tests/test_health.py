"""Check everything: every area reports, one broken check can't stop the rest, and the report has no secrets."""
from __future__ import annotations

import subprocess
import time
from types import SimpleNamespace as NS

import pytest

from monkey import app as app_mod, health as H, keys
from monkey.routines import scheduler

SECRET = "sk-ant-api03-SUPERSECRETVALUE-abcdefghijklmnop"
TOKEN = '{"token": "ya29.SECRETTOKENabcdefghijklmnopqrstuvwxyz0123", "refresh_token": "1//REFRESHSECRET"}'


@pytest.fixture
def mk(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    a = app_mod.MonkeyApp(tmp_path / "Monkey", headless=True)
    events = []
    a.ui.emit = lambda name, p=None: events.append((name, p))
    return a, app_mod.Api(a), events


def test_fresh_install_reports_every_area_and_skips_unconfigured(mk):
    a, api, _ = mk
    checks = H.run_checks(a, api)
    areas = {c.area for c in checks}
    assert {"App", "Brain", "Voice", "Listening", "Google", "Calendar", "Canvas", "Memory", "Morning brief",
            "Budget"} <= areas
    by = {(c.area, c.name): c for c in checks}
    assert by[("Brain", "Claude key")].status == H.FAIL and "Settings" in by[("Brain", "Claude key")].fix
    assert by[("Google", "Gmail + Calendar")].status == H.SKIP
    assert by[("Calendar", "Calendar link")].status == H.SKIP
    assert by[("Morning brief", "Class schedule")].status == H.WARN


def test_report_never_contains_secrets_or_emails(mk, monkeypatch):
    a, api, _ = mk
    keys.set("anthropic", SECRET)
    keys.set("google_client", '{"installed": {"client_id": "1-x.apps.googleusercontent.com", "client_secret": "GOCSPX-zzz",'
                              ' "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",'
                              ' "redirect_uris": ["http://localhost"]}}')
    keys.set("google_token", TOKEN)
    keys.set("calendar_ics", "https://calendar.google.com/calendar/ical/me%40gmail.com/private-abc/basic.ics")

    class Boom(Exception):
        pass

    def bad_list(**kw):
        raise Boom(f"401 for key {SECRET} user someone@gmail.com at https://api.anthropic.com/v1/models")

    monkeypatch.setattr(a, "_ensure_client", lambda: NS(models=NS(list=bad_list)))
    monkeypatch.setattr(a.google, "service", lambda *x: (_ for _ in ()).throw(RuntimeError(f"token {TOKEN} for x@y.com")))
    monkeypatch.setattr(a.ics_calendar, "list_events", lambda s, e: (_ for _ in ()).throw(
        RuntimeError("could not fetch https://calendar.google.com/calendar/ical/me%40gmail.com/private-abc/basic.ics")))
    checks = H.run_checks(a, api)
    text = H.report_text(checks) + repr(H.as_dicts(checks))
    for leak in (SECRET, "SUPERSECRET", "ya29", "REFRESHSECRET", "GOCSPX", "@gmail.com", "x@y.com", "private-abc",
                 "https://"):
        assert leak not in text, leak
    by = {(c.area, c.name): c for c in checks}
    assert by[("Brain", "Claude key")].status == H.FAIL
    assert by[("Google", "Gmail")].status == H.FAIL and by[("Calendar", "Calendar link")].status == H.FAIL


def test_working_key_is_ok(mk, monkeypatch):
    a, api, _ = mk
    keys.set("anthropic", SECRET)
    monkeypatch.setattr(a, "_ensure_client", lambda: NS(models=NS(list=lambda **kw: NS(data=[1]))))
    by = {(c.area, c.name): c for c in H.run_checks(a, api)}
    assert by[("Brain", "Claude key")].status == H.OK


def test_one_crashing_or_hanging_group_does_not_stop_the_rest(mk, monkeypatch):
    a, api, _ = mk

    def crash(app):
        raise ZeroDivisionError("boom")

    def hang(app):
        time.sleep(3)
        return []

    groups = list(H.GROUPS)
    groups[1] = ("Brain", crash)
    groups[2] = ("Voice", hang)
    monkeypatch.setattr(H, "GROUPS", groups)
    checks = H.run_checks(a, api, timeout_s=0.5)
    by_area = {c.area: c for c in checks}
    assert by_area["Brain"].status == H.FAIL and "boom" in by_area["Brain"].detail
    assert by_area["Voice"].status == H.WARN and "didn't answer" in by_area["Voice"].detail
    assert "Memory" in by_area and "Budget" in by_area


def test_api_runs_in_background_and_emits(mk):
    a, api, events = mk
    assert api.health_check()["ok"] is True
    for _ in range(100):
        if any(n == "health" for n, _ in events):
            break
        time.sleep(0.1)
    p = next(p for n, p in events if n == "health")
    assert p["ok"] and p["checks"] and p["report"].startswith("Monkey check")


def test_task_registered_query(monkeypatch):
    monkeypatch.setattr(scheduler.sys, "platform", "win32")
    monkeypatch.setattr(scheduler.subprocess, "run", lambda *a, **k: NS(returncode=0, stdout="Monkey\\Morning brief Ready"))
    assert scheduler.is_registered() is True
    monkeypatch.setattr(scheduler.subprocess, "run", lambda *a, **k: NS(returncode=1, stdout="", stderr="not found"))
    assert scheduler.is_registered() is False

    def oops(*a, **k):
        raise subprocess.TimeoutExpired("schtasks", 10)

    monkeypatch.setattr(scheduler.subprocess, "run", oops)
    assert scheduler.is_registered() is False


def test_schedule_first_error_says_how(mk):
    a, api, _ = mk
    r = api.brief_task_preview()
    assert not r["ok"] and r["needs_schedule"] and "Confirm schedule" in r["error"]

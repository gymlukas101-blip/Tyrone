"""Outlook must never be started by a status check: only the Connect button (or a real read after connecting)."""
from __future__ import annotations

import sys
import types

import pytest

from monkey.integrations import outlook_com as oc


@pytest.fixture
def fake_win(monkeypatch):
    """Pretend to be Windows with classic Outlook registered; record any COM launch."""
    calls = {"dispatch": 0, "active": 0}
    client = types.SimpleNamespace(
        Dispatch=lambda name: calls.__setitem__("dispatch", calls["dispatch"] + 1) or object(),
        GetActiveObject=lambda name: (calls.__setitem__("active", calls["active"] + 1), (_ for _ in ()).throw(OSError("not running")))[1],
    )
    monkeypatch.setitem(sys.modules, "win32com", types.SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setattr(oc.sys, "platform", "win32")
    monkeypatch.setattr(oc, "installed", lambda: True)
    return calls


def test_available_never_launches_outlook(fake_win):
    on = {"v": False}
    p = oc.OutlookProvider(enabled=lambda: on["v"])
    assert p.available() is False            # not connected yet
    on["v"] = True
    for _ in range(20):                      # UI refreshes, "all calendars" reads, morning brief checks
        assert p.available() is True
    assert fake_win == {"dispatch": 0, "active": 0}


def test_available_false_when_classic_outlook_missing(fake_win, monkeypatch):
    monkeypatch.setattr(oc, "installed", lambda: False)
    assert oc.OutlookProvider(enabled=lambda: True).available() is False


def test_app_prefers_running_outlook(fake_win):
    oc.OutlookProvider()._app()
    assert fake_win == {"dispatch": 1, "active": 1}   # tried to attach first, launched only because none was running


def test_not_windows_is_never_available(monkeypatch):
    monkeypatch.setattr(oc.sys, "platform", "linux")
    assert oc.installed() is False
    assert oc.OutlookProvider(enabled=lambda: True).available() is False


def test_outlook_connected_defaults_off():
    from monkey.config import Settings

    assert Settings().outlook_connected is False


# ---- the Connect button opens Outlook visibly and always comes back with an answer ----------------------------
class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class _Mail:
    Class = oc.CLASS_MAIL
    EntryID, SenderName, SenderEmailType, SenderEmailAddress, To = "1", "Prof", "SMTP", "p@wisc.edu", ""
    Subject, Body, UnRead, ConversationID = "Hi", "hello", True, ""

    class ReceivedTime:
        year, month, day, hour, minute, second = 2026, 11, 20, 9, 0, 0


def _outlook_app(ready_after: float, clock: _Clock):
    def attach(name):
        if clock() < ready_after:
            raise OSError("Operation unavailable")          # starting, or waiting on a sign-in screen
        items = types.SimpleNamespace(Sort=lambda *a: None, GetFirst=lambda: _Mail())
        folder = types.SimpleNamespace(Items=items)
        ns = types.SimpleNamespace(GetDefaultFolder=lambda i: folder)
        return types.SimpleNamespace(GetNamespace=lambda n: ns)
    return attach


@pytest.fixture
def no_com(monkeypatch):
    monkeypatch.setitem(sys.modules, "pythoncom", types.SimpleNamespace(CoInitialize=lambda: None,
                                                                       CoUninitialize=lambda: None))


def test_connect_opens_outlook_visibly_and_waits_for_sign_in(no_com):
    clock, launched, running = _Clock(), [], set()

    def launch():
        launched.append(1)
        running.add("outlook.exe")
    got = oc.OutlookProvider().connect(wait_s=90, launch=launch, procs=lambda: set(running),
                                       attach=_outlook_app(ready_after=25, clock=clock),
                                       sleep=clock.sleep, clock=clock)
    assert launched == [1] and len(got) == 1 and got[0].subject == "Hi"
    assert 25 <= clock() < 30                                 # waited while you signed in, then connected


def test_connect_uses_an_already_open_outlook_without_launching(no_com):
    clock = _Clock()
    got = oc.OutlookProvider().connect(launch=lambda: pytest.fail("must not launch"), procs=lambda: {"outlook.exe"},
                                       attach=_outlook_app(0, clock), sleep=clock.sleep, clock=clock)
    assert len(got) == 1


def test_connect_explains_new_outlook(no_com):
    clock = _Clock()
    with pytest.raises(oc.OutlookConnectError) as e:
        oc.OutlookProvider().connect(wait_s=10, launch=lambda: None, procs=lambda: {"olk.exe"},
                                     attach=_outlook_app(0, clock), sleep=clock.sleep, clock=clock)
    assert "new Outlook" in str(e.value) and "classic" in str(e.value)


def test_connect_gives_a_next_step_when_outlook_never_answers(no_com):
    clock = _Clock()
    with pytest.raises(oc.OutlookConnectError) as e:
        oc.OutlookProvider().connect(wait_s=10, launch=lambda: None, procs=lambda: {"outlook.exe"},
                                     attach=_outlook_app(10_000, clock), sleep=clock.sleep, clock=clock)
    assert "sign in" in str(e.value) and clock() >= 10


def test_connect_reports_outlook_that_wont_start(no_com):
    clock = _Clock()

    def launch():
        raise OSError("The system cannot find the file specified")
    with pytest.raises(oc.OutlookConnectError) as e:
        oc.OutlookProvider().connect(launch=launch, procs=set, sleep=clock.sleep, clock=clock)
    assert "Outlook (classic)" in str(e.value)


def test_connect_button_always_answers(monkeypatch):
    """The API wraps connect() in a deadline and turns errors into a message, never a silent hang."""
    from types import SimpleNamespace

    from monkey import app as appmod

    monkeypatch.setattr(appmod.sys, "platform", "win32")
    monkeypatch.setattr(oc, "installed", lambda: True)
    saved = []
    cfg = SimpleNamespace(settings=SimpleNamespace(outlook_connected=False), save=lambda: saved.append(1))

    def boom(**kw):
        raise oc.OutlookConnectError(oc.NEW_OUTLOOK)
    fake = SimpleNamespace(outlook=SimpleNamespace(connect=boom), cfg=cfg, _emit=lambda *a: None)
    api = appmod.Api.__new__(appmod.Api)
    api._app = fake
    r = api.test_outlook()
    assert r["ok"] is False and "new Outlook" in r["error"] and not saved
    fake.outlook = SimpleNamespace(connect=lambda **kw: [object()])
    r = api.test_outlook()
    assert r == {"ok": True, "count": 1} and cfg.settings.outlook_connected is True and saved

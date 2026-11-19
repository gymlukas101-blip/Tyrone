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

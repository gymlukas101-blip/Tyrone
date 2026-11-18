"""App-level morning brief: the real MonkeyApp wiring with nothing connected (headless, temp data dir)."""
import pytest

from monkey import app as app_mod
from monkey.routines.morning import SCHOOL_DAYS


@pytest.fixture
def mk(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    a = app_mod.MonkeyApp(tmp_path / "Monkey", headless=True)
    return a, app_mod.Api(a)


def test_confirm_schedule_sanitizes_and_enables_timing(mk):
    a, api = mk
    st = api.brief_status()
    assert st["verified"] is False and st["next_run"] is None                 # nothing timed until confirmed
    st = api.brief_confirm({"mon": "08:50", "tue": "9:30", "sat": "10:00", "wed": "nope"})
    assert st["verified"] and st["schedule"] == {"mon": "08:50", "tue": "9:30"}
    assert st["next_run"] is not None


def test_preview_with_nothing_connected_is_labeled(mk):
    a, api = mk
    api.brief_confirm({d: "09:00" for d in SCHOOL_DAYS})
    r = api.brief_preview(opened=False)
    assert r["ok"]
    b = r["brief"]
    if b is None:                                                            # weekend when the test runs
        return
    st = {s["title"]: s["status"] for s in b["sections"]}
    assert st["Today"] == "not_connected" and st["Unread email"] == "not_connected"
    assert st["Due in 72 h"] == "not_connected"


def test_task_xml_preview_has_safe_settings(mk):
    a, api = mk
    assert api.brief_task_preview()["ok"] is False                           # no confirmed schedule yet
    api.brief_confirm({"mon": "08:50", "thu": "09:30"})
    xml = api.brief_task_preview()["xml"]
    assert "<WakeToRun>true</WakeToRun>" in xml and "<StartWhenAvailable>true</StartWhenAvailable>" in xml
    assert "--routine morning" in xml and xml.count("<CalendarTrigger>") == 2
    assert "T07:20:00" in xml and "T08:00:00" in xml                         # 90 minutes before each


def test_headless_routine_without_schedule_does_nothing(mk, monkeypatch):
    a, api = mk
    monkeypatch.setattr(app_mod, "MonkeyApp", lambda headless=True: a)
    assert app_mod.run_routine("morning") == 0
    assert not [k for k in ("brief",) if a.ledger.get_state("brief:" + __import__("datetime").date.today().isoformat())]
    assert app_mod.run_routine("bogus") == 2


def test_canvas_token_status(mk):
    from monkey.routines.canvas_token import status

    assert status(False, "")["status"] == "none"
    assert status(True, "", rejected=True)["status"] == "expired"
    assert status(True, "2026-11-20", today=__import__("datetime").date(2026, 11, 18))["status"] == "expiring"
    assert status(True, "2026-11-10", today=__import__("datetime").date(2026, 11, 18))["status"] == "expired"
    assert status(True, "2026-12-15", today=__import__("datetime").date(2026, 11, 18))["status"] == "ok"
    a, api = mk
    assert api.brief_status()["canvas"]["status"] == "none"

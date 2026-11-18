from types import SimpleNamespace as NS

from monkey.updater import Updater


class FakeMgr:
    def __init__(self, newer=None):
        self.newer = newer
        self.downloaded = None
        self.applied = None

    def get_current_version(self):
        return "0.3.10"

    def check_for_updates(self):
        return NS(TargetFullRelease=NS(Version=self.newer)) if self.newer else None

    def download_updates(self, info):
        self.downloaded = info

    def apply_updates_and_restart(self, info):
        self.applied = info


def make(mgr=None, enabled=True, boom=False):
    events = []

    def factory():
        if boom:
            raise RuntimeError("This application is not properly installed: blah\nmore")
        return mgr

    return Updater(lambda e, p: events.append((e, p)), lambda: enabled, factory), events


def test_up_to_date():
    u, ev = make(FakeMgr())
    s = u.check()
    assert s["status"] == "up_to_date" and s["current"] == "0.3.10" and ev == []


def test_update_downloaded_then_applied():
    mgr = FakeMgr("0.3.11")
    u, ev = make(mgr)
    s = u.check()
    assert s["status"] == "ready" and s["available"] == "0.3.11" and mgr.downloaded
    assert [p["status"] for _, p in ev] == ["downloading", "ready"]
    u.apply()
    assert mgr.applied is mgr.downloaded


def test_not_installed_is_reported_not_raised():
    u, _ = make(boom=True)
    s = u.check()
    assert s["status"] == "unavailable" and "not properly installed" in s["detail"]
    assert u.apply()["error"]


def test_errors_are_caught():
    class Offline(FakeMgr):
        def check_for_updates(self):
            raise OSError("network down")

    u, _ = make(Offline())
    assert u.check()["status"] == "error"

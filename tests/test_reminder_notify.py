"""To-do reminders outside Monkey's window: Windows notifications (fake toast backend; the real one is checked on
Windows only) and the phone through ntfy (fake HTTP). No test here talks to the network or shows a real toast."""
from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from monkey.memory.todos import TodoStore
from monkey.notify import due_phrase
from monkey.notify import ntfy, wintoast
from monkey.notify.ntfy import NtfySender, PhoneMessage, PhoneNotifier, normalize_server, reminder_message
from monkey.notify.wintoast import Handlers, WindowsNotifier

MON = datetime(2026, 11, 23, 10, 0)            # a Monday morning, local time
TOPIC = "monkey-" + "T" * 32                     # a valid, obviously fake topic
TOKEN = "tk_fake_token_for_tests_0000"


# ---------------------------------------------------------------- fakes
class FakeBackend:
    def __init__(self, available=True, fail=False):
        self.available = available
        self.reason = "ready (fake)" if available else "not here (fake)"
        self.fail = fail
        self.shown: list[dict] = []
        self.removed: list[str] = []

    def show(self, tag, lines, *, high, expires, buttons, on_click):
        if self.fail:
            raise OSError("toast platform said no")
        self.shown.append({"tag": tag, "lines": lines, "high": high, "expires": expires, "buttons": buttons,
                           "click": on_click})

    def remove(self, tag):
        self.removed.append(tag)


class FakeResponse:
    def __init__(self, code):
        self.status_code = code


class FakePost:
    """Records each request; answers with the scripted results (an int status or an exception)."""

    def __init__(self, *results, gate: threading.Event | None = None):
        self.results = list(results) or [200]
        self.calls: list[dict] = []
        self.gate = gate

    def __call__(self, url, *, json, headers, timeout):
        if self.gate is not None:
            self.gate.wait(5)
        self.calls.append({"url": url, "json": json, "headers": dict(headers), "timeout": timeout})
        r = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(r, Exception):
            raise r
        return FakeResponse(r)


def _secrets(**initial):
    store = dict(initial)
    return store, store.get, store.__setitem__


def _phone(post, *, enabled=True, show_text=True, topic=TOPIC, token=None, server="https://ntfy.sh"):
    st = NS(todo_phone_notify=enabled, todo_phone_show_text=show_text, ntfy_server=server)
    init = {}
    if topic:
        init[ntfy.TOPIC_KEY] = topic
    if token:
        init[ntfy.TOKEN_KEY] = token
    store, get, put = _secrets(**init)
    sleeps: list[float] = []
    p = PhoneNotifier(lambda: st, get, put, sender=NtfySender(post=post, sleep=sleeps.append))
    return p, st, store, sleeps


def _app(tmp_path, *, backend=None, in_front=False, phone=None, **settings):
    """A stand-in for MonkeyApp with just what todo_tick and the toast handlers use."""
    from monkey.app import MonkeyApp

    events, said = [], []
    st = NS(todo_reminders=True, todo_speak_reminders=False, todo_reminder_lead_min=10, todo_windows_notify=True,
            todo_phone_notify=False, todo_phone_show_text=True)
    st.__dict__.update(settings)
    app = NS(cfg=NS(settings=st), todos=TodoStore(tmp_path / "monkey.db"), speaker=None, _listening=False,
             _agent_state="idle", _emit=lambda e, p: events.append((e, p)), _say=said.append, phone=phone)
    app.win_notify = WindowsNotifier(lambda: st, Handlers(
        open=lambda i: MonkeyApp._todo_open_from_toast(app, i),
        done=lambda i: MonkeyApp._todo_done_from_toast(app, i),
        snooze=lambda i, m: MonkeyApp._todo_snooze_from_toast(app, i, m)),
        backend=backend or FakeBackend(), in_front=lambda: in_front)
    return app, events, (lambda now=None: MonkeyApp.todo_tick(app, now))


# ---------------------------------------------------------------- Windows notifications
def test_windows_toast_once_per_due_with_text_time_and_buttons(tmp_path):
    app, events, tick = _app(tmp_path)
    t = app.todos.add("Call the dentist", due="2026-11-23T10:05", priority="high", now=MON)
    assert [x["id"] for x in tick(MON)] == [t["id"]]
    b = app.win_notify.backend
    assert len(b.shown) == 1
    shown = b.shown[0]
    assert shown["tag"] == t["id"]
    assert shown["lines"] == ["Call the dentist", "Reminder · due today 10:05 AM · high priority"]
    assert shown["buttons"] == [("Done", f"done:{t['id']}"), ("Snooze 10 min", f"snooze:{t['id']}")]
    assert shown["high"] is True and shown["expires"] > MON
    assert [e for e, _ in events] == ["todo_reminder"]                    # the in-app note fires too
    assert tick(MON) == [] and tick(MON + timedelta(minutes=3)) == [] and len(b.shown) == 1   # once per due time


def test_windows_toast_buttons_run_the_in_app_handlers(tmp_path):
    app, events, tick = _app(tmp_path)
    a = app.todos.add("Start laundry", due="2026-11-23T10:05", now=MON)
    b_ = app.todos.add("Email the TA", due="2026-11-23T10:06", now=MON)
    tick(MON)
    toasts = {s["tag"]: s for s in app.win_notify.backend.shown}
    toasts[a["id"]]["click"](f"done:{a['id']}")
    assert app.todos.get(a["id"])["status"] == "done"
    assert events[-1][0] == "todo_changed" and events[-1][1]["action"] == "done"
    toasts[b_["id"]]["click"](f"snooze:{b_['id']}")
    assert events[-1][1]["action"] == "snoozed"
    toasts[b_["id"]]["click"](b_["id"])                                    # the body: open the To-do panel
    assert events[-1] == ("todo_open", {"id": b_["id"]})
    toasts[a["id"]]["click"]("done:gone")                                  # a deleted item: quietly nothing
    assert events[-1] == ("todo_open", {"id": b_["id"]})


def test_snooze_is_honoured_then_it_comes_back(tmp_path):
    from monkey.app import Api

    app, events, tick = _app(tmp_path)
    now = datetime.now().replace(second=0, microsecond=0)
    t = app.todos.add("Take the pizza out", due=(now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"), now=now)
    tick(now)
    b = app.win_notify.backend
    assert len(b.shown) == 1
    assert Api(app).todo_snooze(t["id"], 10)["ok"]
    assert b.removed == [t["id"]]                                          # snoozed in the app: toast taken back
    assert tick(now + timedelta(minutes=1)) == [] and len(b.shown) == 1    # still snoozed: nothing
    # `now` is cut to the minute, so the snooze (10 min from the real clock) has surely ended 12 minutes on
    assert [x["id"] for x in tick(now + timedelta(minutes=12))] == [t["id"]]
    assert len(b.shown) == 2                                               # back after the snooze, once
    assert tick(now + timedelta(minutes=13)) == [] and len(b.shown) == 2


def test_done_or_deleted_in_the_app_takes_the_toast_back(tmp_path):
    from monkey.app import Api

    app, _, tick = _app(tmp_path)
    a = app.todos.add("One", due="2026-11-23T10:05", now=MON)
    c = app.todos.add("Two", due="2026-11-23T10:05", now=MON)
    tick(MON)
    api = Api(app)
    api.todo_update(a["id"], {"status": "done"})
    api.todo_delete(c["id"])
    assert app.win_notify.backend.removed == [a["id"], c["id"]]
    api.todo_update(a["id"], {"text": "One again"})                     # nothing shown for it any more: no call
    assert app.win_notify.backend.removed == [a["id"], c["id"]]


def test_no_double_reminder_when_monkey_is_in_front(tmp_path):
    app, events, tick = _app(tmp_path, in_front=True)
    app.todos.add("Call mom", due="2026-11-23T10:05", now=MON)
    tick(MON)
    assert app.win_notify.backend.shown == [] and [e for e, _ in events] == ["todo_reminder"]
    # With the in-app note off, the Windows notification is the only reminder, so it shows even in front.
    (tmp_path / "b").mkdir()
    app2, ev2, tick2 = _app(tmp_path / "b", in_front=True, todo_reminders=False)
    app2.todos.add("Call mom", due="2026-11-23T10:05", now=MON)
    tick2(MON)
    assert len(app2.win_notify.backend.shown) == 1 and ev2 == []


def test_windows_off_or_unavailable_or_broken(tmp_path):
    app, events, tick = _app(tmp_path, todo_windows_notify=False)
    app.todos.add("A", due="2026-11-23T10:05", now=MON)
    tick(MON)
    assert app.win_notify.backend.shown == [] and len(events) == 1
    (tmp_path / "u").mkdir()
    app2, ev2, tick2 = _app(tmp_path / "u", backend=FakeBackend(available=False))
    app2.todos.add("A", due="2026-11-23T10:05", now=MON)
    assert len(tick2(MON)) == 1 and len(ev2) == 1                          # in-app still works
    assert app2.win_notify.describe() == {"enabled": True, "available": False, "detail": "not here (fake)"}
    (tmp_path / "f").mkdir()
    app3, ev3, tick3 = _app(tmp_path / "f", backend=FakeBackend(fail=True))
    app3.todos.add("A", due="2026-11-23T10:05", now=MON)
    assert len(tick3(MON)) == 1 and len(ev3) == 1                          # a broken toast never stops the rest
    assert "failed (OSError)" in app3.win_notify.describe()["detail"]


def test_off_everywhere_fires_nothing_and_keeps_the_reminder(tmp_path):
    app, events, tick = _app(tmp_path, todo_reminders=False, todo_windows_notify=False)
    t = app.todos.add("A", due="2026-11-23T10:05", now=MON)
    assert tick(MON) == [] and events == []
    app.cfg.settings.todo_windows_notify = True                            # turned on later: it still comes
    assert [x["id"] for x in tick(MON)] == [t["id"]]


def test_not_windows_is_a_clear_no_op(monkeypatch):
    monkeypatch.setattr(wintoast.sys, "platform", "linux")
    n = WindowsNotifier(lambda: NS(todo_windows_notify=True), Handlers(lambda i: None, lambda i: None, lambda i, m: None))
    assert isinstance(n.backend, wintoast.UnavailableBackend)
    assert n.describe() == {"enabled": True, "available": False,
                            "detail": "Windows notifications only work on Windows."}
    assert n.notify({"id": "x", "text": "A", "due": "2026-11-23T10:05", "priority": "normal"}, MON, in_app=True) \
        == "unavailable"
    assert n.test()["ok"] is False
    assert wintoast.monkey_in_front() is False


def test_windows_test_notification_has_no_buttons(tmp_path):
    app, _, _ = _app(tmp_path)
    assert app.win_notify.test(MON) == {"ok": True, "error": ""}
    shown = app.win_notify.backend.shown[0]
    assert shown["buttons"] == [] and shown["lines"][0] == "Test reminder from Monkey"


@pytest.mark.skipif(sys.platform != "win32", reason="the real toast library only exists on Windows")
def test_real_windows_toast_library_loads_and_builds(tmp_path):  # pragma: no cover - Windows CI
    aumid = "Monkey.Tests.Reminders"
    try:
        wintoast.register_aumid(aumid, "Monkey tests", None)
        b = wintoast.WinToastBackend(aumid)
        assert b.available, b.reason
        t = b.build("abc", ["Text", "due now"], high=True, expires=None, buttons=[("Done", "done:abc")],
                    on_click=lambda a: None)
        assert t.tag == "abc" and len(t.actions) == 1
    finally:
        wintoast.unregister_aumid(aumid)


# ---------------------------------------------------------------- phone (ntfy)
def test_new_topic_is_long_random_and_valid():
    topics = {ntfy.new_topic() for _ in range(50)}
    assert len(topics) == 50
    for t in topics:
        assert ntfy.valid_topic(t) and t.startswith("monkey-") and 30 < len(t) <= 64
    assert not ntfy.valid_topic("monkey") and not ntfy.valid_topic("has space in it, long enough!!")


def test_request_shape_and_priority():
    post = FakePost(200)
    p, *_ = _phone(post, token=TOKEN)
    res = p.send_now(reminder_message("Call the dentist", "due today 5:00 PM", high=True, show_text=True))
    assert res.ok and res.attempts == 1
    (call,) = post.calls
    assert call["url"] == "https://ntfy.sh/"                               # the topic is not in the URL
    assert call["timeout"] <= 5
    assert call["headers"] == {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
    assert call["json"] == {"topic": TOPIC, "title": "Monkey reminder", "message": "Call the dentist\nDue today 5:00 PM",
                            "priority": 4, "tags": ["alarm_clock"]}
    post2 = FakePost(200)
    p2, *_ = _phone(post2, server="https://ntfy.example.org/sub/")
    p2.send_now(reminder_message("Laundry", "due today 6:00 PM", high=False, show_text=True))
    assert post2.calls[0]["url"] == "https://ntfy.example.org/sub/"
    assert "Authorization" not in post2.calls[0]["headers"] and post2.calls[0]["json"]["priority"] == 3


def test_privacy_toggle_keeps_the_text_off_the_server():
    m = reminder_message("Pick up prescription", "due today 5:00 PM", high=False, show_text=False)
    assert m.title == "Monkey reminder" and m.body == "You have a reminder"
    assert "prescription" not in str(ntfy.payload(TOPIC, m))


def test_retry_once_then_give_up_quietly():
    import httpx

    post = FakePost(503, 200)
    p, _, _, sleeps = _phone(post)
    assert p.send_now(PhoneMessage("t", "b")).ok and len(post.calls) == 2 and sleeps == [ntfy.RETRY_AFTER_S]
    post = FakePost(httpx.ReadTimeout("slow"))
    p, _, _, sleeps = _phone(post)
    res = p.send_now(PhoneMessage("t", "b"))
    assert not res.ok and res.attempts == 2 and len(post.calls) == 2 and len(sleeps) == 1
    assert res.detail == "the server didn't answer within 5 seconds"
    assert p.status["state"] == "failed" and p.status["detail"] == res.detail
    post = FakePost(httpx.ConnectError("no route"))
    p, *_ = _phone(post)
    assert "couldn't reach the server" in p.send_now(PhoneMessage("t", "b")).detail
    post = FakePost(401)                                                   # a refusal: retrying won't help
    p, _, _, sleeps = _phone(post)
    res = p.send_now(PhoneMessage("t", "b"))
    assert not res.ok and len(post.calls) == 1 and sleeps == [] and "access token" in res.detail


def test_no_secret_or_text_in_logs_or_status(caplog):
    caplog.set_level(logging.DEBUG)
    leak = RuntimeError(f"boom https://ntfy.sh/{TOPIC} Bearer {TOKEN} Secret dentist appointment")
    post = FakePost(leak)
    p, *_ = _phone(post, token=TOKEN)
    res = p.send_now(reminder_message("Secret dentist appointment", "due today 5:00 PM", high=False, show_text=True))
    assert not res.ok and res.detail == "couldn't send (RuntimeError)"
    blob = caplog.text + str(p.status) + res.detail
    for secret in (TOPIC, TOKEN, "dentist"):
        assert secret not in blob
    assert "phone notification not sent" in caplog.text                   # it is logged, just safely


def test_submit_never_blocks_and_sends_in_the_background():
    gate = threading.Event()
    post = FakePost(200, gate=gate)
    p, *_ = _phone(post)
    t0 = time.monotonic()
    assert p.submit(PhoneMessage("t", "b"))
    assert time.monotonic() - t0 < 0.5 and post.calls == []                # the request is still waiting
    gate.set()
    assert p.wait_idle(10) and len(post.calls) == 1 and p.status["state"] == "ok"
    off, *_ = _phone(FakePost(200), enabled=False)
    assert off.submit(PhoneMessage("t", "b")) is False
    unset, *_ = _phone(FakePost(200), topic=None)
    assert unset.enabled() is False and unset.submit(PhoneMessage("t", "b")) is False
    res = unset.send_now(PhoneMessage("t", "b"))
    assert not res.ok and "Set up my phone" in res.detail


def test_reminder_tick_queues_the_phone_message(tmp_path):
    post = FakePost(200)
    phone, st, *_ = _phone(post)
    app, events, tick = _app(tmp_path, phone=phone, todo_windows_notify=False)
    app.cfg.settings = NS(**{**app.cfg.settings.__dict__, "todo_phone_notify": True})
    t = app.todos.add("Call the dentist", due="2026-11-23T10:05", priority="high", now=MON)
    assert [x["id"] for x in tick(MON)] == [t["id"]]
    assert phone.wait_idle(10)
    (call,) = post.calls
    assert call["json"]["message"] == "Call the dentist\nDue today 10:05 AM" and call["json"]["priority"] == 4
    assert tick(MON) == [] and len(post.calls) == 1                        # once per due time
    st.todo_phone_show_text = False
    app.cfg.settings.todo_phone_show_text = False
    app.todos.add("Private thing", due="2026-11-23T10:07", now=MON)
    tick(MON)
    assert phone.wait_idle(10) and post.calls[-1]["json"]["message"] == "You have a reminder"


def test_due_phrase():
    assert due_phrase({"due": "2026-11-23T10:05"}, MON) == "due today 10:05 AM"
    assert due_phrase({"due": "2026-11-23T09:00"}, MON) == "was due today 9:00 AM"


@pytest.mark.parametrize("raw, want", [
    ("", "https://ntfy.sh"), ("ntfy.example.com", "https://ntfy.example.com"),
    ("https://ntfy.example.com/", "https://ntfy.example.com"), ("http://192.168.1.20:8080", "http://192.168.1.20:8080"),
    ("http://localhost", "http://localhost"), ("http://ntfy.home.arpa", "http://ntfy.home.arpa"),
])
def test_server_address_ok(raw, want):
    assert normalize_server(raw) == want


@pytest.mark.parametrize("raw", ["http://ntfy.example.com", "ftp://ntfy.sh", "https://ntfy.sh/?x=1",
                                 "https://user:pw@ntfy.sh", "https://", "https://ntfy.sh:99999"])
def test_server_address_refused(raw):
    with pytest.raises(ValueError):
        normalize_server(raw)


# ---------------------------------------------------------------- settings persistence
def test_topic_and_token_live_in_the_secret_store_not_settings(tmp_path, monkeypatch):
    from monkey import keys
    from monkey.app import Api
    from monkey.config import Config

    for env in ("MONKEY_NTFY_TOPIC", "MONKEY_NTFY_TOKEN"):
        monkeypatch.delenv(env, raising=False)
    keys.use_store(tmp_path / "secrets.dat")
    try:
        cfg = Config(tmp_path / "data")
        assert (cfg.settings.todo_windows_notify, cfg.settings.todo_phone_notify, cfg.settings.todo_phone_show_text,
                cfg.settings.ntfy_server) == (True, False, True, "https://ntfy.sh")
        phone = PhoneNotifier(lambda: cfg.settings, keys.get, keys.set, sender=NtfySender(post=FakePost(200)))
        app = NS(cfg=cfg, phone=phone, win_notify=WindowsNotifier(lambda: cfg.settings, Handlers(
            lambda i: None, lambda i: None, lambda i, m: None), backend=FakeBackend()))
        api = Api(app)
        monkeypatch.setattr(Api, "get_state", lambda self: {})
        r = api.phone_setup(False)
        topic = r["phone"]["topic"]
        assert r["ok"] and ntfy.valid_topic(topic) and r["phone"]["configured"] and not r["phone"]["enabled"]
        assert r["phone"]["subscribe_url"] == f"https://ntfy.sh/{topic}"
        assert keys.saved("ntfy_topic") == topic
        assert api.phone_setup(False)["phone"]["topic"] == topic           # stable until renewed
        assert api.save_key("ntfy_token", TOKEN)["ok"] and api.reminder_channels()["phone"]["has_token"]
        assert api.save_key("ntfy_topic", "short")["ok"] is False          # a guessable topic is refused
        api.save_settings({"todo_phone_notify": True, "todo_phone_show_text": False, "ntfy_server": "http://bad.example"})
        assert cfg.settings.todo_phone_notify and not cfg.settings.todo_phone_show_text
        assert cfg.settings.ntfy_server == "https://ntfy.sh"               # an unsafe address is never saved
        assert api.phone_save_server("http://bad.example")["ok"] is False
        assert api.phone_save_server("ntfy.example.org") == {"ok": True, "server": "https://ntfy.example.org"}
        assert api.phone_test()["ok"] and phone.sender._post.calls[0]["url"] == "https://ntfy.example.org/"
        on_disk = (tmp_path / "data" / "settings.json").read_text(encoding="utf-8")
        assert topic not in on_disk and TOKEN not in on_disk and "ntfy_topic" not in on_disk
        assert Config(tmp_path / "data").settings.ntfy_server == "https://ntfy.example.org"   # survives a restart
        renewed = api.phone_setup(True)["phone"]["topic"]
        assert renewed != topic and keys.saved("ntfy_topic") == renewed
        assert api.windows_test_notification()["ok"]
    finally:
        keys.use_store(None)


def test_turning_the_phone_on_sets_it_up(tmp_path, monkeypatch):
    from monkey.app import Api

    store, get, put = _secrets()
    st = NS(todo_phone_notify=False, todo_phone_show_text=True, ntfy_server="https://ntfy.sh")
    cfg = NS(settings=st, update=lambda **kw: st.__dict__.update(kw))
    app = NS(cfg=cfg, phone=PhoneNotifier(lambda: st, get, put))
    monkeypatch.setattr(Api, "get_state", lambda self: {})
    Api(app).save_settings({"todo_phone_notify": True})
    assert ntfy.valid_topic(store[ntfy.TOPIC_KEY]) and app.phone.enabled()


def test_uninstall_hook_forgets_the_notification_identity_quietly(monkeypatch):
    from monkey import updater

    gone = []
    monkeypatch.setattr(wintoast, "unregister_aumid", lambda aumid=wintoast.AUMID: gone.append(aumid))
    updater._forget_notification_identity()
    assert gone == ["velopack.Monkey"]

    def boom(aumid=wintoast.AUMID):
        raise OSError("registry says no")

    monkeypatch.setattr(wintoast, "unregister_aumid", boom)
    updater._forget_notification_identity()                              # never raises during an uninstall

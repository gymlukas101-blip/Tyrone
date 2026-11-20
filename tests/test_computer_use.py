"""Hybrid computer use: the shared model, routing, gate extensions, the trace, and real-Chromium runs of every
browser fixture plus the browser → app → browser workflow (with a stand-in app off Windows)."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from monkey.automation.computer import Computer, Trace
from monkey.automation.computer.coords import BrowserWindowGeometry, ImageMap, convert
from monkey.automation.computer.drivers.uia import CAPABILITY as UIA, Scope, to_pywinauto_keys
from monkey.automation.computer.drivers.browser import CAPABILITY as BROWSER
from monkey.automation.computer.drivers.visual import CAPABILITY as VISUAL
from monkey.automation.computer.model import Box, ElementRef, ErrorKind, Space
from monkey.automation.computer.router import Router
from monkey.automation.computer.trace import Ev
from monkey.automation.permissions import Action, PermissionGate, Risk, Target, classify, path_allowed
from monkey.automation.tasks import S, Task


# ---------------------------------------------------------------------------------------------- coordinates
def test_image_map_round_trip_and_bounds():
    m = ImageMap.fit(Space.SCREEN, -1920, 100, 2560, 1600)           # a monitor left of the primary
    assert (m.img_w, m.img_h) == (1280, 800)
    x, y = m.to_src(640, 400)
    assert (x, y) == (-1920 + 1280, 100 + 800)
    assert m.to_image(x, y) == (640, 400)
    with pytest.raises(ValueError):
        m.to_src(1300, 10)
    b = m.box_to_src(Box(10, 10, 20, 10, Space.IMAGE))
    assert b.space == Space.SCREEN and b.w == 40 and b.h == 20


def test_no_implicit_space_conversion():
    with pytest.raises(ValueError):
        convert(Box(1, 1, 1, 1, Space.VIEWPORT), Space.SCREEN)
    small = ImageMap.fit(Space.VIEWPORT, 0, 0, 800, 600)             # never upscaled
    assert (small.img_w, small.img_h) == (800, 600)


def test_viewport_to_screen_is_explicit_and_dpi_scaled():
    g = BrowserWindowGeometry(screen_x=100, screen_y=50, outer_w=1296, outer_h=900, inner_w=1280, inner_h=800,
                              dpr=1.5)
    assert g.viewport_to_screen(0, 0) == (round((100 + 8) * 1.5), round((50 + 92) * 1.5))


# ---------------------------------------------------------------------------------------------- routing
def test_router_prefers_owner_dialogs_and_semantics_before_pixels():
    r = Router({"browser": BROWSER, "uia": UIA, "visual": VISUAL}, allow_visual=True)
    el = ElementRef("b1:e3", "browser", "b1", "e3", "button", "Save")
    assert r.order("click", el) == ["browser", "visual"]
    assert r.order("click", None, dialog_open=True)[0] == "uia"
    assert r.order("navigate") == ["browser"]
    assert r.order("choose_file") == ["uia"]
    assert r.order("type_text", el) == ["browser"]                     # pixels never type


def test_router_hides_visual_without_screenshot_consent_and_demotes_failures():
    r = Router({"browser": BROWSER, "uia": UIA, "visual": VISUAL}, allow_visual=False)
    assert "visual" not in r.order("click", None)
    r.record("browser", "click", False)
    r.record("browser", "click", False)
    assert r.order("click", None, prefer="browser")[-1] == "browser"


# ---------------------------------------------------------------------------------------------- gate extensions
def test_uploads_are_high_risk_and_limited_to_the_tasks_files(tmp_path):
    f = tmp_path / "report.txt"
    f.write_text("x")
    other = tmp_path.parent / "secret.txt"
    t = Task(objective="o", allowed_domains=["127.0.0.1"], files=[str(f)])
    g = PermissionGate()
    assert classify(Action("upload", path=str(f)))[0] == Risk.HIGH
    assert classify(Action("choose_file", path=str(f)))[0] == Risk.MEDIUM
    assert classify(Action("choose_file", path=str(f), to_web=True))[0] == Risk.HIGH
    d = g.authorize(t, Action("upload", target=Target(role="button", name="Upload"), path=str(f)),
                    page_url="http://127.0.0.1/x")
    assert not d.allowed and d.needs_approval
    d = g.authorize(t, Action("upload", path=str(other)), page_url="http://127.0.0.1/x")
    assert not d.allowed and d.risk == Risk.FORBIDDEN
    assert path_allowed(str(tmp_path / "sub" / "a.txt"), [str(tmp_path)])[0]
    assert not path_allowed(str(tmp_path / ".." / "x.txt"), [str(tmp_path)])[0]


def test_window_scope_includes_owned_dialogs_of_the_same_process_only():
    owners = {11: 10, 12: 10, 13: 11}
    pids = {10: 1, 11: 1, 12: 2, 13: 1, 20: 7, 21: 7}
    sc = Scope({10}, owner=lambda h: owners.get(h, 0), pid=lambda h: pids.get(h, 0), windows=lambda: [13, 12, 11, 10],
               title=lambda h: "Open")
    assert sc.contains(10) and sc.contains(11) and sc.contains(13)
    assert not sc.contains(12)                                        # owned, but another process
    assert sc.dialogs() == [13, 11]
    browser = Scope(set(), {7}, owner=lambda h: 0, pid=lambda h: pids.get(h, 0), windows=lambda: [20, 21])
    assert browser.contains(21) and not browser.contains(10)


def test_key_names_translate_to_pywinauto():
    assert to_pywinauto_keys("Control+S") == "^s"
    assert to_pywinauto_keys("Alt+F4") == "%{F4}"
    assert to_pywinauto_keys("Tab Enter") == "{TAB}{ENTER}"


# ---------------------------------------------------------------------------------------------- trace
def test_trace_never_records_typed_text_or_full_urls(tmp_path):
    p = tmp_path / "t.jsonl"
    tr = Trace("t1", p)
    tr(Ev.ACTION_VERIFIED, op="type_text", text="my secret answer", url="https://x.edu/a?token=abc#f", ms=12)
    line = p.read_text()
    assert "secret" not in line and "token" not in line and "x.edu" in line
    m = tr.metrics()
    assert m["actions"] == 1 and m["verified"] == 1


# ---------------------------------------------------------------------------------------------- real Chromium
@pytest.fixture(scope="module")
def site():
    from tools.computer_bench import fixtures as fx

    srv, port = fx.serve()
    yield port
    srv.shutdown()


from tools.computer_bench.scripts import SCRIPTS  # noqa: E402


@pytest.mark.parametrize("name", list(SCRIPTS))
def test_browser_fixture_reaches_the_servers_end_state(site, name):
    from tools.computer_bench.run_browser import run_fixture

    with tempfile.TemporaryDirectory() as d:
        r = run_fixture(name, site, Path(d), restart=(name == "restart"))
    assert r["success"], r
    if name == "duplicate":
        assert r["duplicates_refused"] >= 1 and r["server"]["counts"].get("duplicate_add") == 1
    if name == "injection":
        assert r["approvals"]["denied"] >= 1 and not r["server"]["counts"].get("injection_delete")
    if name == "fake_success":
        assert r["verify_rejections"] >= 1                           # the hidden "Saved!" banner wasn't accepted
    if name == "canvas_button":
        assert "visual" in r["backends"]
    if name == "upload":
        assert r["approvals"]["approved"] == 2
    if name == "restart":
        assert r["resumed"] and r["server"]["saved"] == {"name": "Ada", "year": "2027"}


def test_hybrid_browser_app_browser_without_losing_state(tmp_path):
    from tools.computer_bench import run_hybrid

    out = tmp_path / "h.json"
    assert run_hybrid.main(["--simulate", "--out", str(out)]) == 0
    import json

    r = json.loads(out.read_text())
    assert r["success"] and r["task_state"] == "COMPLETED"
    assert [s["to"] for s in r["switches"]] == ["uia", "browser"]
    assert r["approvals"] == {"asked": 2, "approved": 2, "denied": 0}


# ---------------------------------------------------------------------------------------------- restart safety
class _NullDriver:
    name = "browser"
    capability = BROWSER
    session_id = "b1"


def test_intents_without_a_completed_op_are_reported_as_uncertain():
    t = Task(objective="o", allowed_domains=["x.org"])
    t.checkpoint("intent", note='click button "Pay"', evidence={"key": "k1", "before": "s1"})
    t.checkpoint("intent", note='click button "Next"', evidence={"key": "k2", "before": "s2"})
    t.checkpoint("op", note='click button "Next"', evidence={"key": "k2", "before": "s2", "after": "s3"})
    c = Computer(t, PermissionGate(), {"browser": _NullDriver()}, Trace(t.id))
    assert c.uncertain() == ['click button "Pay"']
    assert c.ledger == {"k2": "s2"}                                   # rebuilt from checkpoints after a restart


def test_action_cache_replays_a_verified_step_without_a_model_call(site, tmp_path):
    from monkey.automation.browser import BrowserSession
    from monkey.automation.computer.cache import ActionCache
    from monkey.automation.computer.drivers.browser import BrowserDriver
    from monkey.automation.computer.goal import GoalRunner
    from tools.automation_eval import browser_path
    from tools.computer_bench import fixtures as fx
    from tools.computer_bench.harness import BenchHost, ScriptedPlanner, new_task
    from tools.computer_bench.scripts import SCRIPTS as SC

    cache = ActionCache(tmp_path / "cache.json")
    calls = []
    for run in range(2):
        fx.S.reset()
        gate = PermissionGate()
        url = f"http://127.0.0.1:{site}/f/nav"
        t = new_task("Find the member number", url)
        s = BrowserSession(tmp_path / f"p{run}", gate, headless=True, executable_path=browser_path(),
                           allowed_domains=t.allowed_domains).start()
        try:
            host = BenchHost(gate)
            c = Computer(t, gate, {"browser": BrowserDriver(s)}, Trace(t.id), should_stop=host.should_stop)
            c.do("navigate", None, url=url)
            steps = [(cond, p) for cond, p in SC["nav"]["steps"]]
            planner = ScriptedPlanner(steps)
            for _cond, p in steps:
                p.model = "scripted"
            # mark scripted plans as "model" plans so verified ones get cached
            orig = planner.plan
            planner.plan = lambda ctx, attempt=0: (lambda p: (setattr(p, "model", "m"), p)[1])(orig(ctx, attempt))
            assert GoalRunner(t, c, planner, host, cache=cache).run() == "completed"
            calls.append(planner.calls)
        finally:
            s.close()
    assert calls[1] < calls[0]                                        # the second run reused verified steps


# ---------------------------------------------------------------------------------------------- TaskManager
def test_general_task_runs_through_the_task_manager_with_approvals(site, tmp_path):
    from monkey.automation.browser import BrowserSession
    from monkey.automation.manager import TaskManager
    from monkey.automation.tasks import TaskStore
    from tools.automation_eval import browser_path
    from tools.computer_bench import fixtures as fx
    from tools.computer_bench.harness import ScriptedPlanner
    from tools.computer_bench.run_browser import _subst

    fx.S.reset()
    report = tmp_path / "report.txt"
    report.write_text("hello")
    gate = PermissionGate()
    events = []
    m = TaskManager(TaskStore(tmp_path / "a.db"), gate,
                    lambda t: BrowserSession(tmp_path / "prof", gate, headless=True, executable_path=browser_path()),
                    emit=lambda n, p: events.append((n, p)),
                    goal_planner=ScriptedPlanner(_subst(SCRIPTS["upload"]["steps"], {"report": str(report)})),
                    trace_dir=tmp_path / "traces")
    try:
        t = m.create("Attach report.txt and press Upload.", f"http://127.0.0.1:{site}/f/upload",
                     ["127.0.0.1", "localhost"], skill="general", files=[str(report)])
        m.start(t.id)
        end = time.time() + 60
        approved = 0
        while time.time() < end:
            for a in gate.pending_for(t.id):
                m.approve(t.id, a.id, a.token)                       # the user clicks Approve in Monkey's window
                approved += 1
            cur = m.get(t.id)
            if cur.terminal:
                break
            time.sleep(0.2)
        cur = m.wait(t.id, 10)
        assert cur.state == S.COMPLETED, cur.note
        assert approved == 2 and fx.FIXTURES["upload"]["check"]()
        assert (tmp_path / "traces" / f"{t.id}.jsonl").is_file()
        assert any(n == "computer_event" for n, _ in events)
    finally:
        m.shutdown()


def test_general_task_without_claude_fails_cleanly(tmp_path):
    from monkey.automation.manager import TaskManager
    from monkey.automation.tasks import TaskStore

    m = TaskManager(TaskStore(tmp_path / "a.db"), PermissionGate(), lambda t: None)
    t = m.create("Do a thing", "", ["x.org"], skill="general")
    m.start(t.id)
    cur = m.wait(t.id, 10)
    assert cur.state == S.FAILED and "Claude" in cur.note
    m.shutdown()


def test_element_errors_map_to_recovery_strategies():
    from monkey.automation.computer.model import RECOVERY

    for k in ErrorKind:
        assert k in RECOVERY
    assert RECOVERY[ErrorKind.REFUSED] == ()                          # a refusal is never retried around

"""Computer-agent core: state machine, persistence, permissions, coordinate maps, planner tool handling."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from monkey.automation.permissions import Action, PermissionGate, Risk, Target, classify, url_allowed
from monkey.automation.planner import ClaudePlanner, build_prompt, evidence_on_page
from monkey.automation.tasks import S, TERMINAL, TRANSITIONS, InvalidTransition, Task, TaskStore, redact, safe_url


# ---------------------------------------------------------------- state machine
def test_valid_path_to_completion():
    t = Task("finish the course")
    for s in (S.RUNNING, S.WAITING, S.RUNNING, S.NEEDS_INPUT, S.RUNNING, S.VERIFYING, S.COMPLETED):
        t.transition(s)
    assert t.terminal


@pytest.mark.parametrize("src,dst", [(S.READY, S.COMPLETED), (S.READY, S.VERIFYING), (S.PAUSED, S.COMPLETED),
                                     (S.COMPLETED, S.RUNNING), (S.CANCELLED, S.RUNNING), (S.WAITING, S.COMPLETED),
                                     (S.NEEDS_INPUT, S.COMPLETED)])
def test_invalid_transitions(src, dst):
    t = Task("x")
    t.state = src
    with pytest.raises(InvalidTransition):
        t.transition(dst)


def test_only_verifying_reaches_completed_and_terminals_are_final():
    assert [s for s, nxt in TRANSITIONS.items() if S.COMPLETED in nxt] == [S.VERIFYING]
    assert all(not TRANSITIONS[s] for s in TERMINAL)
    assert all(S.CANCELLED in TRANSITIONS[s] for s in S if s not in TERMINAL)   # Stop works from every live state


# ---------------------------------------------------------------- persistence
def test_checkpoints_persist_and_active_tasks_come_back_paused(tmp_path):
    store = TaskStore(tmp_path / "a.db")
    t = Task("course", start_url="http://127.0.0.1:1/", allowed_domains=["127.0.0.1"])
    t.transition(S.RUNNING)
    t.checkpoint("module_complete", "http://127.0.0.1:1/?token=SECRET#x", "module 1", {"module": 1})
    t.usage.actions = 7
    store.save(t)
    again = TaskStore(tmp_path / "a.db")
    rec = again.recover_after_restart()
    back = again.load(t.id)
    assert [r.id for r in rec] == [t.id] and back.state == S.PAUSED and "Resume" in back.note
    assert back.checkpoints[0]["evidence"] == {"module": 1} and back.usage.actions == 7
    assert "SECRET" not in back.checkpoints[0]["url"]                     # query strings never stored
    assert back.progress()["modules_done"] == 1


def test_audit_log_is_privacy_preserving(tmp_path):
    store = TaskStore(tmp_path / "a.db")
    store.audit("t1", "type", "MEDIUM", "textbox Password hunter2", "https://login.example.edu/sso?ticket=abc", "done")
    row = store.audit_log("t1")[0]
    assert row["target"] == "[redacted]" and row["host"] == "login.example.edu" and "abc" not in str(row)
    assert safe_url("https://a.b/c?x=1#y") == "https://a.b/c" and redact("Continue") == "Continue"


# ---------------------------------------------------------------- risk classes
def click(name, role="button", **kw):
    return Action("click", Target(role=role, name=name, **kw))


@pytest.mark.parametrize("action,risk", [
    (click("Continue"), Risk.LOW), (click("Next page", "link"), Risk.LOW), (click("Not now"), Risk.LOW),
    (Action("play", Target("button", "Play lesson")), Risk.LOW), (Action("navigate", url="https://x.edu"), Risk.LOW),
    (click("Complete module"), Risk.MEDIUM), (click("Download PDF"), Risk.MEDIUM), (click("Frobnicate"), Risk.MEDIUM),
    (Action("type", Target("textbox", "Search")), Risk.MEDIUM),
    (click("Send"), Risk.HIGH), (click("Submit"), Risk.HIGH), (click("Place order"), Risk.HIGH),
    (click("Delete account"), Risk.HIGH), (click("Unenroll"), Risk.HIGH),
    (click("Submit quiz"), Risk.USER_ONLY), (click("Check answer"), Risk.USER_ONLY), (click("Sign in"), Risk.USER_ONLY),
    (click("I confirm I reviewed module 1 myself", "checkbox"), Risk.USER_ONLY),
    (click("911", "radio", in_question=True), Risk.USER_ONLY),
    (Action("type", Target("textbox", "Answer", in_question=True)), Risk.USER_ONLY),
    (Action("type", Target("textbox", "Password", input_type="password")), Risk.FORBIDDEN),
    (Action("type", Target("textbox", "Card number")), Risk.FORBIDDEN),
])
def test_classify(action, risk):
    assert classify(action)[0] == risk


def test_url_policy():
    allowed = ["canvas.wisc.edu", "127.0.0.1"]
    assert url_allowed("https://canvas.wisc.edu/courses/1", allowed)[0]
    assert url_allowed("https://sub.canvas.wisc.edu/", allowed)[0]
    assert url_allowed("http://127.0.0.1:8080/x", allowed)[0]
    for bad in ("https://canvas.wisc.edu.evil.com/", "javascript:alert(1)", "file:///C:/Users", "data:text/html,x",
                "https://evil.example/bonus", "https://canvas.wisc.edu\n.evil.com", "chrome://settings"):
        assert not url_allowed(bad, allowed)[0], bad


# ---------------------------------------------------------------- the gate (enforced in the execution layer)
def scope(**kw):
    return NS(id="t1", mode="managed_browser", allowed_domains=["127.0.0.1"], confirm_medium=False, **kw)


def test_gate_low_medium_allowed_high_needs_one_time_approval():
    g = PermissionGate()
    sc = scope()
    assert g.authorize(sc, click("Continue"), "http://127.0.0.1/").allowed
    assert g.authorize(sc, click("Complete module"), "http://127.0.0.1/").allowed
    a = click("Send message")
    d = g.authorize(sc, a, "http://127.0.0.1/inbox")
    assert not d.allowed and d.needs_approval
    ap = g.request("t1", a, "http://127.0.0.1/inbox", d.risk)
    with pytest.raises(PermissionError):
        g.approve(ap.id, "guessed-token")
    g.approve(ap.id, ap.token)
    assert g.authorize(sc, a, "http://127.0.0.1/inbox").allowed            # once…
    assert not g.authorize(sc, a, "http://127.0.0.1/inbox").allowed        # …and only once
    with pytest.raises(PermissionError):
        g.approve(ap.id, "")                                                # tokens are single-use


def test_gate_user_only_forbidden_observe_offsite_and_emergency_stop():
    g = PermissionGate()
    sc = scope()
    assert g.authorize(sc, click("Submit quiz"), "http://127.0.0.1/").user_only
    assert not g.authorize(sc, Action("type", Target("textbox", "Password", input_type="password"), "x")).allowed
    assert not g.authorize(sc, Action("navigate", url="https://evil.example/"), "").allowed
    link = click("Continue to bonus content", "link", href="https://evil.example/bonus")
    assert not g.authorize(sc, link, "http://127.0.0.1/").allowed
    rel = click("Start module 1", "link", href="/module/1/1")
    assert g.authorize(sc, rel, "http://127.0.0.1:9/").allowed               # relative links resolve on the page
    obs_only = scope()
    obs_only.mode = "observe_window"
    assert not g.authorize(obs_only, click("Continue"), "").allowed
    g.stopped.set()
    assert not g.authorize(sc, click("Continue"), "http://127.0.0.1/").allowed


def test_medium_can_require_confirmation():
    g = PermissionGate()
    assert g.authorize(scope(), click("Save"), "http://127.0.0.1/").allowed
    sc = scope()
    sc.confirm_medium = True
    assert g.authorize(sc, click("Save"), "http://127.0.0.1/").needs_approval


# ---------------------------------------------------------------- the Claude planner: tool-result handling
class FakeSession:
    """Just enough of BrowserSession for make_toolset (no real browser)."""

    def __init__(self, gate, elements):
        from monkey.automation.browser import Observation

        self.gate = gate
        self.acted: list = []
        self.obs = Observation(url="http://127.0.0.1/q", title="Quiz", elements=elements, aria="- button")
        self.last_obs = self.obs
        self.page = NS(url="http://127.0.0.1/q")
        self.context = NS(pages=[self.page])
        self.events = []

    def observe(self):
        return self.obs

    def act(self, scope, action, el=None, paused=False):
        from monkey.automation.browser import ActResult

        if el is not None and action.target is None:
            action.target = el.target()
        d = self.gate.authorize(scope, action, self.page.url, paused)
        if not d.allowed:
            return ActResult(False, d.reason, d)
        self.acted.append(action.describe())
        return ActResult(True, "done", d)


def tool_use(i, name, inp, toolset="browser"):
    return NS(type="tool_use", id=f"toolu_{i}", name=name, input=inp, toolset_name=toolset)


def fake_client(blocks):
    msg = NS(content=blocks, usage=NS(input_tokens=1200, output_tokens=80))
    return NS(messages=NS(create=lambda **kw: msg))


def planner_task():
    return Task("finish the training", start_url="http://127.0.0.1/", allowed_domains=["127.0.0.1"])


def test_planner_follows_injection_but_gate_refuses_and_stops_the_batch():
    """A page told the model to submit the exam and open an off-site link. The model complied; nothing happened."""
    pytest.importorskip("anthropic.tools.browser")
    from anthropic.types.beta import BetaToolUseBlock

    from monkey.automation.browser import Element

    g = PermissionGate()
    els = [Element("e1", "button", "Submit final exam"), Element("e2", "button", "Continue")]
    sess = FakeSession(g, els)
    blocks = [BetaToolUseBlock(type="tool_use", id="toolu_1", name="left_click", toolset_name="browser",
                               input={"target": {"type": "ref", "ref": "ref_e1"}}),
              BetaToolUseBlock(type="tool_use", id="toolu_2", name="navigate", toolset_name="browser",
                               input={"url": "https://evil.example/bonus"}),
              tool_use(3, "report_status", {"status": "done", "message": "submitted", "evidence": "Exam submitted"},
                       toolset=None)]
    p = ClaudePlanner(fake_client(blocks), cost_fn=lambda m, u: 0.004)
    r = p.step(planner_task(), sess, sess.obs, [])
    assert sess.acted == []                                  # neither the exam submit nor the off-site page
    assert r.blocked and r.blocked[0][1].needs_approval      # "Submit…" is high-risk → the user would be asked
    assert r.acted == 0 and r.usd == 0.004 and r.input_tokens == 1200
    assert not evidence_on_page(r.evidence, sess.obs)        # its "done" has no proof on the page


def test_planner_routine_click_runs_and_prompt_is_compact_and_fenced():
    pytest.importorskip("anthropic.tools.browser")
    from anthropic.types.beta import BetaToolUseBlock

    from monkey.automation.browser import Element

    g = PermissionGate()
    sess = FakeSession(g, [Element("e2", "button", "Continue")])
    blocks = [BetaToolUseBlock(type="tool_use", id="toolu_1", name="left_click", toolset_name="browser",
                               input={"target": {"type": "ref", "ref": "ref_e2"}})]
    r = ClaudePlanner(fake_client(blocks)).step(planner_task(), sess, sess.obs, ["did a thing"] * 20)
    assert sess.acted == ['click button "Continue"'] and r.acted == 1
    prompt = build_prompt(planner_task(), sess.obs, ["step"] * 20)
    assert prompt.count("- step") == 6 and "<untrusted_page>" in prompt and "allowed sites=127.0.0.1" in prompt


def test_evidence_must_be_on_the_page():
    from monkey.automation.browser import Observation

    obs = Observation(title="Done", text="All 4 modules are complete.")
    assert evidence_on_page("all 4 modules are complete", obs)
    assert not evidence_on_page("Course passed with 100%", obs) and not evidence_on_page("", obs)

"""The task helper's hard limits, approval rules, templates and routing (no browser, no network).

Near-misses are tested next to every refusal (docs/agent-lessons.md: test a filter against legitimate near-misses
before shipping it)."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from monkey.automation import templates as T
from monkey.automation.limits import blocked_host, check_goal
from monkey.automation.permissions import Action, PermissionGate, Risk, Target, action_kind, classify, url_allowed
from monkey.automation.tasks import Task


# --------------------------------------------------------------------------------------------- the refusal list
@pytest.mark.parametrize("goal,limit", [
    ("log into my bank and check my balance", "banking"),
    ("pay my credit card bill on the chase site", "banking"),
    ("send $20 to Sam on Venmo", "banking"),
    ("transfer money from savings to checking", "banking"),
    ("buy some bitcoin on coinbase", "banking"),
    ("like the last 10 posts on my Instagram feed", "social"),
    ("keep my snapchat streaks going while I'm away", "social"),
    ("enter my credit card number at checkout", "payment_details"),
    ("fill in my billing info and card details on the order page", "payment_details"),
    ("change my Gmail password to something stronger", "security"),
    ("turn off two-factor on my school account", "security"),
    ("update my recovery phone number in my Google account", "security"),
])
def test_forbidden_goals_are_refused_with_a_clear_message(goal, limit):
    r = check_goal(goal)
    assert r is not None and r.limit == limit, goal
    assert len(r.message) > 20 and r.message.endswith(".")


@pytest.mark.parametrize("goal", [
    "cancel my Spotify free trial reminder",
    "find the cheapest flight from Madison to Denver on Dec 18, just show me",
    "fill in this form with my info, let me review",
    "is Monday a bank holiday? check the post office site",
    "unsubscribe me from Instagram's marketing emails",         # about mail, not automating the app
    "stop getting the Chase newsletter",
    "turn off promotional notifications in my Spotify settings",
    "work through the 4 modules of the Title IX training on Canvas",
    "download last month's phone bill PDF",
    "put a 2-pack of AA batteries in my Target cart",           # spending is a stop-and-ask, not a refusal
    "remind me to update my resume",
    "show me how to set up a pin on google maps",
])
def test_legitimate_near_misses_are_not_refused(goal):
    assert check_goal(goal) is None, goal


def test_forbidden_sites_by_domain_and_apps():
    assert check_goal("check something", "https://secure.chase.com/dashboard").limit == "banking"
    assert check_goal("look around", "", ["www.instagram.com"]).limit == "social"
    assert check_goal("tidy up", "", [], ["Bitwarden.exe"]) is not None
    assert blocked_host("chase.com") == "banking" and blocked_host("x.paypal.com") == "banking"
    assert blocked_host("notchase.com") == "" and blocked_host("instagram.com.evil.example") == ""


def test_gate_never_opens_a_forbidden_site_even_with_any_website_on():
    for url in ("https://www.chase.com/", "https://instagram.com/p/x", "https://www.paypal.com/signin"):
        ok, msg = url_allowed(url, ["*"])
        assert not ok and msg
    g = PermissionGate()
    t = Task(objective="o", allowed_domains=["*"])
    assert not g.authorize(t, Action("navigate", url="https://www.venmo.com/")).allowed
    # A redirect that lands on one: nothing is clicked there.
    d = g.authorize(t, Action("click", Target("button", "Continue")), page_url="https://secure.chase.com/x")
    assert not d.allowed and d.risk == Risk.FORBIDDEN
    assert url_allowed("https://www.target.com/cart", ["*"])[0]


# --------------------------------------------------------------------------------------------- the gate
@pytest.mark.parametrize("action,risk", [
    (Action("click", Target("link", "Change password")), Risk.FORBIDDEN),
    (Action("click", Target("button", "Two-factor authentication")), Risk.FORBIDDEN),
    (Action("click", Target("button", "Turn off 2-Step Verification")), Risk.FORBIDDEN),
    (Action("click", Target("link", "Security settings")), Risk.FORBIDDEN),
    (Action("type", Target("textbox", "Name on card"), "Ada"), Risk.FORBIDDEN),
    (Action("type", Target("textbox", "Card number"), "4111"), Risk.FORBIDDEN),
    (Action("type", Target("textbox", "IBAN"), "DE00"), Risk.FORBIDDEN),
    (Action("click", Target("button", "Place order")), Risk.HIGH),
    (Action("click", Target("button", "Start free trial")), Risk.HIGH),
    (Action("click", Target("button", "Upgrade")), Risk.HIGH),
    (Action("click", Target("button", "Book now")), Risk.HIGH),
    (Action("click", Target("button", "Submit application")), Risk.HIGH),
    # near-misses: still ordinary
    (Action("click", Target("link", "Password manager tips")), Risk.LOW),
    (Action("click", Target("button", "Next")), Risk.LOW),
    (Action("type", Target("searchbox", "Search flights"), "Denver"), Risk.MEDIUM),
    (Action("click", Target("link", "Current offers")), Risk.LOW),            # "rent" inside a word isn't spending
])
def test_classification_of_limits_and_spending(action, risk):
    assert classify(action)[0] == risk, action.describe()


def test_approval_card_says_what_the_step_does():
    assert action_kind(Action("click", Target("button", "Place order"))) == "spend"
    assert action_kind(Action("click", Target("button", "Send message"))) == "send"
    assert action_kind(Action("click", Target("button", "Delete account"))) == "delete"
    assert action_kind(Action("click", Target("button", "Submit application"))) == "submit"
    g = PermissionGate()
    t = Task(objective="o", allowed_domains=["*"])
    a = Action("click", Target("button", "Pay now"))
    d = g.authorize(t, a, "https://shop.example/checkout")
    assert d.needs_approval and d.kind == "spend"
    ap = g.request(t.id, a, "https://shop.example/checkout", d.risk)
    assert ap.public()["kind"] == "spend"
    g.approve(ap.id, ap.token)
    assert g.authorize(t, a, "https://shop.example/checkout").allowed                 # that exact step, once
    assert not g.authorize(t, a, "https://shop.example/checkout").allowed             # never a standing grant


def test_template_rules_only_ever_narrow_the_gate():
    g = PermissionGate()
    look = Task(objective="o", allowed_domains=["*"], rules=T.TEMPLATES["look_only"].rules_for())
    sub = Action("click", Target("button", "Submit"))
    d = g.authorize(look, sub, "https://x.example/")
    assert not d.allowed and not d.needs_approval and "look-only" in d.reason       # refused, not even asked
    assert g.authorize(look, Action("type", Target("searchbox", "Search"), "denver"), "https://x.example/").allowed
    assert g.authorize(look, Action("click", Target("link", "Results")), "https://x.example/").allowed

    settings = Task(objective="o", allowed_domains=["*"], rules=T.TEMPLATES["account_settings"].rules_for())
    d = g.authorize(settings, Action("click", Target("checkbox", "Promotional emails")), "https://x.example/")
    assert d.needs_approval                                                          # every change asks

    unsub = Task(objective="o", allowed_domains=["list.example"], start_url="https://list.example/u",
                 rules=T.TEMPLATES["unsubscribe_page"].rules_for(type_only=["me@example.com"]))
    page = "https://list.example/u"
    assert g.authorize(unsub, Action("click", Target("button", "Unsubscribe")), page).allowed
    assert g.authorize(unsub, Action("click", Target("button", "Confirm")), page).allowed
    assert g.authorize(unsub, Action("type", Target("textbox", "Email"), "me@example.com"), page).allowed
    for a in (Action("click", Target("button", "Sign up for more deals")),
              Action("click", Target("button", "Subscribe")),
              Action("click", Target("link", "See today's offer")),
              Action("type", Target("textbox", "Email"), "someone@else.example"),
              Action("type", Target("textbox", "Comments"), "please remove me"),
              Action("navigate", url="https://list.example/other")):
        d = g.authorize(unsub, a, page)
        assert not d.allowed and not d.needs_approval, a.describe()


# --------------------------------------------------------------------------------------------- templates
@pytest.mark.parametrize("goal,tid", [
    ("find the cheapest flight from Madison to Denver on Dec 18, just show me", "look_only"),
    ("fill in this form with my info, let me review", "form_fill"),
    ("cancel my Spotify free trial reminder", "account_settings"),
    ("turn off promotional notifications on my phone carrier's site", "account_settings"),
    ("put a 2-pack of AA batteries in my Target cart", "shopping"),
    ("download last month's phone bill PDF", "generic"),
    ("work through the modules on canvas", "generic"),              # course is the owner's pick, never automatic
])
def test_template_picking(goal, tid):
    assert T.pick(goal).id == tid


def test_unsubscribe_goals_go_to_the_mailing_lists_review():
    assert T.panel_for("unsubscribe me from the Medium newsletter") == "mailing_lists"
    assert T.panel_for("stop getting these emails from SnackBox") == "mailing_lists"
    assert T.panel_for("unsubscribe me", "https://list.example/u") == ""             # a page was given: a task
    assert T.panel_for("cancel my gym membership") == ""
    ids = [t["id"] for t in T.listing()]
    assert "course" in ids and "generic" in ids and "unsubscribe_page" not in ids    # only batches start that one


def test_unsubscribe_step_picks_the_unsubscribe_button_not_the_decoy():
    from monkey.automation.computer.model import ElementRef, View

    els = [ElementRef("b1:1", "browser", "b1", "1", "button", "Sign up for more deals"),
           ElementRef("b1:2", "browser", "b1", "2", "textbox", "Your email", input_type="email"),
           ElementRef("b1:3", "browser", "b1", "3", "link", "Update preferences"),
           ElementRef("b1:4", "browser", "b1", "4", "button", "Unsubscribe")]
    v = View("browser", "b1", "Prefs", "https://x.example", els, text="We're sad to see you go")
    task = Task(objective="o", rules={"type_only": ["me@example.com"]})
    p = T.unsubscribe_step(v, {}, task)
    assert [(c["name"], c["input"]["id"]) for c in p.calls] == [("type_text", "b1:2"), ("click", "b1:4")]
    assert p.calls[0]["input"]["text"] == "me@example.com"
    done = T.unsubscribe_step(View("browser", "b1", "Done", "", [], text="You have been unsubscribed."), {}, task)
    assert done.status == "done" and "unsubscribed" in done.evidence
    assert T.unsubscribe_step(View("browser", "b1", "?", "", [els[0]], text="Deals!"), {}, task) is None


# --------------------------------------------------------------------------------------------- service + brain
def _service(enabled=True):
    from monkey.automation.service import AutomationService

    app = NS(cfg=NS(settings=NS(computer_access=enabled, automation_browser="chrome", chrome_bridge_port=0),
                    data_dir="."), ui=NS(emit=lambda n, p: None))
    return AutomationService(app)


def test_service_refuses_forbidden_tasks_before_anything_starts():
    svc = _service()
    for goal, limit in (("log into my bank and pay my credit card bill", "banking"),
                        ("post this photo to my instagram", "social"),
                        ("reset my password on the school portal", "security")):
        r = svc.start(goal, "", ["*"], skill="general")
        assert not r["ok"] and r["refused"] == limit and svc._mgr is None    # nothing was even built


def test_brain_propose_refuses_and_routes_unsubscribe_to_the_review():
    from monkey.brain.tools import Services, ToolRunner

    events = []

    class Mailing:
        def stale(self):
            return False

        def scan_async(self):
            events.append(("scan", {}))

        def state(self):
            return {"lists": [{"id": "ml_1", "sender": "Medium Daily Digest", "account_label": "Personal",
                               "count_90d": 60, "unread_90d": 59, "status": "active", "methods": ["one_click"]}],
                    "suggestions": [{"say": "You get about 20 emails a month from Medium Daily Digest and never "
                                            "open them."}], "scanning": False}

        def find(self, names):
            return [r for r in self.state()["lists"] if any(n.lower() in r["sender"].lower() for n in names)]

    tr = ToolRunner(Services(emit=lambda n, p: events.append((n, p)), memory=None, approval=None, mailing=Mailing()))
    out = tr.t_propose_computer_task("change my instagram password", "")
    assert out.startswith("Refused") and not events
    tr.t_propose_computer_task("cancel my Spotify free trial reminder", "")
    assert events[-1] == ("automation_propose", {"objective": "cancel my Spotify free trial reminder",
                                                 "start_url": "", "template": "account_settings"})
    got = tr.t_propose_unsubscribe(["Medium"])
    assert events[-1] == ("mailing_review", {"ids": ["ml_1"]}) and got["selected"][0]["method"] == "one_click"
    assert "nothing has been done" in got["note"]
    r = tr.run("find_mailing_lists", {"refresh": False})
    assert "Medium Daily Digest" in r[0] and "find_mailing_lists" in tr.untrusted      # email data is untrusted
    tr.t_propose_computer_task("unsubscribe me from the Medium newsletter", "")
    assert events[-1][0] == "mailing_review"


@pytest.mark.parametrize("text,task", [
    ("unsubscribe me from the Medium newsletter", "task_helper"),
    ("stop getting these emails from SnackBox", "task_helper"),
    ("cancel my Spotify free trial reminder", "task_helper"),
    ("go on the gym's website and cancel my membership", "task_helper"),
    ("fill out the club sign-up form for me", "task_helper"),
    ("remind me to cancel my gym membership", "todo"),                  # near-misses keep their routes
    ("read me the newsletter from my professor", None),
    ("what's on the website for my class", None),
    ("open canvas", "command"),
    ("draft an email to my professor", "draft_email"),
])
def test_router_sends_task_helper_requests_to_the_task_helper(text, task):
    from monkey.brain.router import rule_task

    assert rule_task(text)[0] == task


def test_policy_and_calibration_know_the_task_helper():
    from monkey.brain.calibrate import FAKE, SAMPLES
    from monkey.brain.policy import ModelPolicy
    from monkey.brain.router import CLASSIFIER_TASKS

    p = ModelPolicy()
    assert p.has("task_helper") and "task_helper" in CLASSIFIER_TASKS and "task_helper" in SAMPLES
    assert p.has("computer_task") and p.task("computer_task").get("internal")
    assert {"find_mailing_lists", "propose_unsubscribe", "propose_computer_task"} <= set(FAKE)


def test_persona_no_longer_limits_the_helper_to_canvas():
    from monkey.brain.agent import load_persona

    p = load_persona()
    assert "not just Canvas" in p and "propose_unsubscribe" in p and "Instagram" in p

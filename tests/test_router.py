import pytest

from monkey.brain.costs import HAIKU, OPUS, SONNET
from monkey.brain.policy import Choice
from monkey.brain.router import Route, Router, detect_importance, refine_task, rule_task


def r(text, classify=None, **kw):
    return Router(classify=classify, **kw).route(text)


def test_importance_words():
    assert detect_importance("this is important, take your time") == "high"
    assert detect_importance("quick question") == "low"
    assert detect_importance("what is photosynthesis") == "normal"


@pytest.mark.parametrize("text,task", [
    ("yo what's up", "chat"),
    ("open canvas", "command"),
    ("set a timer for 10 minutes", "command"),
    ("show me the weather forecast", "weather"),
    ("what's due this week", "assignments"),
    ("what should I work on tonight", "assignments"),
    ("check off HW 7", "check_off"),
    ("how did I sleep", "health"),
    ("what's my heart rate", "health"),
    ("what's on my calendar tomorrow", "calendar"),
    ("remember that my mom's birthday is May 3", "memory_note"),
    ("read my latest email from Professor Lee", "read_email"),
    ("any important emails?", "triage"),
    ("how's my day look", "briefing"),
    ("explain how vaccines work", "study_help"),
    ("draft an email to my professor saying I'll be late", "draft_email"),
    ("research the best laptops for engineering students", "research"),
    ("draw me a picture of a banana spaceship", "image_request"),
    ("who won the badgers game", "web_lookup"),
])
def test_rules_pick_tasks(text, task):
    assert rule_task(text)[0] == task


def test_everyday_talk_and_lookups_go_to_haiku():
    for q in ["yo what's up", "open canvas", "what's due this week", "how did I sleep", "show me the weather forecast",
              "who won the badgers game"]:
        assert r(q).model == HAIKU, q


def test_email_drafting_uses_opus_even_if_quick():
    route = r("quick, draft an email to my professor saying I'll be late")
    assert route.model == OPUS and route.effort == "low" and route.tier == "min"


def test_important_uses_task_max():
    route = r("This is important: draft an email to my advisor about switching majors")
    assert (route.model, route.effort, route.tier) == (OPUS, "high", "max")
    assert r("how did I sleep? this is important").model == SONNET


def test_classifier_used_when_no_rule():
    calls = []

    def classify(text):
        calls.append(text)
        return "hard_problem", 5, False, "proof"

    route = r("Why is the halting problem undecidable, and how does it relate to Rice's theorem", classify)
    assert calls and route.task == "hard_problem" and route.model == OPUS


def test_classifier_needs_web_goes_to_web_lookup():
    route = r("Which dining halls on campus serve sushi", lambda t: ("general", 2, True, "web"))
    assert route.task == "web_lookup"


def test_classifier_failure_defaults_to_general():
    def boom(t):
        raise RuntimeError("offline")

    route = r("Why do cats purr when they're happy", boom)
    assert route.task == "general" and route.model == SONNET


def test_refine_task():
    assert refine_task("general", 1, False) == "quick_fact"
    assert refine_task("general", 5, False) == "hard_problem"
    assert refine_task("quick_fact", 2, True) == "web_lookup"
    assert refine_task("general", 4, True) == "research"
    assert refine_task("draft_email", 5, False) == "draft_email"


def test_quick_uses_task_min():
    route = r("quick: explain how vaccines work")
    assert route.tier == "min" and route.model == SONNET


def test_budget_guard_stays_in_task_range():
    over = Router(budget_usd=lambda: 10, spent_usd=lambda: 12)
    route = over.route("research the best laptops for engineering students")
    assert (route.model, route.effort) == (SONNET, "medium")      # research min, not Haiku
    assert over.route("research laptops, this is important").model == OPUS
    near = Router(budget_usd=lambda: 10, spent_usd=lambda: 9.5)
    nr = near.route("research the best laptops")
    assert (nr.model, nr.effort) == (OPUS, "low") and "near monthly budget" in nr.reason


def test_forced_model():
    assert Router(forced_model=lambda: SONNET).route("research anything").model == SONNET


def test_escalate_steps_up():
    router = Router()
    base = router.route("hey")
    up = router.escalate(base)
    assert up.model == SONNET
    assert router.escalate(router.route("explain photosynthesis")).model == OPUS


def test_saver_profile_uses_min():
    saver = Router(profile=lambda: "saver")
    assert saver.route("research the best laptops for engineering students").model == SONNET
    assert saver.route("yo what's up").model == HAIKU


def test_sticky_follow_up_keeps_model_in_range():
    router = Router()
    prev = Route(SONNET, "low", "normal", "read_email", "x")
    follow = router.route("what's due this week", sticky=prev)      # assignments range is Haiku..Sonnet
    assert follow.model == SONNET and "stayed on" in follow.reason
    prev_opus = Route(OPUS, "medium", "normal", "research", "x")
    assert router.route("yo thanks", sticky=prev_opus).model == HAIKU  # Opus is out of range for chat


def test_policy_step_down_never_below_min():
    p = Router().policy
    assert p.step_down("draft_email", Choice(OPUS, "low")) == Choice(OPUS, "low")
    assert p.step_down("research", Choice(OPUS, "medium")) == Choice(OPUS, "low")

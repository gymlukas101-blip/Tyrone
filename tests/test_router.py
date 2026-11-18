from monkey.brain.costs import HAIKU, OPUS, SONNET
from monkey.brain.router import Router, detect_importance, rule_level


def r(text, classify=None, **kw):
    return Router(classify=classify, **kw).route(text)


def test_importance_words():
    assert detect_importance("this is important, take your time") == "high"
    assert detect_importance("quick question") == "low"
    assert detect_importance("what is photosynthesis") == "normal"


def test_small_talk_and_commands_go_to_haiku():
    assert r("yo what's up").model == HAIKU
    assert r("open canvas").model == HAIKU
    assert r("set a timer for 10 minutes").model == HAIKU


def test_command_needing_web_avoids_haiku():
    assert r("show me the weather forecast").model == SONNET


def test_email_drafting_uses_opus_even_if_quick():
    route = r("quick, draft an email to my professor saying I'll be late")
    assert route.model == OPUS and route.effort == "medium"


def test_important_bumps_up():
    route = r("This is important: draft an email to my advisor about switching majors")
    assert route.model == OPUS and route.effort in ("high", "xhigh")


def test_important_bumps_small_question_to_opus():
    assert r("what's 15% of 80? this is important").model == OPUS


def test_classifier_used_when_no_rule():
    calls = []

    def classify(text):
        calls.append(text)
        return 5, False, "proof"

    route = r("Prove that the halting problem is undecidable and relate it to Rice's theorem", classify)
    assert calls and route.model == OPUS and route.effort == "high"


def test_classifier_needs_web_never_haiku():
    route = r("Which dining halls on campus serve sushi", lambda t: (1, True, "web"))
    assert route.model != HAIKU


def test_classifier_failure_defaults_to_sonnet():
    def boom(t):
        raise RuntimeError("offline")

    route = r("Explain the difference between mitosis and meiosis for my bio exam", boom)
    assert route.model == SONNET


def test_quick_caps_level():
    route = r("quick: explain how vaccines work", lambda t: (4, False, "x"))
    assert route.model in (HAIKU, SONNET) and route.level <= 1


def test_budget_guard():
    over = Router(budget_usd=lambda: 10, spent_usd=lambda: 12)
    assert over.route("research the best laptops for engineering students").model == HAIKU
    assert over.route("research laptops, this is important").model == OPUS
    near = Router(budget_usd=lambda: 10, spent_usd=lambda: 9.5)
    assert near.route("research the best laptops for engineering students").model == SONNET


def test_forced_model():
    assert Router(forced_model=lambda: SONNET).route("research anything").model == SONNET


def test_escalate_steps_up():
    router = Router()
    base = router.route("hey")
    assert router.escalate(base).model == SONNET


def test_rule_level_none_for_open_question():
    assert rule_level("why do cats purr")[0] is None

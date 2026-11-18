from types import SimpleNamespace as NS

from monkey.brain.calibrate import SAMPLES, Calibration, apply_picks, estimate_cost, plan
from monkey.brain.costs import HAIKU, SONNET, Ledger
from monkey.brain.policy import Choice, ModelPolicy


class Stream:
    def __init__(self, content, stop):
        self.content, self.stop = content, stop

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for b in self.content:
            if b.type == "text":
                yield NS(type="text", text=b.text)

    def get_final_message(self):
        return NS(content=self.content, stop_reason=self.stop, model="m",
                  usage=NS(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0,
                           cache_creation_input_tokens=0, server_tool_use=None))


class Client:
    """Calls a tool on the first round of every run, then answers. Records tool names it was offered."""

    def __init__(self):
        self.calls = []
        self.beta = NS(messages=NS(stream=self.stream))

    def stream(self, **params):
        self.calls.append(params)
        last = params["messages"][-1]
        if last["role"] == "user" and isinstance(last["content"], list) and last["content"][0].get("type") == "text":
            return Stream([NS(type="tool_use", name="draft_email", id="t1",
                              input={"account": "gmail", "to": ["x@wisc.edu"], "cc": [], "subject": "s",
                                     "body": "b", "reply_to_id": ""})], "tool_use")
        return Stream([NS(type="text", text="All set. Here's the answer.")], "end_turn")


def test_plan_covers_every_task_with_unique_candidates():
    p = ModelPolicy()
    jobs = plan(p)
    assert {t for t, _ in jobs} == set(SAMPLES)
    for task in SAMPLES:
        cands = [c for t, c in jobs if t == task]
        assert len(cands) == len(set(cands)) and 1 <= len(cands) <= 3
    assert 1 < estimate_cost(p) < 8


def test_calibration_runs_with_stubbed_tools_and_records(tmp_path):
    p = ModelPolicy(tmp_path / "model_policy.json")
    ledger = Ledger(tmp_path / "db.sqlite")
    ledger.put_state("conversation", {"history": [{"role": "user", "content": "real chat"}]}, 1e12)
    progress = []
    cal = Calibration(Client(), p, ledger, tmp_path / "calibration.json", progress.append)
    out = cal.run()
    assert out["complete"] and progress[-1].get("finished")
    run = out["tasks"]["draft_email"]["runs"][0]
    assert run["answer"].startswith("All set") and run["usd"] > 0 and not run["error"]
    # Stubs only: the draft tool returned fake text, the real conversation state is untouched,
    # and spend is labeled as calibration.
    assert ledger.get_state("conversation")[0]["history"][0]["content"] == "real chat"
    import sqlite3
    purposes = {r[0] for r in sqlite3.connect(tmp_path / "db.sqlite").execute("SELECT purpose FROM spend")}
    assert purposes == {"calibration"}


def test_cancel_stops_early(tmp_path):
    p = ModelPolicy(tmp_path / "model_policy.json")
    cal = Calibration(Client(), p, Ledger(tmp_path / "db.sqlite"), tmp_path / "c.json")
    cal.cancel.set()
    out = cal.run()
    assert out["complete"] is False and out["tasks"] == {}


def test_apply_picks(tmp_path):
    p = ModelPolicy(tmp_path / "model_policy.json")
    results = {"date": "2026-11-18", "tasks": {
        "general": {"runs": [
            {"model": HAIKU, "effort": "medium", "usd": 0.001, "first_words_s": 1.0, "total_s": 2.0, "error": ""},
            {"model": SONNET, "effort": "low", "usd": 0.008, "first_words_s": 1.5, "total_s": 3.0, "error": ""}]},
        "chat": {"runs": [
            {"model": HAIKU, "effort": "low", "usd": 0.0001, "first_words_s": 0.6, "total_s": 0.9, "error": ""},
            {"model": SONNET, "effort": "low", "usd": 0.002, "first_words_s": 1.2, "total_s": 1.8, "error": ""}]}}}
    changed = apply_picks(p, results, {"general": "all", "chat": 1})
    assert changed == ["chat"]
    reloaded = ModelPolicy(tmp_path / "model_policy.json")
    assert reloaded.choice("general") == Choice(HAIKU, "medium")
    assert reloaded.task("general")["measured"]["usd"] == 0.001
    assert reloaded.choice("chat") == Choice(SONNET, "low")


# ------------------------------------------------------------------ fixes from the first real run
from monkey.brain.calibrate import _StubTools  # noqa: E402
from monkey.brain.ranking import RankedItem, Ranking  # noqa: E402


def test_warm_up_runs_once_per_model_and_is_not_in_results(tmp_path):
    p = ModelPolicy(tmp_path / "model_policy.json")
    client = Client()
    cal = Calibration(client, p, Ledger(tmp_path / "db.sqlite"), tmp_path / "c.json", tasks=["chat"])
    out = cal.run()
    models_in_plan = {c.model for t, c in plan(p) if t == "chat"}
    warmups = [c for c in client.calls
               if len(c["messages"]) == 1 and c["messages"][0]["content"][0]["text"].endswith("\nhi")]
    assert len(warmups) == len(models_in_plan)
    assert list(out["tasks"]) == ["chat"] and len(out["tasks"]["chat"]["runs"]) == len(models_in_plan)


def test_drafts_are_captured_for_review(tmp_path):
    p = ModelPolicy(tmp_path / "model_policy.json")
    out = Calibration(Client(), p, Ledger(tmp_path / "db.sqlite"), tmp_path / "c.json", tasks=["draft_email"],
                      warm_up=False).run()
    o = out["tasks"]["draft_email"]["runs"][0]["outputs"][0]
    assert o["kind"] == "Email draft" and o["to"] == "x@wisc.edu" and o["text"] == "b"


def test_rerun_keeps_other_tasks(tmp_path):
    p = ModelPolicy(tmp_path / "model_policy.json")
    f = tmp_path / "c.json"
    Calibration(Client(), p, Ledger(tmp_path / "db"), f, tasks=["chat"], warm_up=False).run()
    out = Calibration(Client(), p, Ledger(tmp_path / "db"), f, tasks=["weather"], warm_up=False).run()
    assert set(out["tasks"]) == {"chat", "weather"} and out["rerun"] == ["weather"]


def test_two_samples_average_cost(tmp_path):
    p = ModelPolicy(tmp_path / "model_policy.json")
    out = Calibration(Client(), p, Ledger(tmp_path / "db"), tmp_path / "c.json", tasks=["chat"], samples=2,
                      warm_up=False).run()
    assert out["tasks"]["chat"]["runs"][0]["samples"] == 2


def test_triage_ranking_really_runs_with_candidate_model(tmp_path):
    seen = {}

    def parse(**kw):
        seen.update(kw)
        return NS(parsed_output=Ranking(items=[RankedItem(id="e1", tier="critical", reason="missing lab")],
                                        summary="Reply to Prof. Lee first."), stop_reason="end_turn",
                  usage=NS(input_tokens=2000, output_tokens=300, cache_read_input_tokens=0,
                           cache_creation_input_tokens=0, server_tool_use=None))

    client = NS(messages=NS(parse=parse))
    tools = _StubTools(client, Choice(SONNET, "medium"), Ledger(tmp_path / "db"))
    out, err = tools.run("rank_items", {"days_ahead": 2, "include_emails": True})
    assert not err and "Reply to Prof. Lee first." in out and "BIO 151 lab report" in out
    assert seen["model"] == SONNET and seen["output_config"]["effort"] == "medium"
    assert tools.extra_usd > 0


def test_stub_texts_dont_mention_calibration():
    tools = _StubTools()
    for name in ("draft_email", "escalate", "open_website"):
        text, _ = tools.run(name, {"to": [], "subject": "", "body": ""} if name == "draft_email" else {})
        assert "calibration" not in text.lower() and "test run" not in text.lower()


def test_pick_index_matches_screen_even_with_errors(tmp_path):
    p = ModelPolicy(tmp_path / "model_policy.json")
    results = {"tasks": {"general": {"runs": [
        {"model": HAIKU, "effort": "medium", "usd": 0.0, "first_words_s": 0, "total_s": 0, "error": "boom"},
        {"model": SONNET, "effort": "low", "usd": 0.008, "first_words_s": 1.5, "total_s": 3.0, "error": ""}]}}}
    apply_picks(p, results, {"general": 1})
    assert p.choice("general") == Choice(SONNET, "low")
    apply_picks(p, results, {"general": 0})            # picking a failed run changes nothing
    assert p.choice("general") == Choice(SONNET, "low")

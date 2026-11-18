import json

import pytest

from monkey.brain.costs import HAIKU, OPUS, SONNET
from monkey.brain.policy import Choice, ModelPolicy, estimate, load_defaults
from monkey.memory.store import MonkeyMemory


def test_defaults_are_valid_and_ordered():
    p = ModelPolicy()
    for row in p.table():
        lo, mid, hi = (Choice(row[t]["model"], row[t]["effort"]) for t in ("min", "default", "max"))
        assert p.in_range(row["id"], mid), row["id"]
        assert row["min"]["usd"] <= row["default"]["usd"] <= row["max"]["usd"] + 1e-9, row["id"]


def test_everyday_tasks_default_to_haiku_and_heavy_to_opus():
    p = ModelPolicy()
    for t in ("chat", "command", "assignments", "health", "calendar", "weather", "web_lookup"):
        assert p.choice(t).model == HAIKU, t
    assert p.choice("draft_email") == Choice(OPUS, "medium")
    assert p.choice("research") == Choice(OPUS, "medium")
    assert p.choice("triage") == Choice(SONNET, "medium")


def test_monthly_total_fits_max_credits():
    p = ModelPolicy()
    assert 15 < p.monthly_total() < 40
    assert p.monthly_total("max") < 95


def test_user_override_merges_and_survives_reload(tmp_path):
    f = tmp_path / "model_policy.json"
    p = ModelPolicy(f)
    p.set_entry("study_help", "default", OPUS, "high")
    assert ModelPolicy(f).choice("study_help") == Choice(OPUS, "high")
    assert ModelPolicy(f).choice("chat") == Choice(HAIKU, "low")      # untouched tasks keep shipped values
    p.reset("study_help")
    assert ModelPolicy(f).choice("study_help") == Choice(SONNET, "medium")


def test_bad_entries_rejected_and_ignored(tmp_path):
    f = tmp_path / "model_policy.json"
    p = ModelPolicy(f)
    with pytest.raises(ValueError):
        p.set_entry("chat", "default", "gpt-5", "low")
    with pytest.raises(ValueError):
        p.set_entry("nope", "default", HAIKU, "low")
    f.write_text(json.dumps({"tasks": {"chat": {"default": ["claude-haiku-5-5", "ultra"]}}}), encoding="utf-8")
    assert ModelPolicy(f).choice("chat") == Choice(HAIKU, "low")


def test_estimate_scales_with_model_and_effort():
    est = load_defaults()["tasks"]["study_help"]["est"]
    h, s, o = (estimate(est, Choice(m, "medium"))["usd"] for m in (HAIKU, SONNET, OPUS))
    assert h < s < o
    assert estimate(est, Choice(OPUS, "low"))["usd"] < estimate(est, Choice(OPUS, "high"))["usd"]
    assert estimate(est, Choice(HAIKU, "low"))["first_words_s"] < estimate(est, Choice(OPUS, "high"))["first_words_s"]


def test_memory_note(tmp_path):
    mem = MonkeyMemory(tmp_path / "memory")
    ModelPolicy().write_memory_note(mem)
    note = mem.read("model_policy.md")
    assert "Draft an email in your voice: Auto Opus 5.5 · medium" in note
    assert "Chit-chat" in note and "monthly cost" in note


def test_docs_table_matches_policy():
    from pathlib import Path

    doc = Path(__file__).resolve().parents[1].joinpath("docs", "MODEL-POLICY.md").read_text(encoding="utf-8")
    p = ModelPolicy()
    assert f"Auto **${p.monthly_total():.2f}**" in doc, "re-run: python -m tools.model_policy.report"
    for row in p.table():
        assert row["label"] in doc


def test_persona_has_calibration_fixes():
    from monkey.brain.agent import load_persona

    persona = load_persona()
    assert "Don't assume anyone's gender" in persona
    assert "Small talk" in persona and "offer to draft the reply" in persona


def test_calibrated_policy_changes():
    p = ModelPolicy()
    assert p.choice("calendar") == Choice(HAIKU, "low")
    assert p.choice("general") == Choice(HAIKU, "medium")
    assert p.choice("image_request") == Choice(HAIKU, "low")
    assert p.choice("read_email") == Choice(SONNET, "low")

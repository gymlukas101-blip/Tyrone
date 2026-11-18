from datetime import datetime, timedelta, timezone

import pytest

from tyrone.brain.costs import HAIKU, OPUS, Ledger, Usage, cost_usd
from tyrone.brain.ranking import heuristic_score, heuristic_tier, rank_items
from tyrone.brain.speech_text import SentenceChunker, speakable
from tyrone.brain.tools import resolve_site
from tyrone.integrations.base import Email, Event
from tyrone.memory.export import export_bundle, import_bundle
from tyrone.memory.store import TyroneMemory


def test_memory_seed_and_tool_commands(tmp_path):
    mem = TyroneMemory(tmp_path / "memory")
    assert "profile.md" in mem.files()
    out = mem.call({"command": "view", "path": "/memories"})
    assert "profile.md" in str(out)
    mem.call({"command": "create", "path": "/memories/notes.md", "file_text": "likes tacos"})
    assert mem.read("notes.md") == "likes tacos"
    mem.call({"command": "str_replace", "path": "/memories/notes.md", "old_str": "tacos", "new_str": "ramen"})
    assert "ramen" in mem.read("notes.md")
    with pytest.raises(Exception):
        mem.call({"command": "view", "path": "/memories/../../etc/passwd"})


def test_site_shortcuts(tmp_path):
    mem = TyroneMemory(tmp_path / "memory")
    s = mem.site_shortcuts()
    assert resolve_site("Canvas", s) == "https://canvas.wisc.edu"
    assert resolve_site("course search", s).startswith("https://public.enroll.wisc.edu")
    assert resolve_site("espn.com", s) == "https://espn.com"
    assert resolve_site("badgers hockey schedule", s).startswith("https://www.google.com/search?q=")
    with pytest.raises(ValueError):
        resolve_site("file:///C:/Windows", s)


def test_export_import_roundtrip(tmp_path):
    data = tmp_path / "a"
    mem = TyroneMemory(data / "memory")
    mem.write("profile.md", "secret fact")
    (data / "settings.json").write_text("{}")
    bundle = export_bundle(data, data / "memory", tmp_path / "x.tyrone", "correct horse")
    assert b"secret fact" not in bundle.read_bytes()
    with pytest.raises(ValueError):
        import_bundle(bundle, tmp_path / "b", tmp_path / "b" / "memory", "wrong password")
    restored = import_bundle(bundle, tmp_path / "b", tmp_path / "b" / "memory", "correct horse")
    assert any("profile.md" in r for r in restored)
    assert (tmp_path / "b" / "memory" / "memories" / "profile.md").read_text() == "secret fact"


def test_costs_and_ledger(tmp_path):
    u = Usage(input_tokens=1_000_000, output_tokens=100_000)
    assert cost_usd(OPUS, u) == pytest.approx(6.0)
    assert cost_usd(HAIKU, u) == pytest.approx(0.15)
    led = Ledger(tmp_path / "t.db")
    led.record(OPUS, "low", "chat", u)
    assert led.month_to_date() == pytest.approx(6.0)


def test_sentence_chunker():
    c = SentenceChunker()
    out = []
    for piece in ["Yo, here's the deal. The exam is ", "on **Friday** at 9am. ", "Check [Canvas](https://canvas.wisc.edu)!"]:
        out += c.feed(piece)
    out += c.flush()
    assert out[0].startswith("Yo, here's the deal.")
    assert "**" not in " ".join(out) and "https" not in " ".join(out)
    assert speakable("- item one\n- item two") == "item one\nitem two"


def test_heuristic_ranking():
    now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
    exam = Event("e1", "canvas", "CS 400 Midterm Exam", now + timedelta(hours=20))
    promo = Email("m1", "gmail", "Store", "deals@store.com", [], "50% off sale!", "unsubscribe", now, True)
    prof = Email("m2", "outlook", "Prof. Smith", "smith@cs.wisc.edu", [], "Action required: project deadline", "",
                 now, True)
    assert heuristic_tier(heuristic_score(exam, now)) == "critical"
    assert heuristic_tier(heuristic_score(promo, now)) == "low"
    assert heuristic_score(prof, now) > heuristic_score(promo, now)
    ranking, usage = rank_items(None, [exam, promo, prof], now=now)
    assert usage is None and ranking.items[0].id == "e1"

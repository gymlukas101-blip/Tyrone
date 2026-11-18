from datetime import datetime, timedelta, timezone

import pytest

from monkey.brain.costs import HAIKU, OPUS, Ledger, Usage, cost_usd
from monkey.brain.ranking import heuristic_score, heuristic_tier, rank_items
from monkey.brain.speech_text import SentenceChunker, speakable
from monkey.brain.tools import resolve_site
from monkey.integrations.base import Email, Event
from monkey.memory.export import export_bundle, import_bundle
from monkey.memory.store import MonkeyMemory


def test_memory_seed_and_tool_commands(tmp_path):
    mem = MonkeyMemory(tmp_path / "memory")
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
    mem = MonkeyMemory(tmp_path / "memory")
    s = mem.site_shortcuts()
    assert resolve_site("Canvas", s) == "https://canvas.wisc.edu"
    assert resolve_site("course search", s).startswith("https://public.enroll.wisc.edu")
    assert resolve_site("espn.com", s) == "https://espn.com"
    assert resolve_site("badgers hockey schedule", s).startswith("https://www.google.com/search?q=")
    with pytest.raises(ValueError):
        resolve_site("file:///C:/Windows", s)


def test_export_import_roundtrip(tmp_path):
    data = tmp_path / "a"
    mem = MonkeyMemory(data / "memory")
    mem.write("profile.md", "secret fact")
    (data / "settings.json").write_text("{}")
    bundle = export_bundle(data, data / "memory", tmp_path / "x.monkey", "correct horse")
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
    # 1-hour cache writes cost 2x input; 5-minute writes 1.25x.
    assert cost_usd(OPUS, Usage(cache_creation_input_tokens=1_000_000, cache_creation_1h_tokens=1_000_000)) == pytest.approx(8.0)
    assert cost_usd(OPUS, Usage(cache_creation_input_tokens=1_000_000)) == pytest.approx(5.0)
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


def test_fish_voice_id_from_pasted_link():
    from monkey.audio.tts import explain_fish_error, normalize_voice_id

    vid = "4a396e7e91a640a2b1e0f06249cbcd14"
    assert normalize_voice_id(f"https://fish.audio/m/{vid}/") == vid
    assert normalize_voice_id(f"  {vid.upper()} ") == vid
    assert normalize_voice_id("") == ""
    assert "API key" in explain_fish_error(RuntimeError("Fish TTS 401: unauthorized"))
    assert "voice ID" in explain_fish_error(RuntimeError("Fish TTS 404: reference not found"))
    assert "credits" in explain_fish_error(RuntimeError("Fish TTS 402: insufficient balance"))


def test_speaker_reports_fallback():
    import numpy as np

    from monkey.audio.speaker import Speaker

    class Broken:
        def available(self):
            return True

        def stream_pcm(self, text):
            raise RuntimeError("Fish TTS 404: reference not found")
            yield  # pragma: no cover

    class Ok:
        def available(self):
            return True

        def stream_pcm(self, text):
            yield np.zeros(10, dtype=np.int16)

    seen = []
    sp = Speaker([Broken(), Ok()], on_level=lambda v: None, on_state=lambda s: None,
                 on_fallback=lambda name, exc: seen.append((name, str(exc))))
    sp.say("hello")
    import time
    for _ in range(50):
        if seen:
            break
        time.sleep(0.02)
    assert seen and seen[0][0] == "Broken" and "404" in seen[0][1]


# ------------------------------------------------------------------ Fish free model
class _FakeStream:
    def __init__(self, status, body=b""):
        self.status_code, self._body, self.text = status, body, body.decode(errors="ignore") if body else ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body

    def iter_bytes(self, n):
        yield self._body


def test_fish_paid_402_falls_back_to_free(monkeypatch):
    import httpx

    from monkey.audio import tts

    seen, switched = [], []

    def fake_stream(method, url, json=None, headers=None, timeout=None):
        seen.append(headers["model"])
        return _FakeStream(402, b'{"detail":"payment required"}') if headers["model"] == "s2.1-pro" \
            else _FakeStream(200, b"\x01\x00\x02\x00")

    monkeypatch.setattr(httpx, "stream", fake_stream)
    f = tts.FishTTS(lambda: "k", lambda: "https://fish.audio/m/4a396e7e91a640a2b1e0f06249cbcd14/", lambda: "s2.1-pro",
                    on_model_change=switched.append)
    chunks = list(f.stream_pcm("hi"))
    assert seen == ["s2.1-pro", "s2.1-pro-free"] and switched == ["s2.1-pro-free"] and len(chunks) == 1
    assert f.model() == "s2.1-pro-free"


def test_fish_429_retries_then_raises(monkeypatch):
    import httpx

    from monkey.audio import tts

    calls = []
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: calls.append(1) or _FakeStream(429, b"busy"))
    monkeypatch.setattr("time.sleep", lambda s: None)
    f = tts.FishTTS(lambda: "k", lambda: "", lambda: "s2.1-pro-free")
    import pytest
    with pytest.raises(RuntimeError, match="429"):
        list(f.stream_pcm("hi"))
    assert len(calls) == 3


def test_free_model_respects_privacy_toggle():
    from monkey.audio import tts

    assert not tts.FishTTS(lambda: "k", lambda: "", lambda: "s2.1-pro-free", allow_free=lambda: False).available()
    assert tts.FishTTS(lambda: "k", lambda: "", lambda: "s2.1-pro", allow_free=lambda: False).available()


def test_settings_migrate_to_free_model(tmp_path):
    import json

    from monkey.config import Config

    (tmp_path / "settings.json").write_text(json.dumps({"fish_model": "s2.1-pro"}))
    assert Config(tmp_path).settings.fish_model == "s2.1-pro-free"
    (tmp_path / "settings.json").write_text(json.dumps({"fish_model": "s2.1-pro", "fish_paid_confirmed": True}))
    assert Config(tmp_path).settings.fish_model == "s2.1-pro"


def test_voice_design_402_explained():
    from monkey.audio.tts import explain_fish_error

    msg = explain_fish_error(RuntimeError("voice-design Client error '402 Payment Required' for url"))
    assert "paid" in msg and "fish.audio website" in msg


def test_hung_voice_engine_falls_through_and_never_sticks(monkeypatch):
    """Regression: the Windows voice hung mid-sentence and Monkey stayed 'Talking' forever."""
    import threading
    import time

    import numpy as np

    from monkey.audio import speaker as spk

    monkeypatch.setattr(spk, "_deadline", lambda text: 0.3)
    forever = threading.Event()

    class Hangs:
        def available(self):
            return True

        def stream_pcm(self, text):
            forever.wait()          # never returns (like pyttsx3's runAndWait)
            yield np.zeros(1, dtype=np.int16)

    class Ok:
        def available(self):
            return True

        def stream_pcm(self, text):
            yield np.ones(100, dtype=np.int16)

    fell = []
    sp = spk.Speaker([Hangs(), Ok()], on_level=lambda v: None, on_state=lambda s: None,
                     on_fallback=lambda n, e: fell.append(n))
    sp.say("hello there")
    for _ in range(100):
        if not sp._audio.empty():
            break
        time.sleep(0.02)
    assert fell == ["Hangs"] and not sp._audio.empty()   # the second engine produced the sentence
    forever.set()


def test_speaker_watchdog_resets_stuck_speaking(monkeypatch):
    import time

    from monkey.audio import speaker as spk

    monkeypatch.setattr(spk, "STALL_S", 0.2)
    states = []
    sp = spk.Speaker([], on_level=lambda v: None, on_state=states.append)
    sp._set_speaking(True)
    sp._pending = 3                   # pretend sentences were lost
    sp._last_audio = time.monotonic() - 5
    for _ in range(40):
        if not sp.speaking:
            break
        time.sleep(0.1)
    assert not sp.speaking and states[-1] is False and sp._pending == 0

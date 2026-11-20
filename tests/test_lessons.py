"""The self-improvement loop: the collector finds failures, waste and owner corrections in run logs (redacted)."""
from __future__ import annotations

import json
from pathlib import Path

from tools.lessons.collect import digest, scan

ROOT = Path(__file__).resolve().parents[1]


def _log(tmp_path, events):
    f = tmp_path / "run.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    return f


def _assistant(text="", tool=None):
    content = [{"type": "text", "text": text}] if text else []
    if tool:
        content.append({"type": "tool_use", "id": "t", "name": tool[0], "input": tool[1]})
    return {"type": "assistant", "sessionId": "abc12345", "timestamp": "2026-11-20T10:00:00Z",
            "message": {"role": "assistant", "content": content}}


def _user(text=None, result=None, is_error=False):
    content = text if text is not None else [{"type": "tool_result", "tool_use_id": "t", "content": result,
                                               "is_error": is_error}]
    return {"type": "user", "sessionId": "abc12345", "timestamp": "2026-11-20T10:01:00Z",
            "message": {"role": "user", "content": content}}


def test_collector_finds_corrections_failures_and_waste_and_redacts(tmp_path):
    events = [
        _assistant("Shipped v0.3.66.", ("Bash", {"command": "pytest -q"})),
        _user(result="FAILED tests/test_x.py::test_y - AssertionError\n1 failed, 3 passed"),
        _assistant("All green, update is out."),
        _user(text="i keep clicking update but it's still at 0.3.66, my key is sk-ant-api03-abcdefghijklmnop"),
        *[_assistant("", ("Read", {"file_path": "/x/a.png"})) for _ in range(3)],
        _user(result="x" * 25_000),
        _user(text="no thanks"),
    ]
    inc = scan(_log(tmp_path, events))
    kinds = [i.kind for i in inc]
    assert kinds.count("failure") == 1 and kinds.count("correction") == 1 and kinds.count("waste") == 2
    text = digest(inc)
    assert "still at 0.3.66" in text and "after: All green" in text          # the correction, with what preceded it
    assert "sk-ant-api03" not in text                                         # secrets redacted
    assert "same Read call 3×" in text and "25,000 characters" in text


def test_every_agent_is_told_to_read_the_lessons():
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "docs/agent-lessons.md" in claude and "fix or retire" in claude
    lessons = (ROOT / "docs" / "agent-lessons.md").read_text(encoding="utf-8")
    assert "## Active rules" in lessons and "## Retired rules" in lessons
    assert "*Why:*" in lessons                                                 # every rule carries its reason

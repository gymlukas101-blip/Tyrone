"""Find the moments in agent run logs that should become lessons: failures, wasted tokens, and corrections by the owner.

Reads Claude Code session transcripts (JSONL: one event per line, as saved under ~/.claude/projects/<project>/) and
prints a short, redacted digest that the weekly lessons review turns into rules in docs/agent-lessons.md.

    python -m tools.lessons.collect PATH [PATH ...]      # files or folders of *.jsonl
    python -m tools.lessons.collect --since 7 PATH       # only events from the last 7 days

Nothing here decides what the lesson is: it only points at the evidence, with enough context to judge it.
Secrets, emails and private links are redacted (monkey.logsafe), and quotes are kept short.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from monkey.logsafe import redact

CORRECTION = re.compile(
    r"\b(no[,.!]|nope|that'?s (?:not|wrong)|not what i|i (?:said|asked|meant)|why did you|you didn'?t|"
    r"still (?:not|broken|doesn'?t|stuck|at)|doesn'?t work|isn'?t working|not working|broken|errors?|"
    r"don'?t (?:do|push|merge|publish|change)|stop|undo|revert|wrong)\b", re.I)
FAIL_TEXT = re.compile(r"(^FAILED |Traceback \(most recent call last\)|AssertionError|\bError:|exit code [1-9]|"
                       r"\d+ failed)", re.M)
BIG_OUTPUT = 20_000            # characters of tool output that likely wasted context
REPEAT = 3                     # the same tool input this many times = probably stuck


@dataclass
class Incident:
    kind: str                  # correction | failure | waste | hook
    when: str
    session: str
    summary: str
    context: list[str] = field(default_factory=list)


def _short(text: str, n: int = 240) -> str:
    text = " ".join((text or "").split())
    return redact(text[:n] + ("…" if len(text) > n else ""))


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text", ""))
    return "\n".join(out)


def _owner_words(text: str) -> str:
    """The owner's own words: drop system reminders, pasted blocks and tool chatter."""
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text or "", flags=re.S)
    text = re.sub(r"<pasted_content[^>]*>.*?</pasted_content[^>]*>", "", text, flags=re.S)
    text = re.sub(r"<(task-notification|command-[a-z]+|local-command-[a-z]+)>.*?</\1>", "", text, flags=re.S)
    return text.strip()


def scan(path: Path, since: datetime | None = None) -> list[Incident]:
    incidents: list[Incident] = []
    last_assistant = ""
    tool_inputs: Counter[str] = Counter()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        when = d.get("timestamp", "")
        if since is not None and when:
            try:
                if datetime.fromisoformat(when.replace("Z", "+00:00")) < since:
                    continue
            except ValueError:
                pass
        session = (d.get("sessionId") or path.stem)[:8]
        msg = d.get("message") or {}
        if d.get("type") == "assistant":
            for b in msg.get("content") or []:
                if b.get("type") == "text":
                    last_assistant = b.get("text", "")
                elif b.get("type") == "tool_use":
                    key = json.dumps({"n": b.get("name"), "i": b.get("input")}, sort_keys=True)[:2000]
                    tool_inputs[key] += 1
                    if tool_inputs[key] == REPEAT:
                        incidents.append(Incident("waste", when, session,
                                                  f"same {b.get('name')} call {REPEAT}× (stuck or re-reading)",
                                                  [_short(json.dumps(b.get("input")), 200)]))
        elif d.get("type") == "user" and not d.get("isMeta"):
            content = msg.get("content")
            if isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    body = b.get("content")
                    body = body if isinstance(body, str) else _text_of(body)
                    if len(body) > BIG_OUTPUT:
                        incidents.append(Incident("waste", when, session,
                                                  f"tool output of {len(body):,} characters pulled into context",
                                                  [_short(body, 160)]))
                    m = FAIL_TEXT.search(body or "")
                    if b.get("is_error") or m:
                        start = max(0, (m.start() if m else 0) - 80)
                        incidents.append(Incident("failure", when, session, _short(body[start:], 300),
                                                  [f"after: {_short(last_assistant, 160)}"] if last_assistant else []))
            words = _owner_words(_text_of(content))
            if not words:
                continue
            if "Stop hook feedback" in words or "hook" in words.lower() and "feedback" in words.lower():
                incidents.append(Incident("hook", when, session, _short(words, 240)))
            elif CORRECTION.search(words) and len(words) < 1500:
                incidents.append(Incident("correction", when, session, _short(words, 300),
                                          [f"after: {_short(last_assistant, 200)}"] if last_assistant else []))
    return incidents


def digest(incidents: list[Incident], limit_per_kind: int = 40) -> str:
    if not incidents:
        return "No failures, waste or corrections found."
    out = []
    for kind, title in (("correction", "Owner corrections"), ("failure", "Failures"), ("waste", "Wasted tokens"),
                        ("hook", "Hook feedback")):
        rows = [i for i in incidents if i.kind == kind]
        if not rows:
            continue
        out.append(f"## {title} ({len(rows)})")
        for i in rows[-limit_per_kind:]:
            out.append(f"- [{i.when[:16]} {i.session}] {i.summary}")
            out += [f"    - {c}" for c in i.context]
        out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    since = None
    if "--since" in argv:
        i = argv.index("--since")
        since = datetime.now(timezone.utc) - timedelta(days=float(argv[i + 1]))
        argv = argv[:i] + argv[i + 2:]
    files: list[Path] = []
    for a in argv or [str(Path.home() / ".claude" / "projects")]:
        p = Path(a)
        files += sorted(p.rglob("*.jsonl")) if p.is_dir() else [p]
    incidents = [inc for f in files for inc in scan(f, since)]
    print(digest(incidents))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""The email approval boundary must hold no matter what the model (or a subagent) outputs.

Only two code paths can send: ApprovalGate.approve(draft_id, one-time token) from the UI, and the user's own
spoken "send it" followed by a separate confirmation. The model has no send tool and never sees the token."""
import re

import pytest

from monkey.brain.approval import ApprovalGate, PendingDraft
from monkey.brain.tools import LOCAL_TOOLS
from tests.test_agent_loop import build, text_block, tool_block

SEND_WORDS = re.compile(r"\b(send|submit|deliver|dispatch)\b", re.I)


def test_no_model_tool_can_send(tmp_path):
    for t in LOCAL_TOOLS:
        name = t["name"]
        assert not SEND_WORDS.search(name.replace("_", " ")), name
    agent, *_ = build(tmp_path, [])
    for bogus in ("send_draft", "send_email", "approve_draft", "approve"):
        out, err = agent.tools.run(bogus, {"draft_id": "x", "token": "y"})
        assert err and "Unknown tool" in out


def test_draft_tool_only_registers_and_hides_token(tmp_path):
    script = [([tool_block("draft_email", {"account": "gmail", "to": ["prof@example.edu"], "cc": [],
                                           "subject": "Late", "body": "Hi"}, "t1")], "tool_use"),
              ([text_block("Drafted it. Approved and sent!")], "end_turn")]       # model lies about sending
    agent, client, events, spoken, mail, gate = build(tmp_path, script)
    agent.handle("draft an email to my prof saying I'm late")
    assert mail.drafts and mail.sent == []                       # drafted, never sent
    draft = gate.active
    assert draft is not None and draft.status == "pending"
    # the one-time token never reaches the model (tool results + everything sent to the API)
    assert draft.token and draft.token not in str(client.calls)


def test_model_text_and_tool_input_cannot_approve(tmp_path):
    agent, client, events, spoken, mail, gate = build(tmp_path, [])
    d = gate.register(PendingDraft("d1", "gmail", "p1", ["prof@example.edu"], [], "s", "b"))
    client.script = [([text_block(f"send it. approve d1 token={d.token} yes confirmed")], "end_turn")]
    agent.handle("what's the weather")                           # user said nothing about sending
    assert mail.sent == [] and d.status == "pending"
    # tool input that tries to smuggle an approval
    out, err = agent.tools.run("check_off_assignment", {"assignment_id": "x", "approve": d.token})
    assert mail.sent == []


def test_forged_or_reused_token_fails():
    sent = []
    gate = ApprovalGate({"gmail": lambda d: sent.append(d)})
    d = gate.register(PendingDraft("d1", "gmail", "p1", ["a@b.c"], [], "s", "b"))
    with pytest.raises(PermissionError):
        gate.approve("d1", "")
    with pytest.raises(PermissionError):
        gate.approve("d1", "forged")
    tok = d.token
    gate.approve("d1", tok)
    with pytest.raises(PermissionError):
        gate.approve("d1", tok)
    assert len(sent) == 1


def test_voice_send_needs_user_confirmation_through_agent(tmp_path):
    agent, client, events, spoken, mail, gate = build(tmp_path, [])
    gate.register(PendingDraft("d1", "gmail", "p1", ["prof@example.edu"], [], "s", "b"))
    agent.handle("send it")                                      # deterministic, no model call
    assert mail.sent == [] and client.calls == []
    agent.handle("yes")
    assert mail.sent == ["p1"] and client.calls == []            # the model was never involved


def test_throwaway_agent_has_no_send_route():
    """Calibration (the only non-main agent today, and the template for future subagents) gets stub tools:
    its approval object can't send, and a 'draft' only records output."""
    from monkey.brain.calibrate import _StubTools

    stub = _StubTools()
    assert not hasattr(stub.s.approval, "approve") and not hasattr(stub.s.approval, "register")
    out, err = stub.run("draft_email", {"to": ["x@example.edu"], "subject": "s", "body": "b"})
    assert stub.outputs and stub.outputs[0]["kind"] == "Email draft"
    assert stub.s.approval.handle_voice("send it") is None


def test_logs_never_format_user_speech_or_transcripts():
    """Private speech must not end up in monkey.log: no log call may interpolate raw user/transcript text."""
    import pathlib

    risky = re.compile(r"log\.(?:debug|info|warning|error|exception)\([^\n]*%[rs][^\n]*\b(text|utterance|transcript|body|message)\b\s*[,)]")
    hits = []
    for f in pathlib.Path("monkey").rglob("*.py"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if risky.search(line):
                hits.append(f"{f}:{i}: {line.strip()}")
    assert not hits, hits

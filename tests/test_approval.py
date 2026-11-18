import pytest

from monkey.brain.approval import ApprovalGate, PendingDraft


def make_gate():
    sent = []
    gate = ApprovalGate({"gmail": lambda d: sent.append(d.draft_id)})
    d = gate.register(PendingDraft("d1", "gmail", "prov1", ["prof@wisc.edu"], [], "Late to lab", "Hi Prof"))
    return gate, d, sent


def test_ui_approval_requires_token():
    gate, d, sent = make_gate()
    with pytest.raises(PermissionError):
        gate.approve("d1", "wrong")
    assert sent == []
    gate.approve("d1", d.token)
    assert sent == ["d1"]


def test_token_is_one_time():
    gate, d, sent = make_gate()
    tok = d.token
    gate.approve("d1", tok)
    with pytest.raises(PermissionError):
        gate.approve("d1", tok)
    assert sent == ["d1"]


def test_voice_needs_confirmation():
    gate, d, sent = make_gate()
    action, msg = gate.handle_voice("yo send it")
    assert action == "confirm_needed" and "prof@wisc.edu" in msg
    assert sent == []
    action, _ = gate.handle_voice("yes")
    assert action == "sent" and sent == ["d1"]


def test_voice_cancel():
    gate, d, sent = make_gate()
    gate.handle_voice("send it")
    action, _ = gate.handle_voice("wait, cancel that")
    assert action == "cancelled" and sent == []
    assert gate.active is None


def test_unrelated_speech_passes_through():
    gate, d, sent = make_gate()
    assert gate.handle_voice("what's the weather") is None
    gate.handle_voice("send it")
    assert gate.handle_voice("actually what time is it") is None  # leaves confirm mode
    assert gate.handle_voice("yes") is None and sent == []


def test_no_draft_no_intercept():
    gate = ApprovalGate({})
    assert gate.handle_voice("send it") is None


def test_cancelled_draft_cannot_be_approved():
    gate, d, sent = make_gate()
    tok = d.token
    gate.cancel("d1")
    with pytest.raises(PermissionError):
        gate.approve("d1", tok)

"""Drive the agent loop with a fake streaming client (no network)."""
from types import SimpleNamespace as NS

from monkey.brain.agent import Agent
from monkey.brain.approval import ApprovalGate
from monkey.brain.costs import HAIKU, SONNET, Ledger
from monkey.brain.router import Router
from monkey.brain.tools import Services, ToolRunner
from monkey.integrations.base import DraftResult
from monkey.memory.store import MonkeyMemory


def text_block(t):
    return NS(type="text", text=t)


def tool_block(name, inp, id_="tu1"):
    return NS(type="tool_use", name=name, input=inp, id=id_)


class FakeStream:
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
                  usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                           cache_creation_input_tokens=0, server_tool_use=None))


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **params):
        self.calls.append(params)
        content, stop = self.script.pop(0)
        return FakeStream(content, stop)


class FakeMail:
    name = "gmail"

    def __init__(self):
        self.drafts, self.sent = [], []

    def available(self):
        return True

    def create_draft(self, to, cc, subject, body, reply_to_id=""):
        self.drafts.append((to, subject))
        return DraftResult("prov-1", "https://mail.google.com/#drafts")

    def send_draft(self, pid, to, cc, subject, body):
        self.sent.append(pid)


def build(tmp_path, script):
    events, spoken = [], []
    mail = FakeMail()
    gate = ApprovalGate({"gmail": lambda d: mail.send_draft(d.provider_draft_id, d.to, d.cc, d.subject, d.body)})
    mem = MonkeyMemory(tmp_path / "memory")
    services = Services(emit=lambda e, p: events.append((e, p)), memory=mem, approval=gate,
                        mail={"gmail": mail}, open_url=lambda u: events.append(("url", u)))
    client = FakeClient(script)
    agent = Agent(client, Router(), ToolRunner(services), mem, Ledger(tmp_path / "t.db"),
                  emit=lambda e, p: events.append((e, p)), speak=spoken.append)
    return agent, client, events, spoken, mail, gate


def test_simple_reply_spoken_and_cached(tmp_path):
    agent, client, events, spoken, *_ = build(tmp_path, [([text_block("Yo! What's good? I'm here.")], "end_turn")])
    agent.handle("yo what's up")
    assert spoken and "What's good" in " ".join(spoken)
    p = client.calls[0]
    assert p["model"] == HAIKU and "betas" not in p
    assert p["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    names = [t.get("name") for t in p["tools"]]
    assert "web_search" in names and "web_fetch" not in names and "escalate" in names
    # Memory basics are handed over up front (no separate /memories round trip needed).
    first = p["messages"][0]["content"][0]["text"]
    assert "profile.md" in first and "Memory files" in first


def test_tool_loop_memory_and_open_site(tmp_path):
    script = [
        ([tool_block("memory", {"command": "view", "path": "/memories"}, "a"),
          tool_block("open_website", {"target": "canvas"}, "b")], "tool_use"),
        ([text_block("Canvas is open, my guy.")], "end_turn"),
    ]
    agent, client, events, spoken, *_ = build(tmp_path, script)
    agent.handle("open canvas")
    assert ("url", "https://canvas.wisc.edu") in events
    results = client.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]  # all results in ONE user message
    assert "profile.md" in results[0]["content"]


def test_escalation_switches_model(tmp_path):
    script = [
        ([tool_block("escalate", {"reason": "needs web"})], "tool_use"),
        ([text_block("The Badgers won 24 to 17.")], "end_turn"),
    ]
    agent, client, *_ = build(tmp_path, script)
    agent.handle("yo who won")
    assert client.calls[0]["model"] == HAIKU
    assert client.calls[1]["model"] == SONNET
    assert client.calls[1]["fallbacks"] == "default"


def test_draft_then_voice_send_never_via_model(tmp_path):
    draft_args = {"account": "gmail", "to": ["prof@wisc.edu"], "cc": [], "subject": "Lab",
                  "body": "Hi Professor, ...", "reply_to_id": ""}
    script = [
        ([tool_block("draft_email", draft_args)], "tool_use"),
        ([text_block("Draft's on your screen. Say send it when you're ready.")], "end_turn"),
    ]
    agent, client, events, spoken, mail, gate = build(tmp_path, script)
    agent.handle("draft an email to my professor saying I'll miss lab")
    assert mail.drafts and not mail.sent
    draft_event = [p for e, p in events if e == "draft"][0]
    assert draft_event["token"]  # the UI gets the token...
    model_result = client.calls[1]["messages"][-1]["content"][0]["content"]
    assert draft_event["token"] not in model_result  # ...the model never sees it
    agent.handle("send it")
    assert not mail.sent
    agent.handle("yes")
    assert mail.sent == ["prov-1"]
    assert len(client.calls) == 2  # approval turns never hit the model


def test_emote_tool_emits_event(tmp_path):
    script = [
        ([tool_block("emote", {"name": "dance"})], "tool_use"),
        ([text_block("Let's go, you finished it!")], "end_turn"),
    ]
    agent, client, events, *_ = build(tmp_path, script)
    agent.handle("I just finished my essay")
    assert ("emote", {"name": "dance"}) in events


def test_generate_image_tool(tmp_path):
    from monkey.brain.tools import Services, ToolRunner
    from monkey.brain.approval import ApprovalGate
    events = []
    s = Services(emit=lambda e, p: events.append((e, p)), memory=None, approval=ApprovalGate({}),
                 image_gen=lambda prompt, n: [{"title": "x", "src": "data:image/jpeg;base64,AAA"}] * n)
    out, err = ToolRunner(s).run("generate_image", {"prompt": "a banana car", "count": 2})
    assert not err and "2 image" in out
    imgs = [p for e, p in events if e == "images"][0]
    assert imgs["generated"] and len(imgs["images"]) == 2
    out, err = ToolRunner(Services(emit=lambda *a: None, memory=None, approval=ApprovalGate({}))).run(
        "generate_image", {"prompt": "x", "count": 1})
    assert "isn't set up" in out


# ------------------------------------------------------------------ model policy behaviour
import anthropic  # noqa: E402
import httpx  # noqa: E402


def _bad_request(message):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.BadRequestError(message, response=httpx.Response(400, request=req), body=None)


class FailingOnceClient(FakeClient):
    def __init__(self, script, error):
        super().__init__(script)
        self.error = error

    def _stream(self, **params):
        if self.error is not None:
            self.calls.append(params)
            err, self.error = self.error, None
            raise err
        return super()._stream(**params)


def test_effort_change_uses_per_message_effort_and_keeps_top_level(tmp_path):
    agent, client, *_ = build(tmp_path, [([text_block("Sup.")], "end_turn"), ([text_block("Here's why.")], "end_turn")])
    agent.handle("yo")                                   # chat: Haiku low
    agent.handle("quick fact: how many ounces are in a cup, roughly?")
    first, second = client.calls
    assert first["output_config"]["effort"] == second["output_config"]["effort"] == "low"  # cache-safe
    sys_msgs = [m for m in second["messages"] if m.get("role") == "system"]
    assert sys_msgs and sys_msgs[-1]["output_config"]["effort"] != "low"
    assert "mid-conversation-output-config-2026-07-01" in second["betas"]


def test_per_message_effort_rejected_falls_back(tmp_path):
    agent, client, *_ = build(tmp_path, [([text_block("Sup.")], "end_turn")])
    agent.handle("yo")
    agent.client = FailingOnceClient([([text_block("Okay.")], "end_turn")],
                                     _bad_request("messages: role 'system' with output_config is not supported"))
    agent.handle("quick fact: how many ounces are in a cup, roughly?")
    retry = agent.client.calls[-1]
    assert agent.per_message_effort is False
    assert not any(m.get("role") == "system" for m in retry["messages"])


def test_haiku_web_search_direct_fallback(tmp_path):
    agent, _, *_ = build(tmp_path, [])
    agent.client = FailingOnceClient([([text_block("They won.")], "end_turn")],
                                     _bad_request("web_search: set allowed_callers to ['direct'] for this model"))
    agent.handle("who won the badgers game")
    retry = agent.client.calls[-1]
    search = next(t for t in retry["tools"] if t.get("name") == "web_search")
    assert search["allowed_callers"] == ["direct"] and retry["model"] == HAIKU


def test_slow_task_says_holding_line_first(tmp_path):
    agent, client, events, spoken, *_ = build(tmp_path, [([text_block("Here's your day.")], "end_turn")])
    agent.handle("how's my day look")
    assert spoken[0] == "Pulling up your day."
    assert "already said" in client.calls[0]["messages"][0]["content"][0]["text"]


def test_route_event_and_ledger_carry_task(tmp_path):
    agent, client, events, *_ = build(tmp_path, [([text_block("Sup.")], "end_turn")])
    agent.handle("yo")
    route_ev = next(p for e, p in events if e == "route")
    assert route_ev["task"] == "chat"
    import sqlite3
    rows = sqlite3.connect(tmp_path / "t.db").execute("SELECT purpose FROM spend").fetchall()
    assert ("chat:chat",) in rows

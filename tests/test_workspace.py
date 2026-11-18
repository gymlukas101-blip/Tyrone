from datetime import datetime, timezone
from types import SimpleNamespace as NS

import anthropic
import httpx

from monkey.brain import workspace
from monkey.brain.calibrate import Calibration
from monkey.brain.costs import Ledger
from monkey.brain.policy import ModelPolicy

MSG = ("This API key is not scoped to a workspace, so this request must include the anthropic-workspace-id "
       "header with the ID of the workspace to use.")


def err(message, status=400):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    cls = anthropic.BadRequestError if status == 400 else anthropic.AuthenticationError
    return cls(message, response=httpx.Response(status, request=req), body=None)


def test_detects_and_describes():
    assert workspace.needs_workspace(err(MSG))
    assert not workspace.needs_workspace(err("max_tokens too large"))
    assert "workspace ID" in workspace.describe(err(MSG))
    assert "whole key" in workspace.describe(err("invalid x-api-key", 401))
    assert workspace.is_setup_error("API error 400: " + MSG)


def client_with(workspaces=None, fail=False):
    def lst(**kw):
        assert kw.get("include_default") is True
        if fail:
            raise err("permission_error", 403)
        return NS(data=workspaces)
    return NS(beta=NS(organization=NS(workspaces=NS(list=lst))))


def test_discover_prefers_default_and_skips_archived_and_claude_code():
    ws = [NS(id="wrkspc_cc", name="Claude Code", archived_at=None),
          NS(id="wrkspc_old", name="Default Workspace", archived_at=datetime.now(timezone.utc)),
          NS(id="wrkspc_def", name="Default Workspace", archived_at=None),
          NS(id="wrkspc_x", name="Monkey", archived_at=None)]
    assert workspace.discover(client_with(ws))[0] == "wrkspc_def"
    assert workspace.discover(client_with([ws[0], ws[3]]))[0] == "wrkspc_x"
    assert workspace.discover(client_with(fail=True))[0] is None


def test_agent_retries_once_after_workspace_fix(tmp_path):
    from tests.test_agent_loop import FailingOnceClient, build, text_block

    agent, *_ = build(tmp_path, [])
    agent.client = FailingOnceClient([([text_block("Hey!")], "end_turn")], err(MSG))
    fixed = []
    agent.on_workspace_error = lambda: fixed.append(1) or True
    assert agent.handle("yo") == "Hey!" and fixed == [1]


def test_agent_explains_when_fix_impossible(tmp_path):
    from tests.test_agent_loop import FailingOnceClient, build

    agent, _, events, *_ = build(tmp_path, [])
    agent.client = FailingOnceClient([], err(MSG))
    agent.on_workspace_error = lambda: False
    assert "workspace" in agent.handle("yo")


def test_calibration_stops_on_setup_error(tmp_path):
    class Boom:
        def __init__(self):
            self.calls = 0
            self.beta = NS(messages=NS(stream=self.stream))

        def stream(self, **p):
            self.calls += 1
            raise err(MSG)

    c = Boom()
    cal = Calibration(c, ModelPolicy(tmp_path / "p.json"), Ledger(tmp_path / "db"), tmp_path / "c.json")
    out = cal.run()
    assert c.calls == 1 and out["complete"] is False and "workspace" in out["setup_error"]

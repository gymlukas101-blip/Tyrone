"""Skills: lazy, read-only playbooks. Only name+description are always in the prompt; bodies load on demand."""
from pathlib import Path

import pytest

from monkey.brain.tools import LOCAL_TOOLS, Services, ToolRunner
from monkey.skills.loader import SkillLibrary

BUNDLED = Path(__file__).resolve().parents[1] / "monkey" / "skills"


def lib(tmp_path=None):
    return SkillLibrary(BUNDLED, tmp_path)


def test_bundled_skills_parse_and_listing_is_small():
    L = lib()
    assert {"canvas-triage", "email-professor-draft"} <= set(L.names())
    listing = L.listing()
    assert len(listing) < 300 + 200 * len(L.names())          # names + one-line descriptions only
    assert "draft" in listing and "never sends" in listing


def test_load_returns_body_not_in_listing():
    L = lib()
    body = L.load("email-professor-draft")
    assert "draft_email" in body and "never invent an address" in body
    assert "never invent an address" not in L.listing()       # lazy: body isn't in the system prompt


def test_user_skill_overrides_and_bad_ones_are_ignored(tmp_path):
    good = tmp_path / "canvas-triage"
    good.mkdir()
    (good / "SKILL.md").write_text("---\nname: canvas-triage\ndescription: my custom triage\n---\nbody v2\n")
    bad = tmp_path / "Evil Skill"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: Evil Skill\ndescription: x\n---\nrm -rf /\n")
    mismatch = tmp_path / "foo"
    mismatch.mkdir()
    (mismatch / "SKILL.md").write_text("---\nname: bar\ndescription: x\n---\n")
    L = lib(tmp_path)
    assert "my custom triage" in L.listing() and "body v2" in L.load("canvas-triage")
    assert "Evil Skill" not in L.names() and "bar" not in L.names()


def test_reference_files_are_confined(tmp_path):
    sk = tmp_path / "demo-skill"
    sk.mkdir()
    (sk / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\nsee ref\n")
    (sk / "ref.md").write_text("reference text")
    (sk / "run.py").write_text("print('no')")
    (tmp_path / "secret.md").write_text("outside")
    L = lib(tmp_path)
    assert "ref.md" in L.load("demo-skill") and "run.py" not in L.load("demo-skill")
    assert L.read_file("demo-skill", "ref.md") == "reference text"
    for bad in ("../secret.md", "run.py", "/etc/passwd"):
        with pytest.raises(ValueError):
            L.read_file("demo-skill", bad)


def test_skill_tools_via_runner_and_system_prompt(tmp_path):
    from monkey.brain.agent import Agent
    from monkey.brain.approval import ApprovalGate
    from monkey.brain.router import Router
    from monkey.memory.store import MonkeyMemory

    services = Services(emit=lambda e, p: None, memory=MonkeyMemory(tmp_path / "m"), approval=ApprovalGate({}),
                        skills=lib())
    runner = ToolRunner(services)
    out, err = runner.run("load_skill", {"name": "canvas-triage"})
    assert not err and out.startswith('<skill name="canvas-triage">')
    out, err = runner.run("load_skill", {"name": "nope"})
    assert err and "No skill named" in out
    agent = Agent(None, Router(), runner, services.memory, None, emit=lambda *a: None, speak=lambda s: None)
    assert "# Skills" in agent.system and "canvas-triage" in agent.system
    assert {"load_skill", "read_skill_file"} <= {t["name"] for t in LOCAL_TOOLS}

"""Milestone 3: the build installs exactly what's locked, and notices ship with the app."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_lockfiles_match_pyproject():
    from tools import check_lock

    assert check_lock.main() == 0


def test_lock_check_catches_an_unlocked_dependency(tmp_path, monkeypatch):
    from tools import check_lock

    fake = tmp_path / "pyproject.toml"
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8").replace(
        '"cryptography>=42",', '"cryptography>=42",\n  "left-pad-not-locked>=1",')
    fake.write_text(text, encoding="utf-8")
    (tmp_path / "requirements").mkdir()
    for f in ("windows-py312.lock", "linux-test-py312.lock", "test-extras.in"):
        (tmp_path / "requirements" / f).write_bytes((ROOT / "requirements" / f).read_bytes())
    monkeypatch.setattr(check_lock, "ROOT", tmp_path)
    assert check_lock.main() == 1


def test_every_workflow_action_is_pinned_to_a_commit():
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        for line in wf.read_text(encoding="utf-8").splitlines():
            m = re.search(r"uses:\s*([^\s#]+)", line)
            if m and not m.group(1).startswith("./"):
                assert re.search(r"@[0-9a-f]{40}$", m.group(1)), f"{wf.name}: {m.group(1)} is not pinned to a SHA"


def test_ci_installs_with_hashes_and_ships_notices():
    wf = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    assert "--require-hashes -r requirements/windows-py312.lock" in wf
    assert "--require-hashes -r requirements/linux-test-py312.lock" in wf
    assert "tools/notices.py" in wf
    spec = (ROOT / "monkey.spec").read_text(encoding="utf-8")
    assert "THIRD_PARTY_NOTICES.md" in spec and "THIRD_PARTY_LICENSES.txt" in spec
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "CC BY-NC-SA" in notices and "Playwright" in notices


def test_notices_generator_lists_installed_packages(tmp_path):
    from tools import notices

    out = tmp_path / "L.txt"
    notices.main(out)
    text = out.read_text(encoding="utf-8")
    assert re.search(r"^anthropic \S+ — ", text, re.M) and "pytest" not in text.split("\n", 5)[-1].split()[0:1]

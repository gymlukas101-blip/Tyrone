"""Fail when pyproject.toml and the hashed lockfiles disagree (CI runs this; no network needed).

Every dependency in pyproject.toml (for the platform each lockfile is for) must be pinned in that lockfile, at a
version that satisfies pyproject's range. Fix: run tools/lock.sh and commit the result.
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent
LOCKS = {
    "requirements/windows-py312.lock": {"platform": "win32", "extras": ["desktop", "dev"], "more": []},
    "requirements/linux-test-py312.lock": {"platform": "linux", "extras": ["dev"],
                                           "more": ["requirements/test-extras.in"]},
}


def pins(lock: Path) -> dict[str, str]:
    out = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-\[\]]+)==([^\s\;]+)", line)
        if m:
            out[canonicalize_name(m.group(1).split("[")[0])] = m.group(2)
    return out


def main() -> int:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    problems = []
    for lock_name, spec in LOCKS.items():
        lock = ROOT / lock_name
        if not lock.exists():
            problems.append(f"{lock_name} is missing")
            continue
        pinned = pins(lock)
        env = {**default_environment(), "sys_platform": spec["platform"], "python_version": "3.12",
               "platform_system": "Windows" if spec["platform"] == "win32" else "Linux"}
        reqs = list(project["dependencies"])
        for extra in spec["extras"]:
            reqs += project["optional-dependencies"][extra]
        for more in spec["more"]:
            reqs += [ln.strip() for ln in (ROOT / more).read_text().splitlines() if ln.strip() and not ln.startswith("#")]
        for raw in reqs:
            req = Requirement(raw)
            if req.marker is not None and not req.marker.evaluate(env):
                continue
            name = canonicalize_name(req.name)
            if name not in pinned:
                problems.append(f"{lock_name}: {req.name} is in pyproject.toml but not locked")
            elif req.specifier and not req.specifier.contains(pinned[name], prereleases=True):
                problems.append(f"{lock_name}: {req.name}=={pinned[name]} doesn't satisfy '{req.specifier}'")
        if "--hash=sha256:" not in lock.read_text(encoding="utf-8"):
            problems.append(f"{lock_name} has no hashes")
    for p in problems:
        print(f"::error::{p}. Run tools/lock.sh and commit the result.")
    if not problems:
        print("lockfiles match pyproject.toml")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

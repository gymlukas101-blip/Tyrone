"""Skills: small, reusable playbooks (a folder with SKILL.md) that Monkey loads only when a request needs them.

- Only each skill's name + one-line description sit in the (cached) system prompt (~30 tokens each).
- `load_skill(name)` returns the SKILL.md body; `read_skill_file(name, file)` returns an extra reference file from
  that skill's folder. Both are read-only text. Skills never run code and never grant capabilities: what Monkey
  can actually DO is still limited to its tools and the approval gate.
- Bundled skills live in monkey/skills/<name>/; your own go in %APPDATA%\\Monkey\\skills\\<name>\\SKILL.md
  (a user skill with the same name overrides the bundled one).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
MAX_BODY = 6000
MAX_REF = 20000
TEXT_EXT = {".md", ".txt"}


@dataclass
class Skill:
    name: str
    description: str
    folder: Path
    body: str


def parse(path: Path) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = FRONT.match(text)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip().strip('"')
    name, desc = meta.get("name", ""), " ".join(meta.get("description", "").split())
    if not NAME.match(name) or name != path.parent.name or not desc:
        return None
    return Skill(name, desc[:300], path.parent, m.group(2).strip()[:MAX_BODY])


class SkillLibrary:
    def __init__(self, *dirs: Path | None):
        self.dirs = [Path(d) for d in dirs if d]
        self._skills: dict[str, Skill] = {}
        self.reload()

    def reload(self) -> None:
        found: dict[str, Skill] = {}
        for d in self.dirs:                         # later dirs (user) override earlier ones (bundled)
            if not d.exists():
                continue
            for p in sorted(d.glob("*/SKILL.md")):
                s = parse(p)
                if s is not None:
                    found[s.name] = s
        self._skills = found

    def names(self) -> list[str]:
        return sorted(self._skills)

    def listing(self) -> str:
        if not self._skills:
            return ""
        lines = "\n".join(f"- {s.name}: {s.description}" for s in sorted(self._skills.values(), key=lambda s: s.name))
        return ("# Skills\nPlaybooks for specific jobs. When a request matches one, call `load_skill` with its name "
                "FIRST and follow it. Skills are instructions only; they don't give you new abilities.\n" + lines)

    def load(self, name: str) -> str:
        s = self._skills.get(str(name).strip())
        if s is None:
            raise KeyError(f"No skill named {name!r}. Available: {', '.join(self.names()) or 'none'}")
        refs = sorted(p.name for p in s.folder.iterdir() if p.suffix in TEXT_EXT and p.name != "SKILL.md")
        extra = f"\n\n(Reference files you can read with read_skill_file: {', '.join(refs)})" if refs else ""
        return f"<skill name=\"{s.name}\">\n{s.body}{extra}\n</skill>"

    def read_file(self, name: str, file: str) -> str:
        s = self._skills.get(str(name).strip())
        if s is None:
            raise KeyError(f"No skill named {name!r}")
        p = (s.folder / str(file)).resolve()
        if s.folder.resolve() not in p.parents or p.suffix not in TEXT_EXT or not p.is_file():
            raise ValueError("Only .md/.txt files inside that skill's folder can be read.")
        return p.read_text(encoding="utf-8")[:MAX_REF]

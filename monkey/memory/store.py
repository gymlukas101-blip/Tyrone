"""Monkey's long-term memory.

Backed by Claude's memory tool (memory_20250818) using the SDK's local-filesystem
implementation. Files live in <memory_dir>/memories/*.md - plain markdown you can
open and edit yourself.
"""
from __future__ import annotations

from pathlib import Path

from anthropic.lib.tools._beta_builtin_memory_tool import BetaLocalFilesystemMemoryTool

SEED_FILES: dict[str, str] = {
    "profile.md": (
        "# About the user\n"
        "- Student at the University of Wisconsin–Madison.\n"
        "- (Monkey fills in name, major, year, hometown, goals as he learns them.)\n"
    ),
    "classes.md": "# Classes this semester\n(course, professor, TA, meeting times, exam dates)\n",
    "people.md": "# People\n(professors, TAs, advisors, friends, family, roommates - who they are and how to address them)\n",
    "preferences.md": "# Preferences\n(how the user likes answers, routines, food, music, study habits)\n",
    "writing_style.md": (
        "# How the user writes emails\n"
        "(Not analyzed yet. Run 'Learn my writing style' in Settings, or ask Monkey to learn it.)\n"
    ),
    "sites.md": (
        "# Website shortcuts\n"
        "- canvas: https://canvas.wisc.edu\n"
        "- myuw: https://my.wisc.edu\n"
        "- course search / enroll: https://public.enroll.wisc.edu\n"
        "- outlook / school email: https://outlook.office.com/mail/\n"
        "- gmail: https://mail.google.com\n"
        "- handshake: https://wisc.joinhandshake.com\n"
        "- rec well: https://recwell.wisc.edu\n"
        "- libraries: https://www.library.wisc.edu\n"
        "- dars / degree audit: https://my.wisc.edu\n"
        "- madison metro: https://www.cityofmadison.com/metro\n"
    ),
}


class MonkeyMemory(BetaLocalFilesystemMemoryTool):
    """Memory tool rooted at <base>/memories, seeded with starter files."""

    def __init__(self, base_path: Path | str):
        super().__init__(base_path=str(base_path))
        self.seed()

    def seed(self) -> None:
        root = Path(self.memory_root)
        root.mkdir(parents=True, exist_ok=True)
        for name, content in SEED_FILES.items():
            p = root / name
            if not p.exists():
                p.write_text(content, encoding="utf-8")

    # Convenience for non-model code (UI, style learner, website shortcuts).
    def read(self, name: str) -> str:
        p = Path(self.memory_root) / name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def write(self, name: str, content: str) -> None:
        p = Path(self.memory_root) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def files(self) -> list[str]:
        root = Path(self.memory_root)
        return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())

    def site_shortcuts(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in self.read("sites.md").splitlines():
            line = line.strip()
            if line.startswith("- ") and ": http" in line:
                name, url = line[2:].split(": ", 1)
                for alias in name.split("/"):
                    out[alias.strip().lower()] = url.strip()
        return out

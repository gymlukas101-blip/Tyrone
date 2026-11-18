"""Import context files (e.g. a profile pack exported from ChatGPT) into Monkey's memory: preview first, back up,
merge, never blindly overwrite.

plan_import(root, {name: text}) -> Plan (per-file: new / merge / unchanged, lines to add, possible conflicts)
apply_import(root, plan)        -> backup folder path; files written with src=import provenance

Merging keeps everything you already have. New lines are appended under a dated "Imported" heading; lines whose
text is already present are skipped; seed placeholders like "(Monkey fills in …)" are dropped. A line that looks like
a different value for something you already have (same class/time keywords, different numbers) is listed as a
possible conflict for you to resolve; both versions are kept until you choose.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import facts as F

ALLOWED = re.compile(r"^[A-Za-z0-9_-]{1,40}\.md$")
NUM = re.compile(r"\d")


@dataclass
class FilePlan:
    name: str
    action: str                       # new | merge | unchanged
    add: list[str] = field(default_factory=list)
    conflicts: list[tuple[str, str]] = field(default_factory=list)   # (existing line, incoming line)
    result: str = ""


@dataclass
class Plan:
    files: list[FilePlan]
    label: str

    def summary(self) -> dict:
        return {"label": self.label, "files": [{"name": f.name, "action": f.action, "add": f.add,
                                                "conflicts": [{"existing": a, "incoming": b} for a, b in f.conflicts]}
                                               for f in self.files]}


def _key_words(text: str) -> set[str]:
    return {w for w in F.content_words(text) if not NUM.search(w)}


def _with_meta(line: str, src_date: str) -> str:
    body, meta = F.parse_meta(line)
    if meta:
        return line
    b = F.BULLET.match(body)
    if not b:
        return line
    return f"- {b.group(1).strip()} <!-- src=import date={src_date} -->"


def plan_import(root: Path, incoming: dict[str, str], label: str | None = None) -> Plan:
    root = Path(root)
    label = label or f"Imported context ({date.today().isoformat()}, review)"
    plans = []
    for name, text in incoming.items():
        if not ALLOWED.match(name) or name in F.SYSTEM_FILES:
            raise ValueError(f"Not importing {name!r}: only plain .md memory files are allowed.")
        text = text.replace("\r\n", "\n").strip() + "\n"
        target = root / name
        src_date = date.today().isoformat()
        if not target.exists() or _only_placeholders(target.read_text(encoding="utf-8")):
            lines = [_with_meta(ln, src_date) for ln in text.splitlines()]
            plans.append(FilePlan(name, "new", [ln for ln in lines if F.BULLET.match(F.parse_meta(ln)[0])],
                                  result="\n".join(lines).rstrip() + "\n"))
            continue
        existing = target.read_text(encoding="utf-8")
        have = {F.normalize(f.text): f for f in F.parse_file(root, name)}
        add, conflicts, section = [], [], ""
        for ln in text.splitlines():
            h = F.HEADING.match(ln)
            if h:
                section = ln
                continue
            b = F.BULLET.match(F.parse_meta(ln)[0])
            if not b:
                continue
            t = b.group(1).strip()
            if F.normalize(t) in have or F.PLACEHOLDER.match(t):
                continue
            kw = _key_words(t)
            for f in have.values():
                overlap = kw & _key_words(f.text)
                if len(overlap) >= 2 and NUM.search(t) and NUM.search(f.text) and \
                        sorted(re.findall(r"\d+", t)) != sorted(re.findall(r"\d+", f.text)):
                    conflicts.append((f.text, t))
                    break
            add.append((section, _with_meta(ln, src_date)))
        if not add:
            plans.append(FilePlan(name, "unchanged", result=existing))
            continue
        kept = [ln for ln in existing.rstrip().splitlines() if not _is_placeholder(ln)]
        block, last = ["", f"## {label}"], None
        for sec, ln in add:
            if sec and sec != last:
                block.append(f"### {sec.lstrip('# ').strip()}")
                last = sec
            block.append(ln)
        plans.append(FilePlan(name, "merge", [ln for _, ln in add], conflicts,
                              "\n".join(kept + block).rstrip() + "\n"))
    return Plan(plans, label)


def _is_placeholder(line: str) -> bool:
    b = F.BULLET.match(F.parse_meta(line)[0])
    return bool(F.PLACEHOLDER.match(line.strip()) or (b and F.PLACEHOLDER.match(b.group(1).strip())))


def _only_placeholders(text: str) -> bool:
    return not any(F.BULLET.match(F.parse_meta(ln)[0]) and not F.PLACEHOLDER.match(F.BULLET.match(
        F.parse_meta(ln)[0]).group(1).strip()) for ln in text.splitlines())


def apply_import(root: Path, plan: Plan) -> Path:
    """Back up every file that will change, then write the merged results. Returns the backup folder."""
    root = Path(root)
    backup = root / "backups" / f"import-{datetime.now():%Y%m%d-%H%M%S}"
    backup.mkdir(parents=True, exist_ok=True)
    for fp in plan.files:
        if fp.action == "unchanged":
            continue
        target = root / fp.name
        if target.exists():
            shutil.copy2(target, backup / fp.name)
        target.write_text(fp.result, encoding="utf-8")
    return backup


def restore_backup(root: Path, backup: Path) -> list[str]:
    """Undo an import: copy the backed-up files back."""
    restored = []
    for p in Path(backup).glob("*.md"):
        shutil.copy2(p, Path(root) / p.name)
        restored.append(p.name)
    return restored

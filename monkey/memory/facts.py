"""Facts in Monkey's markdown memory, with provenance, corrections and deletion.

The markdown files in /memories stay the source of truth (you can open and edit them). A fact is a bullet line;
it may carry trailing metadata that Monkey writes and you can ignore:

    - Prefers short spoken answers <!-- id=f1a2b3c4 src=user_said date=2026-11-18 -->

src is one of: user_said (you told Monkey), import (from a context file you imported), user_edit (you typed it
into the file; the default for lines without metadata), inferred (Monkey's guess; only in inferences.md).
Correcting a fact moves the old line to superseded.md (so it is never treated as current); forgetting deletes it.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

META = re.compile(r"\s*<!--\s*(.*?)\s*-->\s*$")
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")
HEADING = re.compile(r"^\s*#{1,6}\s+(.*\S)\s*$")
PLACEHOLDER = re.compile(r"^\(.*\)$")                 # seed lines like "(Monkey fills in name, major…)"
SYSTEM_FILES = {"superseded.md"}
SKIP_DIRS = {"backups"}
SENSITIVE = re.compile(
    r"\b(health|medical|medication|diagnos\w*|therap\w*|injur\w*|surgery|illness|disorder|"
    r"military|army|national guard|guard drill|deploy\w*|veteran|security clearance|"
    r"family|mom|dad|mother|father|sister|brother|parents?|relationship|girlfriend|boyfriend|"
    r"finance\w*|bank|salary|income|debt|loan|ssn|social security|password|passcode|pin)\b", re.I)
EXPLICIT_REMEMBER = re.compile(r"\b(remember|note (?:that|this|it)|save (?:that|this)|don'?t forget|keep in mind|"
                               r"write (?:that|this) down|update (?:my|that)|change (?:my|that)|forget|correct(?:ion)?)\b", re.I)


@dataclass
class Fact:
    id: str
    file: str
    section: str
    text: str
    src: str = "user_edit"
    date: str = ""
    line_no: int = 0
    status: str = "current"            # current | superseded
    sensitive: bool = False
    meta: dict = field(default_factory=dict)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s:/.-]", "", text.lower())).strip()


def fact_id(file: str, text: str) -> str:
    return "f" + hashlib.sha1(f"{file}\n{normalize(text)}".encode()).hexdigest()[:8]


def parse_meta(line: str) -> tuple[str, dict]:
    m = META.search(line)
    if not m:
        return line, {}
    meta = {}
    for part in m.group(1).split():
        if "=" in part:
            k, v = part.split("=", 1)
            meta[k] = v
    return line[:m.start()], meta


def parse_file(root: Path, rel: str) -> list[Fact]:
    path = Path(root) / rel
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        mdate = datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
    except OSError:
        return []
    status = "superseded" if rel in SYSTEM_FILES else "current"
    section, out = "", []
    for i, raw in enumerate(lines):
        h = HEADING.match(raw)
        if h:
            section = h.group(1)
            continue
        body, meta = parse_meta(raw)
        b = BULLET.match(body)
        if not b:
            continue
        text = b.group(1).strip()
        if not text or PLACEHOLDER.match(text):
            continue
        out.append(Fact(
            id=meta.get("id") or fact_id(rel, text), file=rel, section=section, text=text,
            src=meta.get("src", "user_edit"), date=meta.get("date", mdate), line_no=i, status=status,
            sensitive=bool(SENSITIVE.search(text)) or rel == "sensitive.md", meta=meta,
        ))
    return out


def memory_files(root: Path) -> list[str]:
    root = Path(root)
    out = []
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root)
        if rel.parts and rel.parts[0] in SKIP_DIRS:
            continue
        out.append(rel.as_posix())
    return out


def all_facts(root: Path) -> list[Fact]:
    return [f for rel in memory_files(root) for f in parse_file(root, rel)]


def safe_rel(root: Path, rel: str) -> str:
    """A markdown path inside the memory root (no traversal, no backups, .md only)."""
    rel = str(rel).replace("\\", "/").lstrip("/")
    if rel.startswith("memories/"):
        rel = rel[len("memories/"):]
    p = (Path(root) / rel).resolve()
    if Path(root).resolve() not in p.parents or p.suffix != ".md":
        raise ValueError("Memory files must be .md files inside the memory folder.")
    if p.relative_to(Path(root).resolve()).parts[0] in SKIP_DIRS or p.name in SYSTEM_FILES:
        raise ValueError("That file is managed by Monkey.")
    return p.relative_to(Path(root).resolve()).as_posix()


def _line(text: str, fid: str, src: str, extra: str = "") -> str:
    today = date.today().isoformat()
    return f"- {text.strip()} <!-- id={fid} src={src} date={today}{(' ' + extra) if extra else ''} -->"


def add_fact(root: Path, rel: str, text: str, src: str = "user_said") -> tuple[Fact, bool]:
    """Append a fact (deduplicated). Returns (fact, created)."""
    rel = safe_rel(root, rel)
    text = " ".join(text.split())
    for f in parse_file(root, rel):
        if normalize(f.text) == normalize(text):
            return f, False
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {Path(rel).stem.replace('_', ' ').title()}\n"
    lines = [ln for ln in existing.splitlines() if not PLACEHOLDER.match(ln.strip())]
    fid = fact_id(rel, text)
    lines.append(_line(text, fid, src))
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return next(f for f in parse_file(root, rel) if f.id == fid), True


_COPULA = re.compile(r"^(.+?)\s+(?:is|are|was|were)\s+(.+)$", re.I)
_DETS = {"the", "their", "his", "her", "a", "an", "user's", "users", "user"}


def _copula(text: str) -> tuple[str, str] | None:
    """("roommate", "jordan") for "Their roommate is Jordan"; None if the fact isn't an "X is Y" statement."""
    m = _COPULA.match(" ".join((text or "").split()).rstrip("."))
    if not m:
        return None
    subj = " ".join(w for w in re.findall(r"[a-z0-9'-]+", m.group(1).lower()) if w not in _DETS)
    val = " ".join(re.findall(r"[a-z0-9'-]+", m.group(2).lower()))
    return (subj, val) if subj and val else None


def conflicts(root: Path, rel: str, text: str) -> list[Fact]:
    """Current facts in the same file about the same thing that say something different.

    "Their advisor is Dr. Rivera" vs "Their advisor is Dr. Chen": most of the shorter fact's content words are
    shared, but not all of them. A new fact like that should replace the old one (update_fact), not sit beside it
    as a second "current" truth."""
    new = content_words(text)
    new_is = _copula(text)
    out = []
    for f in parse_file(root, safe_rel(root, rel)):
        if f.status != "current" or normalize(f.text) == normalize(text):
            continue
        old_is = _copula(f.text)
        if new_is and old_is and new_is[0] == old_is[0] and new_is[1] != old_is[1]:
            out.append(f)                    # same subject, different value: "roommate is Sam" / "roommate is Jordan"
            continue
        if not new:
            continue
        old = content_words(f.text)
        if not old:
            continue
        shared = len(new & old)
        smaller = min(len(new), len(old))
        if shared >= 1 and shared / smaller >= 0.5 and (new - old) and (old - new):
            out.append(f)
    return out


def find_fact(root: Path, fid: str) -> Fact | None:
    return next((f for f in all_facts(root) if f.id == fid and f.status == "current"), None)


def _remove_line(root: Path, f: Fact) -> None:
    path = Path(root) / f.file
    lines = path.read_text(encoding="utf-8").splitlines()
    if 0 <= f.line_no < len(lines):
        del lines[f.line_no]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def update_fact(root: Path, fid: str, new_text: str, src: str = "user_said") -> tuple[Fact, Fact]:
    """Replace a current fact; the old line moves to superseded.md with a pointer. Returns (old, new)."""
    old = find_fact(root, fid)
    if old is None:
        raise KeyError(f"No current memory with id {fid}")
    new_text = " ".join(new_text.split())
    new_id = fact_id(old.file, new_text)
    path = Path(root) / old.file
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[old.line_no] = _line(new_text, new_id, src, f"supersedes={old.id}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    sup = Path(root) / "superseded.md"
    head = "" if sup.exists() else "# Superseded (older versions of facts; never treated as current)\n"
    with sup.open("a", encoding="utf-8") as fh:
        fh.write(head + f"- [{old.file}] {old.text} <!-- id={old.id} src={old.src} date={old.date} "
                        f"superseded_by={new_id} superseded={date.today().isoformat()} -->\n")
    new = next(f for f in parse_file(root, old.file) if f.id == new_id)
    return old, new


def forget_fact(root: Path, fid: str) -> Fact:
    f = find_fact(root, fid)
    if f is None:
        raise KeyError(f"No current memory with id {fid}")
    _remove_line(root, f)
    return f


def content_words(text: str) -> set[str]:
    stop = {"that", "this", "with", "from", "have", "they", "them", "their", "about", "would", "there", "what",
            "when", "will", "your", "just", "like", "really", "into", "been", "also", "very", "user", "user's", "lucas"}
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) >= 4 and w not in stop}


def grounded(fact: str, evidence: str, user_texts: list[str]) -> str:
    """'' if the fact is grounded in what the USER actually said this conversation, else why not.

    evidence must be a verbatim quote from one of the user's own messages, and most of the fact's content words
    must come from that quote, so text from emails, web pages or retrieved notes can't become a durable fact."""
    ev = " ".join((evidence or "").split()).lower()
    if len(ev) < 6:
        return "Quote the user's exact words as evidence."
    said = [" ".join(t.split()).lower() for t in user_texts]
    if not any(ev in s for s in said):
        return "The evidence isn't something the user said in this conversation. Ask them to confirm it first."
    words = content_words(fact)
    if words:
        hit = len(words & content_words(ev)) / len(words)
        if hit < 0.5:
            return "Most of that fact isn't in the user's words. Store only what they actually said."
    return ""

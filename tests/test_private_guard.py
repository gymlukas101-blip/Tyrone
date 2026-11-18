"""Guard: no line from the user's private context pack may appear in this PUBLIC repository.

The pack itself is never in the repo. Point MONKEY_PRIVATE_PACK at a local folder (or .zip) of the private
.md files to run the check; it's skipped otherwise (e.g. in CI)."""
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def private_lines() -> list[str]:
    src = os.environ.get("MONKEY_PRIVATE_PACK")
    if not src or not Path(src).exists():
        pytest.skip("MONKEY_PRIVATE_PACK not set")
    texts = []
    p = Path(src)
    if p.suffix == ".zip":
        with zipfile.ZipFile(p) as z:
            texts = [z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".md")]
    else:
        texts = [f.read_text(encoding="utf-8", errors="ignore") for f in p.glob("*.md")]
    lines = []
    for t in texts:
        for ln in t.splitlines():
            ln = ln.strip("-*# ").strip()
            if len(ln) >= 40:                       # distinctive sentences only (not headings)
                lines.append(ln)
    return lines


def test_no_private_text_in_tracked_files():
    lines = private_lines()
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    hits = []
    for f in files:
        p = ROOT / f
        if p.suffix in (".glb", ".png", ".jpg", ".ogg", ".mp3", ".onnx", ".ico", ".jpeg"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for ln in lines:
            if ln in text:
                hits.append(f"{f}: {ln[:30]}…")
    assert not hits, hits

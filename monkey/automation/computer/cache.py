"""Action cache: a step the planner chose and that was *verified* is replayed the next time the same objective meets
the same screen, without a model call (the Stagehand cache-then-self-heal idea, kept local). Replays still go through
the permission gate; a replay that fails drops the entry and the planner is asked again.

Stored in the user's data folder (never the repo). Keys hash the objective, the app/site, and the screen's outline
without ids; values are tool calls with ids replaced by (role, name) so they survive re-renders.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

from .model import View


def screen_key(objective: str, view: View) -> str:
    loc = view.location
    if loc.startswith("http"):
        p = urlsplit(loc)
        loc = f"{p.hostname}{re.sub(r'/[0-9a-f-]{6,}|/\\d+', '/*', p.path)}"
    outline = re.sub(r" \[id=[^\]]+\]", "", view.outline(3000))
    outline = re.sub(r'value="[^"]*"', "", outline)
    src = f"{' '.join(objective.lower().split())}\n{view.backend}\n{loc}\n{outline}"
    return hashlib.sha1(src.encode("utf-8", "ignore")).hexdigest()[:20]


class ActionCache:
    def __init__(self, path: Path | None = None, limit: int = 500):
        self.path = Path(path) if path else None
        self.limit = limit
        self._lock = threading.Lock()
        self.data: dict[str, list[dict]] = {}
        if self.path and self.path.is_file():
            try:
                self.data = json.loads(self.path.read_text("utf-8"))
            except (OSError, ValueError):
                self.data = {}
        self.hits = 0

    def lookup(self, key: str) -> list[dict] | None:
        return self.data.get(key)

    def store(self, key: str, calls: list[dict], view: View) -> None:
        portable = []
        for c in calls:
            inp = dict(c.get("input") or {})
            if c["name"] in ("type_text",):
                return                                   # typed text can be personal: never cached
            el = view.get(inp.get("id", "")) if inp.get("id") else None
            if inp.get("id") and el is None:
                return
            if el is not None:
                inp.pop("id")
                inp["target"] = {"role": el.role, "name": el.name, "backend": el.backend}
            portable.append({"name": c["name"], "input": inp})
        with self._lock:
            self.data[key] = portable
            if len(self.data) > self.limit:
                for k in list(self.data)[: len(self.data) - self.limit]:
                    self.data.pop(k, None)
            self._flush()

    def drop(self, key: str) -> None:
        with self._lock:
            if self.data.pop(key, None) is not None:
                self._flush()

    def _flush(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data), "utf-8")
        except OSError:
            pass

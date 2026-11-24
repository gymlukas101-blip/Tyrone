"""Inbox cleanups in monkey.db (local only): one row per run, one per email it touched, for the result screen and Undo.

Kept: the account, the message id (and Outlook's new id after the move), the group, the label and what happened.
Not kept: subjects, senders, snippets or bodies.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path


class CleanupStore:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS inbox_cleanup_runs(id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                      "created REAL NOT NULL, finished REAL, status TEXT NOT NULL, accounts TEXT NOT NULL DEFAULT '', "
                      "summary TEXT NOT NULL DEFAULT '{}', labels_made TEXT NOT NULL DEFAULT '[]', undone_at REAL)")
            c.execute("CREATE TABLE IF NOT EXISTS inbox_cleanup_items(run_id TEXT NOT NULL, account TEXT NOT NULL, "
                      "message_id TEXT NOT NULL, new_id TEXT NOT NULL DEFAULT '', grp TEXT NOT NULL DEFAULT '', "
                      "archive INTEGER NOT NULL DEFAULT 0, label TEXT NOT NULL DEFAULT '', "
                      "status TEXT NOT NULL DEFAULT 'pending', detail TEXT NOT NULL DEFAULT '', ts REAL)")
            c.execute("CREATE INDEX IF NOT EXISTS inbox_cleanup_items_run ON inbox_cleanup_items(run_id)")

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def start(self, run_id: str, kind: str, accounts: list[str], items: list[dict]) -> None:
        now = time.time()
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO inbox_cleanup_runs(id, kind, created, status, accounts) VALUES (?,?,?,?,?)",
                      (run_id, kind, now, "running", ",".join(accounts)))
            c.executemany("INSERT INTO inbox_cleanup_items(run_id, account, message_id, grp, archive, label, ts) "
                          "VALUES (?,?,?,?,?,?,?)",
                          [(run_id, i["account"], i["id"], i.get("group", ""), int(bool(i.get("archive"))),
                            i.get("label", ""), now) for i in items])

    def mark(self, run_id: str, account: str, ids: list[str], status: str, detail: str = "",
             new_ids: dict[str, str] | None = None) -> None:
        now = time.time()
        with self._lock, self._conn() as c:
            for mid in ids:
                c.execute("UPDATE inbox_cleanup_items SET status=?, detail=?, new_id=?, ts=? WHERE run_id=? AND "
                          "account=? AND message_id=?", (status, detail[:200], (new_ids or {}).get(mid, ""), now,
                                                         run_id, account, mid))

    def labels_made(self, run_id: str, made: list[tuple[str, str]]) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE inbox_cleanup_runs SET labels_made=? WHERE id=?", (json.dumps(made), run_id))

    def finish(self, run_id: str, status: str, summary: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE inbox_cleanup_runs SET status=?, finished=?, summary=? WHERE id=?",
                      (status, time.time(), json.dumps(summary), run_id))

    def undone(self, run_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE inbox_cleanup_runs SET status='undone', undone_at=? WHERE id=?", (time.time(), run_id))

    def run(self, run_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM inbox_cleanup_runs WHERE id=?", (run_id,)).fetchone()
        return self._pub(r) if r else None

    def last(self, undoable: bool = False) -> dict | None:
        q = "SELECT * FROM inbox_cleanup_runs"
        if undoable:
            q += " WHERE status IN ('done', 'stopped')"
        with self._conn() as c:
            r = c.execute(q + " ORDER BY created DESC LIMIT 1").fetchone()
        return self._pub(r) if r else None

    def items(self, run_id: str, status: str | None = None) -> list[dict]:
        with self._conn() as c:
            q = "SELECT * FROM inbox_cleanup_items WHERE run_id=?"
            rows = c.execute(q + (" AND status=?" if status else ""), (run_id, status) if status else (run_id,))
            return [dict(r) for r in rows]

    @staticmethod
    def _pub(r) -> dict:
        d = dict(r)
        d["summary"] = json.loads(d.get("summary") or "{}")
        d["labels_made"] = [tuple(x) for x in json.loads(d.get("labels_made") or "[]")]
        d["accounts"] = [a for a in (d.get("accounts") or "").split(",") if a]
        return d

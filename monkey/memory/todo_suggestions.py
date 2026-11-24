"""To-dos Monkey found in the owner's email, waiting for Accept or Dismiss (monkey.db, local only).

A suggestion is never a to-do by itself: only Accept (the owner's click) adds it, through the normal TodoStore.add
path, with the email as its origin. Every email that was looked at is remembered by (account, message id), whatever
became of it (pending, accepted, dismissed, or skipped as not a to-do), so a dismissed suggestion never comes back
and the same email is never sent to the model twice. Only a one-line quote is kept, never the email body.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

STATUSES = ("pending", "accepted", "dismissed", "skipped")
KEEP_S = 45 * 86400            # dismissed/skipped rows outlive the scan window (days) many times over, then go
MAX_PENDING = 30

COLUMNS: dict[str, str] = {
    "id": "TEXT PRIMARY KEY",
    "key": "TEXT NOT NULL UNIQUE",          # "<account>:<message id>"
    "account": "TEXT NOT NULL",             # account id: gmail, gmail-2, outlook
    "account_label": "TEXT NOT NULL DEFAULT ''",
    "kind": "TEXT NOT NULL DEFAULT 'gmail'",  # gmail | outlook | outlook_task
    "message_id": "TEXT NOT NULL DEFAULT ''",
    "link": "TEXT NOT NULL DEFAULT ''",
    "text": "TEXT NOT NULL DEFAULT ''",
    "due": "TEXT",
    "evidence": "TEXT NOT NULL DEFAULT ''",   # the quoted line from the email's subject or preview
    "subject": "TEXT NOT NULL DEFAULT ''",
    "sender": "TEXT NOT NULL DEFAULT ''",     # display name only
    "signal": "TEXT NOT NULL DEFAULT ''",     # flagged | task | ask
    "why": "TEXT NOT NULL DEFAULT ''",        # skipped: why it isn't a to-do
    "status": "TEXT NOT NULL DEFAULT 'pending'",
    "todo_id": "TEXT NOT NULL DEFAULT ''",
    "created": "REAL",
    "updated": "REAL",
}
PUBLIC = ("id", "account", "account_label", "kind", "link", "text", "due", "evidence", "subject", "sender", "signal",
          "status", "todo_id", "created")


class SuggestionStore:
    def __init__(self, db_path: Path | str, hidden: Callable[[dict], bool] | None = None):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        # Suggestions about a class the owner dropped stay in the table (Dismiss/seen state is kept) but aren't shown
        # or counted while the class is hidden; showing the class again brings them back.
        self.hidden = hidden
        with self._conn() as c:
            c.execute(f"CREATE TABLE IF NOT EXISTS todo_suggestions({', '.join(f'{k} {v}' for k, v in COLUMNS.items())})")
            have = {r[1] for r in c.execute("PRAGMA table_info(todo_suggestions)")}
            for name, decl in COLUMNS.items():
                if name not in have:
                    c.execute(f"ALTER TABLE todo_suggestions ADD COLUMN {name} "
                              f"{decl.replace('PRIMARY KEY', '').replace('UNIQUE', '')}")
            c.execute("CREATE INDEX IF NOT EXISTS todo_suggestions_status ON todo_suggestions(status)")
            c.execute("DELETE FROM todo_suggestions WHERE status IN ('dismissed', 'skipped') AND updated < ?",
                      (time.time() - KEEP_S,))

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    @staticmethod
    def key(account: str, message_id: str) -> str:
        return f"{account}:{message_id}"

    @staticmethod
    def _row(r) -> dict | None:
        return {k: r[k] for k in PUBLIC} if r is not None else None

    def known(self, keys: list[str]) -> set[str]:
        """Which of these emails were already looked at (any status)."""
        if not keys:
            return set()
        with self._conn() as c:
            out: set[str] = set()
            for i in range(0, len(keys), 500):
                chunk = keys[i:i + 500]
                out |= {r[0] for r in c.execute(
                    f"SELECT key FROM todo_suggestions WHERE key IN ({','.join('?' * len(chunk))})", chunk)}
            return out

    def record(self, *, account: str, message_id: str, status: str = "pending", account_label: str = "",
               kind: str = "gmail", link: str = "", text: str = "", due: str | None = None, evidence: str = "",
               subject: str = "", sender: str = "", signal: str = "", why: str = "") -> dict | None:
        """Remember one email. Returns the new row, or None if this email was seen before (it is never re-added, so
        Dismiss sticks) or the pending list is full."""
        status = status if status in STATUSES else "pending"
        ts = time.time()
        with self._lock, self._conn() as c:
            if status == "pending" and c.execute(
                    "SELECT COUNT(*) FROM todo_suggestions WHERE status='pending'").fetchone()[0] >= MAX_PENDING:
                return None
            sid = uuid.uuid4().hex[:8]
            cur = c.execute(
                "INSERT OR IGNORE INTO todo_suggestions(id, key, account, account_label, kind, message_id, link, text, "
                "due, evidence, subject, sender, signal, why, status, created, updated) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, self.key(account, message_id), account, account_label[:60], kind, message_id, link[:500],
                 " ".join(text.split())[:200], due, " ".join(evidence.split())[:300], subject[:200], sender[:80],
                 signal, why[:80], status, ts, ts))
            if cur.rowcount == 0:
                return None
        return self.get(sid)

    def get(self, sid: str) -> dict | None:
        with self._conn() as c:
            return self._row(c.execute("SELECT * FROM todo_suggestions WHERE id=?", (sid,)).fetchone())

    def message_id(self, sid: str) -> str:
        with self._conn() as c:
            r = c.execute("SELECT message_id FROM todo_suggestions WHERE id=?", (sid,)).fetchone()
        return r[0] if r else ""

    def _shown(self, row: dict) -> bool:
        try:
            return not (self.hidden is not None and self.hidden(row))
        except Exception:  # noqa: BLE001 - a bad filter must never hide the whole list
            return True

    def pending(self, limit: int = MAX_PENDING) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM todo_suggestions WHERE status='pending' "
                             "ORDER BY CASE signal WHEN 'flagged' THEN 0 WHEN 'task' THEN 0 ELSE 1 END, created DESC"
                             ).fetchall()
        return [r for r in (self._row(x) for x in rows) if r is not None and self._shown(r)][:limit]

    def count_pending(self) -> int:
        if self.hidden is not None:
            return len(self.pending())
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM todo_suggestions WHERE status='pending'").fetchone()[0])

    def _set(self, sid: str, status: str, todo_id: str = "") -> dict:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT status FROM todo_suggestions WHERE id=?", (sid,)).fetchone()
            if r is None:
                raise KeyError(sid)
            if r[0] != "pending":
                raise ValueError(f"that suggestion is already {r[0]}")
            c.execute("UPDATE todo_suggestions SET status=?, todo_id=?, updated=? WHERE id=?",
                      (status, todo_id, time.time(), sid))
        return self.get(sid)  # type: ignore[return-value]

    def mark_accepted(self, sid: str, todo_id: str) -> dict:
        return self._set(sid, "accepted", todo_id)

    def dismiss(self, sid: str) -> dict:
        return self._set(sid, "dismissed")

    def forget_account(self, account: str) -> int:
        """An account was removed: its waiting suggestions go (dismissals stay remembered)."""
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM todo_suggestions WHERE account=? AND status='pending'", (account,)).rowcount

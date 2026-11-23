"""The owner's mailing lists and what became of each unsubscribe (monkey.db, local only).

Rows are upserted by each read-only scan (counts, last received, the newest unsubscribe methods) and keep their status
across scans. Unsubscribe results are recorded per list and in a small log:
    done            the list's server accepted it (one-click), the email was sent, or the page confirmed it
    waiting_send    an unsubscribe email is drafted; the owner presses Send on the draft card
    needs_manual    Monkey couldn't finish it (no usable method, an unclear page, computer tasks off)
    failed          the list's server refused it, or something broke
    kept            the owner chose to keep the list (hidden from suggestions)
Verification: `verify_after` (default 7 days after "done"). If mail from the list keeps arriving after a 2-day grace
period it's "still_arriving"; past `verify_after` with nothing new it's "quiet".

The unsubscribe URLs are kept here (they're needed to act), but never logged, sent to Claude or shown in full.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path

from .scan import ListGroup

GRACE_S = 2 * 86400           # RFC 8058 asks lists to stop within two days
VERIFY_DAYS = 7
STATUSES = ("active", "queued", "waiting_send", "done", "needs_manual", "failed", "kept")

COLUMNS: dict[str, str] = {
    "id": "TEXT PRIMARY KEY",
    "account": "TEXT NOT NULL",
    "account_label": "TEXT NOT NULL DEFAULT ''",
    "list_key": "TEXT NOT NULL",
    "sender": "TEXT NOT NULL DEFAULT ''",
    "sender_email": "TEXT NOT NULL DEFAULT ''",
    "list_id": "TEXT NOT NULL DEFAULT ''",
    "subject": "TEXT NOT NULL DEFAULT ''",
    "count_90d": "INTEGER NOT NULL DEFAULT 0",
    "unread_90d": "INTEGER NOT NULL DEFAULT 0",
    "first_received": "REAL",
    "last_received": "REAL",
    "one_click_url": "TEXT NOT NULL DEFAULT ''",
    "mailto": "TEXT NOT NULL DEFAULT ''",
    "web_url": "TEXT NOT NULL DEFAULT ''",
    "status": "TEXT NOT NULL DEFAULT 'active'",
    "method_used": "TEXT NOT NULL DEFAULT ''",
    "result": "TEXT NOT NULL DEFAULT ''",
    "result_at": "REAL",
    "verify_after": "REAL",
    "verify_status": "TEXT NOT NULL DEFAULT ''",     # '' | waiting | quiet | still_arriving
    "last_after": "REAL",                            # newest mail seen after the unsubscribe (past the grace period)
    "draft_id": "TEXT NOT NULL DEFAULT ''",
    "task_id": "TEXT NOT NULL DEFAULT ''",
    "screenshot": "TEXT NOT NULL DEFAULT ''",
    "scanned_at": "REAL",
}
PUBLIC = ("id", "account", "account_label", "sender", "sender_email", "list_id", "subject", "count_90d", "unread_90d",
          "last_received", "status", "method_used", "result", "result_at", "verify_after", "verify_status",
          "last_after", "draft_id", "task_id", "screenshot")


def list_row_id(account: str, key: str) -> str:
    return "ml_" + hashlib.sha256(f"{account}\n{key}".encode()).hexdigest()[:12]


class MailingListStore:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute(f"CREATE TABLE IF NOT EXISTS mailing_lists({', '.join(f'{k} {v}' for k, v in COLUMNS.items())})")
            have = {r[1] for r in c.execute("PRAGMA table_info(mailing_lists)")}
            for name, decl in COLUMNS.items():
                if name not in have:
                    c.execute(f"ALTER TABLE mailing_lists ADD COLUMN {name} {decl.replace('PRIMARY KEY', '')}")
            c.execute("CREATE TABLE IF NOT EXISTS mailing_unsub_log(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                      "list_id TEXT, ts REAL, method TEXT, outcome TEXT, detail TEXT)")

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    # ---- scans -----------------------------------------------------------------------------------------------------
    def upsert(self, groups: list[ListGroup], now: float | None = None) -> int:
        """Store a scan. Rows already unsubscribed get their verification updated from the new last_received."""
        now = now or time.time()
        n = 0
        with self._lock, self._conn() as c:
            for g in groups:
                rid = list_row_id(g.account, g.key)
                last = g.last_received.timestamp()
                cur = c.execute("SELECT status, result_at, last_after FROM mailing_lists WHERE id=?", (rid,)).fetchone()
                vals = {"account": g.account, "account_label": g.account_label, "list_key": g.key, "sender": g.sender,
                        "sender_email": g.sender_email, "list_id": g.list_id, "subject": g.subject,
                        "count_90d": g.count, "unread_90d": g.unread, "first_received": g.first_received.timestamp(),
                        "last_received": last, "one_click_url": g.methods.get("one_click", ""),
                        "mailto": g.methods.get("mailto", ""), "web_url": g.methods.get("web", ""), "scanned_at": now}
                if cur is None:
                    vals["id"] = rid
                    cols = ", ".join(vals)
                    c.execute(f"INSERT INTO mailing_lists({cols}) VALUES ({', '.join('?' * len(vals))})",
                              tuple(vals.values()))
                else:
                    if cur["status"] == "done" and cur["result_at"] and last > cur["result_at"] + GRACE_S:
                        vals["last_after"] = max(last, cur["last_after"] or 0)
                        vals["verify_status"] = "still_arriving"
                    c.execute(f"UPDATE mailing_lists SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?",
                              (*vals.values(), rid))
                n += 1
        return n

    # ---- reads -----------------------------------------------------------------------------------------------------
    @staticmethod
    def _pub(r) -> dict:
        d = {k: r[k] for k in PUBLIC}
        d["methods"] = [m for m, col in (("one_click", "one_click_url"), ("mailto", "mailto"), ("web", "web_url"))
                        if r[col]]
        return d

    def all(self, include_kept: bool = True) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM mailing_lists ORDER BY count_90d DESC, sender").fetchall()
        return [self._pub(r) for r in rows if include_kept or r["status"] != "kept"]

    def get(self, rid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM mailing_lists WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None

    def public(self, rid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM mailing_lists WHERE id=?", (rid,)).fetchone()
        return self._pub(r) if r else None

    def log(self, rid: str | None = None) -> list[dict]:
        with self._conn() as c:
            q = "SELECT list_id, ts, method, outcome, detail FROM mailing_unsub_log"
            rows = c.execute(q + (" WHERE list_id=? ORDER BY id" if rid else " ORDER BY id"), (rid,) if rid else ())
            return [dict(r) for r in rows]

    # ---- results ---------------------------------------------------------------------------------------------------
    def record(self, rid: str, status: str, method: str = "", detail: str = "", now: float | None = None,
               **extra) -> dict:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status}")
        now = now or time.time()
        sets = {"status": status, "result": detail[:300], "result_at": now}
        if method:
            sets["method_used"] = method
        if status == "done":
            sets.update(verify_after=now + VERIFY_DAYS * 86400, verify_status="waiting", last_after=None)
        for k in ("draft_id", "task_id", "screenshot"):
            if k in extra:
                sets[k] = str(extra[k] or "")
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE mailing_lists SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), rid))
            if status not in ("queued",):
                c.execute("INSERT INTO mailing_unsub_log(list_id, ts, method, outcome, detail) VALUES (?,?,?,?,?)",
                          (rid, now, method, status, detail[:300]))
        return self.public(rid) or {}

    def verify_due(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        with self._conn() as c:
            rows = c.execute("SELECT * FROM mailing_lists WHERE status='done' AND verify_status='waiting' "
                             "AND verify_after<=?", (now,)).fetchall()
        return [dict(r) for r in rows]

    def finish_verification(self, now: float | None = None) -> list[str]:
        """After a fresh scan: waiting rows past verify_after with nothing new become quiet."""
        now = now or time.time()
        with self._lock, self._conn() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM mailing_lists WHERE status='done' AND "
                                           "verify_status='waiting' AND verify_after<=?", (now,))]
            c.execute("UPDATE mailing_lists SET verify_status='quiet' WHERE status='done' AND verify_status='waiting' "
                      "AND verify_after<=?", (now,))
        return ids

    def forget_account(self, account: str) -> None:
        with self._lock, self._conn() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM mailing_lists WHERE account=?", (account,))]
            c.execute("DELETE FROM mailing_lists WHERE account=?", (account,))
            c.executemany("DELETE FROM mailing_unsub_log WHERE list_id=?", [(i,) for i in ids])


def suggest(rows: list[dict], limit: int = 5) -> list[dict]:
    """Lists worth unsubscribing from: frequent and mostly unopened. A sentence Monkey can say, per list."""
    out = []
    for r in rows:
        if r["status"] != "active" or r["count_90d"] < 6:
            continue
        unread = r["unread_90d"] / max(1, r["count_90d"])
        if unread < 0.75:
            continue
        per_month = max(1, round(r["count_90d"] / 3))
        opened = "never open them" if unread >= 0.97 else f"open only {round((1 - unread) * 100)}% of them"
        out.append({"id": r["id"], "sender": r["sender"], "per_month": per_month, "unread_pct": round(unread * 100),
                    "say": f"You get about {per_month} emails a month from {r['sender']} and {opened}."})
    out.sort(key=lambda s: -s["per_month"])
    return out[:limit]

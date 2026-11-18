"""Model price table + a spend ledger so Monkey can respect a monthly budget."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"

# USD per 1M tokens: (input, output, cache_read, cache_write_5m)
PRICES: dict[str, tuple[float, float, float, float]] = {
    OPUS: (4.00, 20.00, 0.20, 5.00),
    SONNET: (2.00, 10.00, 0.10, 2.50),
    HAIKU: (0.10, 0.50, 0.01, 0.125),
}
WEB_SEARCH_USD = 10.0 / 1000  # per search request


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    web_searches: int = 0

    @classmethod
    def from_response(cls, usage) -> "Usage":
        if usage is None:
            return cls()
        stu = getattr(usage, "server_tool_use", None)
        return cls(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            web_searches=(getattr(stu, "web_search_requests", 0) or 0) if stu else 0,
        )


def cost_usd(model: str, u: Usage) -> float:
    inp, out, cread, cwrite = PRICES.get(model, PRICES[OPUS])
    return (
        u.input_tokens * inp
        + u.output_tokens * out
        + u.cache_read_input_tokens * cread
        + u.cache_creation_input_tokens * cwrite
    ) / 1_000_000 + u.web_searches * WEB_SEARCH_USD


class Ledger:
    """Append-only spend log in SQLite."""

    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS spend(
                    ts TEXT, model TEXT, effort TEXT, purpose TEXT,
                    input INTEGER, output INTEGER, cache_read INTEGER, cache_write INTEGER,
                    searches INTEGER, usd REAL)"""
            )

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def record(self, model: str, effort: str, purpose: str, u: Usage) -> float:
        usd = cost_usd(model, u)
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO spend VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    model, effort, purpose,
                    u.input_tokens, u.output_tokens,
                    u.cache_read_input_tokens, u.cache_creation_input_tokens,
                    u.web_searches, usd,
                ),
            )
        return usd

    def month_to_date(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self._conn() as c:
            row = c.execute("SELECT COALESCE(SUM(usd),0) FROM spend WHERE ts >= ?", (start,)).fetchone()
        return float(row[0])

    def breakdown(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self._conn() as c:
            rows = c.execute(
                "SELECT model, COUNT(*), SUM(usd) FROM spend WHERE ts >= ? GROUP BY model ORDER BY 3 DESC",
                (start,),
            ).fetchall()
        return [{"model": m, "calls": n, "usd": round(u or 0, 4)} for m, n, u in rows]

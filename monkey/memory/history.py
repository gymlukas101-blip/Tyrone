"""Cross-conversation history: every session's messages and a dated episode summary, searchable with SQLite FTS5,
plus a search index over the markdown facts (the files stay the source of truth; this is only an index).

Lives in the existing monkey.db. Nothing here is uploaded anywhere; Monkey sends excerpts to Claude only when a
search finds them relevant to what you asked.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from . import facts as F

STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "it", "my", "me", "i", "you", "we",
        "what", "whats", "what's", "did", "do", "does", "was", "were", "about", "that", "this", "with", "at", "be",
        "are", "can", "could", "would", "should", "tell", "remind", "remember", "know", "again", "last", "time",
        "how", "when", "where", "who", "which", "said", "say", "told", "any", "our", "monkey", "hey", "yo", "pls",
        "please", "up", "so", "from", "have", "has", "had", "just", "like", "get", "got"}


@dataclass
class Hit:
    kind: str                 # fact | episode | message
    ref: str                  # fact id, or session id (+ message id)
    text: str
    date: str
    source: str               # file name for facts; "conversation" / "episode summary"
    status: str = "current"
    score: float = 0.0
    sensitive: bool = False

    def cite(self) -> str:
        tag = {"fact": f"{self.source} {self.ref}", "episode": f"episode {self.date}",
               "message": f"conversation {self.date}"}[self.kind]
        flag = "" if self.status == "current" else f" [{self.status}]"
        return f"[{tag}{flag}] {self.text}"


def _stem(w: str) -> str:
    """Tiny stemmer so a fact's words match the user's own wording: live/lives/living/lived → "liv"."""
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith(("sses", "shes", "ches", "xes", "zes")):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    for suf in ("ing", "ed"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    return w[:-1] if len(w) > 3 and w.endswith("e") else w


def _stems(text: str) -> list[str]:
    """Whole words, lower-cased, stop words dropped, light stemming ("lives" → "live", but "olives" ≠ "live")."""
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP]


def terms(query: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", query.lower())
    out = []
    for w in words:
        if w in STOP or len(w) < 2:
            continue
        if w not in out:
            out.append(w)
    return out[:12]


def fts_query(query: str) -> str:
    """OR of quoted terms with prefix matching for longer words (BBU -> "bbu"*, battles -> "battle"*)."""
    parts = []
    for t in terms(query):
        stem = t[:-1] if len(t) > 4 and t.endswith("s") else t
        parts.append(f'"{stem}"*' if len(stem) >= 4 else f'"{stem}"')
    return " OR ".join(parts)


class HistoryStore:
    def __init__(self, db_path: Path | str, retention_days: int = 365):
        self.db_path = str(db_path)
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._fact_mtimes: dict[str, float] = {}
        with self._conn() as c:
            self.fts = self._has_fts(c)
            c.executescript("""
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, started REAL, ended REAL, status TEXT);
                CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, ts REAL,
                    role TEXT, text TEXT, source TEXT);
                CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id);
                CREATE TABLE IF NOT EXISTS episodes(session_id TEXT PRIMARY KEY, day TEXT, summary TEXT,
                    topics TEXT, decisions TEXT, open_items TEXT, source TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY, file TEXT, section TEXT, text TEXT, src TEXT,
                    day TEXT, status TEXT, sensitive INTEGER);
                CREATE TABLE IF NOT EXISTS tombstones(hash TEXT, kind TEXT, day TEXT);
            """)
            if self.fts:
                c.executescript("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(text, content='messages',
                        content_rowid='id', tokenize='porter unicode61');
                    CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                        INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text); END;
                    CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                        INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.id, old.text); END;
                    CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(session_id UNINDEXED, body,
                        tokenize='porter unicode61');
                    CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(id UNINDEXED, body,
                        tokenize='porter unicode61');
                """)

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    @staticmethod
    def _has_fts(c) -> bool:
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
            c.execute("DROP TABLE _fts_probe")
            return True
        except sqlite3.OperationalError:
            return False

    # ------------------------------------------------------------------ sessions + messages
    def start_session(self, sid: str | None = None) -> str:
        sid = sid or uuid.uuid4().hex[:12]
        with self._lock, self._conn() as c:
            c.execute("INSERT OR IGNORE INTO sessions(id, started, ended, status) VALUES (?,?,NULL,'active')",
                      (sid, time.time()))
        return sid

    def add_message(self, sid: str, role: str, text: str, source: str = "voice") -> int:
        text = (text or "").strip()
        if not text:
            return 0
        with self._lock, self._conn() as c:
            c.execute("INSERT OR IGNORE INTO sessions(id, started, ended, status) VALUES (?,?,NULL,'active')",
                      (sid, time.time()))
            cur = c.execute("INSERT INTO messages(session_id, ts, role, text, source) VALUES (?,?,?,?,?)",
                            (sid, time.time(), role, text[:20000], source))
            return int(cur.lastrowid)

    def end_session(self, sid: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE sessions SET ended=?, status='ended' WHERE id=? AND status='active'", (time.time(), sid))

    def close_stale(self, active_sid: str | None = None, idle_s: float = 20 * 60) -> list[str]:
        """Sessions left 'active' by a crash/quit and idle for a while count as ended."""
        cutoff = time.time() - idle_s
        with self._lock, self._conn() as c:
            rows = c.execute("""SELECT s.id FROM sessions s WHERE s.status='active' AND s.id != ? AND
                COALESCE((SELECT MAX(ts) FROM messages m WHERE m.session_id=s.id), s.started) < ?""",
                             (active_sid or "", cutoff)).fetchall()
            ids = [r["id"] for r in rows]
            c.executemany("UPDATE sessions SET ended=?, status='ended' WHERE id=?", [(time.time(), i) for i in ids])
        return ids

    def messages(self, sid: str) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT id, ts, role, text, source FROM messages WHERE session_id=? "
                                               "ORDER BY id", (sid,))]

    def needs_episode(self, min_user_msgs: int = 1) -> list[str]:
        with self._conn() as c:
            rows = c.execute("""SELECT s.id FROM sessions s WHERE s.status='ended'
                AND NOT EXISTS (SELECT 1 FROM episodes e WHERE e.session_id=s.id)
                AND (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id AND m.role='user') >= ?
                ORDER BY s.started""", (min_user_msgs,)).fetchall()
        return [r["id"] for r in rows]

    # ------------------------------------------------------------------ episodes
    def add_episode(self, sid: str, summary: str, topics: list[str], decisions: list[str], open_items: list[str],
                    source: str) -> None:
        with self._conn() as c:
            row = c.execute("SELECT MIN(ts) t FROM messages WHERE session_id=?", (sid,)).fetchone()
        day = datetime.fromtimestamp(row["t"] or time.time()).date().isoformat()
        body = " ".join([summary, *topics, *decisions, *open_items])
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO episodes VALUES (?,?,?,?,?,?,?,?)",
                      (sid, day, summary, json.dumps(topics), json.dumps(decisions), json.dumps(open_items),
                       source, time.time()))
            if self.fts:
                c.execute("DELETE FROM episodes_fts WHERE session_id=?", (sid,))
                c.execute("INSERT INTO episodes_fts(session_id, body) VALUES (?,?)", (sid, body))

    def recent_episodes(self, n: int = 2, exclude: str | None = None) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM episodes WHERE session_id != ? ORDER BY day DESC, created DESC LIMIT ?",
                             (exclude or "", n)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("topics", "decisions", "open_items"):
                d[k] = json.loads(d[k] or "[]")
            out.append(d)
        return out

    # ------------------------------------------------------------------ fact index (from the markdown files)
    def index_facts(self, root: Path, force: bool = False) -> int:
        root = Path(root)
        rels = F.memory_files(root)
        mt = {}
        for r in rels:
            try:
                mt[r] = (root / r).stat().st_mtime
            except OSError:
                pass
        if not force and mt == self._fact_mtimes:
            return 0
        facts = F.all_facts(root)
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM facts")
            if self.fts:
                c.execute("DELETE FROM facts_fts")
            for f in facts:
                c.execute("INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?,?,?,?)",
                          (f.id, f.file, f.section, f.text, f.src, f.date, f.status, int(f.sensitive)))
                if self.fts:
                    c.execute("INSERT INTO facts_fts(id, body) VALUES (?,?)",
                              (f.id, f"{f.section} {f.text} {Path(f.file).stem}"))
        self._fact_mtimes = mt
        return len(facts)

    # ------------------------------------------------------------------ search
    def search(self, query: str, scope: str = "all", limit: int = 6, include_superseded: bool = False,
               include_sensitive: bool = True, exclude_session: str | None = None,
               exclude_files: tuple[str, ...] = ()) -> list[Hit]:
        q = fts_query(query)
        if not q:
            return []
        hits: list[Hit] = []
        with self._conn() as c:
            if scope in ("all", "facts"):
                hits += self._search_facts(c, q, query, limit, include_superseded, include_sensitive, exclude_files)
            if scope in ("all", "episodes"):
                hits += self._search_episodes(c, q, query, limit, exclude_session)
            if scope in ("all", "conversations"):
                hits += self._search_messages(c, q, query, limit, exclude_session)
        if not include_sensitive:
            # Health, family, money... from past chats are never surfaced unless asked for (persona rule), whether
            # they sit in a fact, an episode summary or a raw message.
            hits = [h for h in hits if not (h.sensitive or (h.kind != "fact" and F.SENSITIVE.search(h.text or "")))]
        # current facts first, then recency; FTS bm25 is negative (lower = better)
        hits.sort(key=lambda h: (h.status != "current", h.score, -_day_num(h.date)))
        return hits[:limit]

    def _search_facts(self, c, q, raw, limit, sup, sens, excl):
        if self.fts:
            rows = c.execute("""SELECT f.*, bm25(facts_fts) s FROM facts_fts JOIN facts f ON f.id = facts_fts.id
                WHERE facts_fts MATCH ? ORDER BY s LIMIT ?""", (q, limit * 3)).fetchall()
        else:
            rows = self._like(c, "SELECT *, 0 s FROM facts WHERE ", "text", raw, limit * 3)
        out = []
        for r in rows:
            if (r["status"] != "current" and not sup) or (r["sensitive"] and not sens) or r["file"] in excl:
                continue
            out.append(Hit("fact", r["id"], r["text"], r["day"], r["file"], r["status"], float(r["s"]),
                           bool(r["sensitive"])))
        return out

    def _search_episodes(self, c, q, raw, limit, excl):
        if self.fts:
            rows = c.execute("""SELECT e.*, bm25(episodes_fts) s FROM episodes_fts JOIN episodes e
                ON e.session_id = episodes_fts.session_id WHERE episodes_fts MATCH ? ORDER BY s LIMIT ?""",
                             (q, limit)).fetchall()
        else:
            rows = self._like(c, "SELECT *, 0 s FROM episodes WHERE ", "summary", raw, limit)
        out = []
        for r in rows:
            if r["session_id"] == excl:
                continue
            items = json.loads(r["decisions"] or "[]") + json.loads(r["open_items"] or "[]")
            text = r["summary"] + (" | " + "; ".join(items) if items else "")
            out.append(Hit("episode", r["session_id"], text, r["day"], "episode summary", "current", float(r["s"])))
        return out

    def _search_messages(self, c, q, raw, limit, excl):
        if self.fts:
            rows = c.execute("""SELECT m.*, bm25(messages_fts) s FROM messages_fts JOIN messages m
                ON m.id = messages_fts.rowid WHERE messages_fts MATCH ? AND m.session_id != ? ORDER BY s LIMIT ?""",
                             (q, excl or "", limit)).fetchall()
        else:
            rows = [r for r in self._like(c, "SELECT *, 0 s FROM messages WHERE ", "text", raw, limit * 2)
                    if r["session_id"] != excl][:limit]
        return [Hit("message", f"{r['session_id']}#{r['id']}", f"{'You' if r['role'] == 'user' else 'Monkey'}: "
                    f"{r['text'][:300]}", datetime.fromtimestamp(r["ts"]).date().isoformat(), "conversation",
                    "current", float(r["s"])) for r in rows]

    @staticmethod
    def _like(c, sql, col, raw, limit):
        ts = terms(raw)
        if not ts:
            return []
        cond = " OR ".join(f"lower({col}) LIKE ?" for _ in ts)
        return c.execute(sql + f"({cond}) LIMIT ?", [f"%{t}%" for t in ts] + [limit]).fetchall()

    # ------------------------------------------------------------------ retention, export, delete
    def forget(self, text: str) -> dict:
        """Forget means forget: tombstone the fact and delete past messages and episode summaries that state it
        (all of its distinctive words present), so neither search nor per-turn recall brings it back."""
        self.tombstone(text)
        fact = _stems(text)
        need = max(1, -(-len(fact) * 4 // 5)) if fact else 0      # ceil(80%) of the distinctive words

        def says_it(body: str) -> bool:
            words = _stems(body or "")
            if not fact or not words:
                return False
            if len(fact) <= 2:                    # short facts: the same words, in order, next to each other
                n = len(fact)
                return any(words[i:i + n] == fact for i in range(len(words) - n + 1))
            have = set(words)                      # longer facts: most of the distinctive words, as whole words
            return sum(1 for t in fact if t in have) >= need
        msgs = eps = 0
        with self._lock, self._conn() as c:
            for r in c.execute("SELECT id, text FROM messages").fetchall():
                if says_it(r["text"]):
                    c.execute("DELETE FROM messages WHERE id = ?", (r["id"],))
                    msgs += 1
            for r in c.execute("SELECT session_id, summary, decisions, open_items FROM episodes").fetchall():
                body = " ".join([r["summary"] or ""] + json.loads(r["decisions"] or "[]") +
                                json.loads(r["open_items"] or "[]"))
                if says_it(body):
                    c.execute("DELETE FROM episodes WHERE session_id = ?", (r["session_id"],))
                    if self.fts:
                        c.execute("DELETE FROM episodes_fts WHERE session_id = ?", (r["session_id"],))
                    eps += 1
        return {"messages": msgs, "episodes": eps}

    def tombstone(self, text: str, kind: str = "fact") -> None:
        h = hashlib.sha256(F.normalize(text).encode()).hexdigest()
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO tombstones VALUES (?,?,?)", (h, kind, datetime.now().date().isoformat()))

    def prune(self, days: int | None = None) -> int:
        days = self.retention_days if days is None else days
        if days <= 0:
            return 0
        cutoff = time.time() - days * 86400
        return self._delete_where("started < ?", (cutoff,))

    def delete_all(self) -> int:
        return self._delete_where("1=1", ())

    def delete_session(self, sid: str) -> int:
        return self._delete_where("id = ?", (sid,))

    def _delete_where(self, where: str, args: tuple) -> int:
        with self._lock, self._conn() as c:
            ids = [r["id"] for r in c.execute(f"SELECT id FROM sessions WHERE {where}", args)]
            for sid in ids:
                c.execute("DELETE FROM messages WHERE session_id=?", (sid,))      # trigger cleans messages_fts
                c.execute("DELETE FROM episodes WHERE session_id=?", (sid,))
                if self.fts:
                    c.execute("DELETE FROM episodes_fts WHERE session_id=?", (sid,))
                c.execute("DELETE FROM sessions WHERE id=?", (sid,))
        return len(ids)

    def export(self) -> dict:
        with self._conn() as c:
            sessions = [dict(r) for r in c.execute("SELECT * FROM sessions ORDER BY started")]
            for s in sessions:
                s["messages"] = [dict(r) for r in c.execute(
                    "SELECT ts, role, text, source FROM messages WHERE session_id=? ORDER BY id", (s["id"],))]
                e = c.execute("SELECT * FROM episodes WHERE session_id=?", (s["id"],)).fetchone()
                s["episode"] = dict(e) if e else None
        return {"exported": datetime.now().isoformat(timespec="seconds"), "sessions": sessions}

    def stats(self) -> dict:
        with self._conn() as c:
            one = lambda q: c.execute(q).fetchone()[0]   # noqa: E731
            return {"sessions": one("SELECT COUNT(*) FROM sessions"), "messages": one("SELECT COUNT(*) FROM messages"),
                    "episodes": one("SELECT COUNT(*) FROM episodes"), "facts": one("SELECT COUNT(*) FROM facts"),
                    "fts": self.fts, "oldest": one("SELECT MIN(started) FROM sessions")}


def _day_num(day: str) -> int:
    try:
        return datetime.fromisoformat(day).toordinal()
    except (TypeError, ValueError):
        return 0


def hits_json(hits: list[Hit]) -> list[dict]:
    return [asdict(h) for h in hits]

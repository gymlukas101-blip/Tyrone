"""Canvas assignments with points, grades and submission status.

Needs a Canvas API token. At UW–Madison students request one through the Learn@UW
"Student Request for Canvas Access Token" form (kb.wisc.edu/156712) - an admin
creates it and sends it to you; activate it in Canvas, then paste it in Settings.
Without a token, Monkey falls back to the Calendar Feed (due dates only).

Checking an item off uses Canvas's own Planner "mark complete", so it shows up as
done in Canvas too (it does NOT submit anything).
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

from ..brain.assignments import Assignment, Group, compute_impacts

_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class LocalChecks:
    """Checkbox state kept on this PC (used for feed-only items or if Canvas sync fails)."""

    def __init__(self, db_path):
        self.db = str(db_path)
        with sqlite3.connect(self.db) as c:
            c.execute("CREATE TABLE IF NOT EXISTS checks(id TEXT PRIMARY KEY, done INTEGER, ts REAL)")

    def get(self) -> dict[str, bool]:
        with sqlite3.connect(self.db) as c:
            return {i: bool(d) for i, d in c.execute("SELECT id, done FROM checks")}

    def set(self, item_id: str, done: bool) -> None:
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT OR REPLACE INTO checks VALUES (?,?,?)", (item_id, int(done), time.time()))


class CanvasAPI:
    def __init__(self, base_url_getter, token_getter, http: httpx.Client | None = None):
        self._base = base_url_getter
        self._token = token_getter
        self._http = http
        self._overrides: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._cache: tuple[float, list[Assignment]] | None = None
        self.token_rejected = False

    def available(self) -> bool:
        return bool(self._token())

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=20)
        return self._http

    def _url(self, path: str) -> str:
        return self._base().rstrip("/") + path

    def _get_all(self, path: str, params: dict | list | None = None) -> list:
        headers = {"Authorization": f"Bearer {self._token()}"}
        url, out, pages = self._url(path), [], 0
        while url and pages < 20:
            r = self._client().get(url, params=params if pages == 0 else None, headers=headers)
            if r.status_code == 401:
                self.token_rejected = True          # expired/revoked; Settings + the morning brief say so
                raise RuntimeError("Canvas rejected the token (expired or revoked). Request a new one.")
            r.raise_for_status()
            self.token_rejected = False
            data = r.json()
            out.extend(data if isinstance(data, list) else [data])
            m = _NEXT.search(r.headers.get("link", ""))
            url, pages = (m.group(1) if m else None), pages + 1
        return out

    # ---- read ----------------------------------------------------------
    def assignments(self, days_back: int = 21, days_ahead: int = 30, use_cache: bool = True) -> list[Assignment]:
        if use_cache and self._cache and time.time() - self._cache[0] < 120:
            return self._cache[1]
        now = datetime.now(timezone.utc)
        lo, hi = now - timedelta(days=days_back), now + timedelta(days=days_ahead)
        courses = self._get_all("/api/v1/courses", [
            ("enrollment_state", "active"), ("enrollment_type", "student"), ("per_page", "50"),
            ("include[]", "total_scores"), ("include[]", "current_grading_period_scores"),
        ])
        self._load_overrides()
        result: list[Assignment] = []
        for c in courses:
            if not isinstance(c, dict) or c.get("access_restricted_by_date"):
                continue
            cid = str(c["id"])
            short = c.get("course_code") or c.get("name") or cid
            enr = next((e for e in c.get("enrollments", []) if e.get("type") == "student"), {})
            grade = enr.get("current_period_computed_current_score")
            if grade is None:
                grade = enr.get("computed_current_score")
            groups_raw = self._get_all(f"/api/v1/courses/{cid}/assignment_groups", [
                ("include[]", "assignments"), ("include[]", "submission"), ("per_page", "50"),
            ])
            groups: dict[str, Group] = {}
            course_items: list[Assignment] = []
            for g in groups_raw:
                gid = str(g.get("id"))
                groups[gid] = Group(gid, float(g.get("group_weight") or 0), [])
                for a in g.get("assignments") or []:
                    if not a.get("published", True):
                        continue
                    sub = a.get("submission") or {}
                    state = sub.get("workflow_state") or ""
                    aid = str(a["id"])
                    item = Assignment(
                        id=f"canvas:{cid}:{aid}", title=a.get("name", "(untitled)"), course=short,
                        course_id=cid, assignment_id=aid, due=_dt(a.get("due_at")),
                        points=a.get("points_possible"), group_id=gid, course_grade=grade,
                        submitted=state in ("submitted", "pending_review") or bool(sub.get("submitted_at")),
                        graded=state == "graded" and sub.get("score") is not None and not sub.get("missing"),
                        excused=bool(sub.get("excused")), missing=bool(sub.get("missing")),
                        late=bool(sub.get("late")), score=sub.get("score"), url=a.get("html_url", ""),
                        marked_complete=bool(self._overrides.get(aid, {}).get("marked_complete")),
                    )
                    item.extra["omit"] = bool(a.get("omit_from_final_grade"))
                    course_items.append(item)
            compute_impacts(course_items, groups, bool(c.get("apply_assignment_group_weights")))
            for it in course_items:
                # Keep the useful window: missing work any time, everything else near now.
                if it.missing or (it.due and lo <= it.due <= hi) or (it.due is None and not it.done):
                    result.append(it)
        self._cache = (time.time(), result)
        return result

    def _load_overrides(self) -> None:
        try:
            rows = self._get_all("/api/v1/planner/overrides", {"per_page": "100"})
            self._overrides = {str(o.get("plannable_id")): o for o in rows
                               if o.get("plannable_type") in ("assignment", "Assignment")}
        except httpx.HTTPError:
            self._overrides = {}

    # ---- write (planner checkbox) --------------------------------------
    def set_complete(self, assignment_id: str, done: bool) -> None:
        headers = {"Authorization": f"Bearer {self._token()}"}
        with self._lock:
            existing = self._overrides.get(str(assignment_id))
            if not existing:
                r = self._client().post(self._url("/api/v1/planner/overrides"), headers=headers, data={
                    "plannable_type": "assignment", "plannable_id": str(assignment_id),
                    "marked_complete": str(done).lower(),
                })
                if r.status_code in (400, 409):   # already has an override we didn't know about
                    self._load_overrides()
                    existing = self._overrides.get(str(assignment_id))
                    if not existing:
                        r.raise_for_status()
            if existing and existing.get("id"):
                r = self._client().put(self._url(f"/api/v1/planner/overrides/{existing['id']}"),
                                       data={"marked_complete": str(done).lower()}, headers=headers)
            r.raise_for_status()
            self._overrides[str(assignment_id)] = r.json()
            self._cache = None


_COURSE = re.compile(r"\[([^\]]+)\]\s*$")


class AssignmentBoard:
    """What the checklist UI and Monkey's tools use: Canvas API if there's a token, else the calendar feed."""

    def __init__(self, api: CanvasAPI, feed, checks: LocalChecks):
        self.api, self.feed, self.checks = api, feed, checks

    def _from_feed(self) -> list[Assignment]:
        now = datetime.now(timezone.utc)
        out = []
        for e in self.feed.list_events(now - timedelta(days=7), now + timedelta(days=30)):
            m = _COURSE.search(e.title)
            aid = e.id.rsplit("-", 1)[-1] if e.id.startswith("event-assignment-") else ""
            out.append(Assignment(
                id=f"ics:{e.id}", title=_COURSE.sub("", e.title).strip(), course=m.group(1) if m else "Canvas",
                assignment_id=aid, due=e.start, url=e.web_link, source="ics",
            ))
        return out

    def load(self, refresh: bool = False) -> dict:
        from ..brain.assignments import rank

        if self.api.available():
            items, source = self.api.assignments(use_cache=not refresh), "canvas"
        elif self.feed.available():
            items, source = self._from_feed(), "feed"
        else:
            return {"source": "none", "todo": [], "done": [], "stats": {}}
        local = self.checks.get()
        for it in items:
            if it.id in local:
                it.marked_complete = local[it.id]  # your last check/uncheck wins
        todo, done = rank(items)
        now = datetime.now(timezone.utc)
        week = now + timedelta(days=7)
        in_week = [a for a in items if a.due and now - timedelta(days=1) <= a.due <= week]
        return {
            "source": source,
            "todo": [a.to_dict() for a in todo],
            "done": [a.to_dict() for a in done[:30]],
            "stats": {"week_total": len(in_week), "week_done": sum(a.done for a in in_week),
                      "missing": sum(a.missing and not a.done for a in items),
                      "critical": sum(a.tier == "critical" for a in todo)},
        }

    def toggle(self, item_id: str, done: bool) -> dict:
        """Check/uncheck. Returns {"synced": bool} - synced means Canvas's planner was updated too."""
        self.checks.set(item_id, done)
        if item_id.startswith("canvas:") and self.api.available():
            try:
                self.api.set_complete(item_id.rsplit(":", 1)[-1], done)
                return {"synced": True}
            except httpx.HTTPError:
                return {"synced": False}
        return {"synced": False}

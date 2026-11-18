"""Rank Canvas assignments by what actually matters.

Priority (0-100) blends three things, then adds a bump for missing work:
  * grade impact (45%) - how much of your final grade it's worth (uses the course's
    assignment-group weights when the course is weighted, otherwise points / total points);
    10%+ of the grade maxes this out.
  * urgency (35%)      - missing/overdue > due in 24h > 48h > 3 days > a week > two weeks.
  * grade need (20%)   - the lower your current grade in that course, the more it matters
    (95%+ = no boost, 70% or lower = full boost).
  * missing            - +10.
Tiers: critical >= 70, high >= 50, normal >= 30, low < 30. Done work is listed separately.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class Assignment:
    id: str                         # "canvas:<course_id>:<assignment_id>" or "ics:<uid>"
    title: str
    course: str
    course_id: str = ""
    assignment_id: str = ""
    due: datetime | None = None
    points: float | None = None
    group_id: str = ""
    impact_pct: float | None = None  # % of final course grade
    course_grade: float | None = None
    submitted: bool = False
    graded: bool = False
    excused: bool = False
    missing: bool = False
    late: bool = False
    score: float | None = None
    marked_complete: bool = False    # checked off (in Canvas planner or locally)
    url: str = ""
    source: str = "canvas"           # "canvas" | "ics"
    # filled in by rank()
    priority: int = 0
    tier: str = ""
    reason: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return self.submitted or self.graded or self.excused or self.marked_complete

    def to_dict(self) -> dict:
        d = asdict(self)
        d["due"] = self.due.isoformat() if self.due else None
        d["done"] = self.done
        d.pop("extra", None)
        return d


@dataclass
class Group:
    id: str
    weight: float
    assignments: list[dict]          # each: {"points": float, "omit": bool}


def compute_impacts(assignments: list[Assignment], groups: dict[str, Group], weighted: bool) -> None:
    """Fill impact_pct (% of the final grade) for one course's assignments, in place."""
    counted = [a for a in assignments if a.points and a.points > 0 and not a.extra.get("omit")]
    if not counted:
        return
    if weighted and groups:
        group_pts: dict[str, float] = {}
        for a in counted:
            group_pts[a.group_id] = group_pts.get(a.group_id, 0.0) + float(a.points or 0)
        live = {gid: g for gid, g in groups.items() if group_pts.get(gid, 0) > 0 and g.weight > 0}
        total_w = sum(g.weight for g in live.values())
        if total_w > 0:
            for a in counted:
                g = live.get(a.group_id)
                if g:
                    a.impact_pct = round(float(a.points) / group_pts[a.group_id] * g.weight / total_w * 100, 2)
            return
    total = sum(float(a.points or 0) for a in counted)
    for a in counted:
        a.impact_pct = round(float(a.points) / total * 100, 2)


def _urgency(a: Assignment, now: datetime) -> tuple[float, str]:
    if a.missing:
        return 1.0, "MISSING"
    if a.due is None:
        return 0.1, "no due date"
    due = a.due if a.due.tzinfo else a.due.replace(tzinfo=timezone.utc)
    hours = (due - now).total_seconds() / 3600
    if hours < 0:
        return 1.0, f"overdue by {_human(-hours)}"
    label = f"due in {_human(hours)}"
    for limit, u in ((24, 0.9), (48, 0.75), (72, 0.6), (168, 0.4), (336, 0.2)):
        if hours <= limit:
            return u, label
    return 0.1, label


def _human(hours: float) -> str:
    if hours < 1:
        return f"{max(1, round(hours * 60))}m"
    if hours < 48:
        return f"{round(hours)}h"
    return f"{round(hours / 24)}d"


def score(a: Assignment, now: datetime | None = None) -> Assignment:
    now = now or datetime.now(timezone.utc)
    if a.done:
        a.priority, a.tier = 0, "done"
        a.reason = "graded" if a.graded else "submitted" if a.submitted else "excused" if a.excused else "checked off"
        return a
    urgency, when = _urgency(a, now)
    if a.impact_pct is not None:
        impact = min(1.0, a.impact_pct / 10)
    elif a.points:
        impact = min(1.0, float(a.points) / 100)
    else:
        impact = 0.2
    need = 0.4 if a.course_grade is None else max(0.0, min(1.0, (95 - a.course_grade) / 25))
    p = 100 * (0.45 * impact + 0.35 * urgency + 0.20 * need) + (10 if a.missing else 0)
    a.priority = int(round(min(100, p)))
    a.tier = "critical" if a.priority >= 70 else "high" if a.priority >= 50 else "normal" if a.priority >= 30 else "low"
    bits = []
    if a.impact_pct is not None:
        bits.append(f"~{a.impact_pct:.1f}% of your grade")
    elif a.points:
        bits.append(f"{a.points:g} pts")
    bits.append(when)
    if a.course_grade is not None:
        bits.append(f"you're at {a.course_grade:.0f}% in {a.course}")
    a.reason = " · ".join(bits)
    return a


def rank(assignments: list[Assignment], now: datetime | None = None) -> tuple[list[Assignment], list[Assignment]]:
    """Returns (todo sorted by priority, done sorted by due date desc)."""
    now = now or datetime.now(timezone.utc)
    for a in assignments:
        score(a, now)
    far = datetime.max.replace(tzinfo=timezone.utc)
    todo = sorted((a for a in assignments if not a.done),
                  key=lambda a: (-a.priority, a.due or far))
    done = sorted((a for a in assignments if a.done),
                  key=lambda a: a.due or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return todo, done

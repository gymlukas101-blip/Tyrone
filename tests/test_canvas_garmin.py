import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from monkey.brain.assignments import Assignment, Group, compute_impacts, rank, score
from monkey.brain.router import Router
from monkey.integrations.canvas_api import AssignmentBoard, CanvasAPI, LocalChecks
from monkey.integrations.garmin import downsample_hr, parse_health, resolve_day, summarize

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


def a(**kw):
    base = dict(id="x", title="t", course="CS 400")
    base.update(kw)
    return Assignment(**base)


# ------------------------------------------------------------------ impact math
def test_unweighted_impact_is_points_share():
    items = [a(id="1", points=50), a(id="2", points=150), a(id="3", points=0)]
    compute_impacts(items, {}, weighted=False)
    assert items[0].impact_pct == 25.0 and items[1].impact_pct == 75.0 and items[2].impact_pct is None


def test_weighted_impact_uses_group_weights():
    # Exams 60% (one 100-pt exam), Homework 40% (four 10-pt HWs)
    exam = a(id="e", points=100, group_id="g1")
    hws = [a(id=f"h{i}", points=10, group_id="g2") for i in range(4)]
    groups = {"g1": Group("g1", 60, []), "g2": Group("g2", 40, [])}
    compute_impacts([exam, *hws], groups, weighted=True)
    assert exam.impact_pct == 60.0
    assert hws[0].impact_pct == 10.0


def test_weighted_impact_renormalizes_empty_groups():
    hw = a(id="h", points=10, group_id="g2")
    groups = {"g1": Group("g1", 50, []), "g2": Group("g2", 50, [])}  # no exams posted yet
    compute_impacts([hw], groups, weighted=True)
    assert hw.impact_pct == 100.0


def test_omitted_assignments_dont_count():
    x, y = a(id="1", points=10), a(id="2", points=10)
    y.extra["omit"] = True
    compute_impacts([x, y], {}, weighted=False)
    assert x.impact_pct == 100.0 and y.impact_pct is None


# ------------------------------------------------------------------ priority
def test_big_assignment_due_soon_is_critical():
    x = score(a(impact_pct=15, course_grade=84, due=NOW + timedelta(hours=20)), NOW)
    assert x.tier == "critical" and "15.0% of your grade" in x.reason and "due in 20h" in x.reason


def test_tiny_far_assignment_with_high_grade_is_low():
    x = score(a(impact_pct=0.5, course_grade=97, due=NOW + timedelta(days=5)), NOW)
    assert x.tier == "low"


def test_missing_gets_bumped():
    x = score(a(impact_pct=2, course_grade=80, missing=True, due=NOW - timedelta(days=2)), NOW)
    assert x.tier in ("high", "critical") and "MISSING" in x.reason


def test_lower_grade_raises_priority():
    lo = score(a(impact_pct=5, course_grade=72, due=NOW + timedelta(days=3)), NOW)
    hi = score(a(impact_pct=5, course_grade=98, due=NOW + timedelta(days=3)), NOW)
    assert lo.priority > hi.priority


def test_done_items_separated():
    todo, done = rank([a(id="1", impact_pct=5, due=NOW + timedelta(days=1)),
                       a(id="2", submitted=True, due=NOW), a(id="3", marked_complete=True, due=NOW)], NOW)
    assert [x.id for x in todo] == ["1"] and {x.id for x in done} == {"2", "3"}
    assert done[0].tier == "done"


# ------------------------------------------------------------------ Canvas API (mocked server)
def canvas_handler(calls):
    overrides = []
    due_soon = (datetime.now(timezone.utc) + timedelta(hours=30)).isoformat().replace("+00:00", "Z")
    past = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat().replace("+00:00", "Z")

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, req.content.decode() if req.content else ""))
        assert req.headers["authorization"] == "Bearer tok"
        p = req.url.path
        if p == "/api/v1/courses":
            return httpx.Response(200, json=[{
                "id": 1, "course_code": "COMP SCI 400", "apply_assignment_group_weights": True,
                "enrollments": [{"type": "student", "computed_current_score": 84.2}],
            }])
        if p == "/api/v1/courses/1/assignment_groups":
            if "page=2" in str(req.url):
                return httpx.Response(200, json=[{"id": 20, "group_weight": 40, "assignments": [
                    {"id": 201, "name": "HW 7", "points_possible": 10, "due_at": due_soon, "published": True,
                     "submission": {"workflow_state": "unsubmitted"}},
                    {"id": 202, "name": "HW 6", "points_possible": 10, "due_at": past, "published": True,
                     "submission": {"workflow_state": "unsubmitted", "missing": True}},
                    {"id": 203, "name": "HW 5", "points_possible": 10, "due_at": past, "published": True,
                     "submission": {"workflow_state": "graded", "score": 9}},
                ]}])
            return httpx.Response(200, json=[{"id": 10, "group_weight": 60, "assignments": [
                {"id": 101, "name": "Midterm", "points_possible": 100, "due_at": due_soon, "published": True,
                 "submission": {"workflow_state": "unsubmitted"}},
            ]}], headers={"link": '<https://canvas.test/api/v1/courses/1/assignment_groups?page=2>; rel="next"'})
        if p == "/api/v1/planner/overrides" and req.method == "GET":
            return httpx.Response(200, json=overrides)
        if p == "/api/v1/planner/overrides" and req.method == "POST":
            if overrides:
                return httpx.Response(400, json={"errors": "already exists"})
            overrides.append({"id": 77, "plannable_id": 201, "plannable_type": "assignment",
                              "marked_complete": "marked_complete=true" in req.content.decode()})
            return httpx.Response(200, json=overrides[0])
        if p == "/api/v1/planner/overrides/77":
            overrides[0]["marked_complete"] = "marked_complete=true" in req.content.decode()
            return httpx.Response(200, json=overrides[0])
        return httpx.Response(404)
    return handler


class NoFeed:
    def available(self):
        return False


def test_canvas_board_end_to_end(tmp_path):
    calls = []
    http = httpx.Client(transport=httpx.MockTransport(canvas_handler(calls)))
    api = CanvasAPI(lambda: "https://canvas.test", lambda: "tok", http=http)
    board = AssignmentBoard(api, NoFeed(), LocalChecks(tmp_path / "t.db"))
    b = board.load()
    assert b["source"] == "canvas"
    titles = [x["title"] for x in b["todo"]]
    # Missing HW worth 13% of the grade (still submittable) edges out the 60% midterm due in 30h.
    assert titles[:2] == ["HW 6", "Midterm"]
    assert "HW 6" in titles and "HW 5" not in titles   # missing shown, graded hidden from todo
    mid = b["todo"][1]
    assert mid["impact_pct"] == 60.0 and mid["course_grade"] == 84.2 and mid["tier"] == "critical"
    hw6 = next(x for x in b["todo"] if x["title"] == "HW 6")
    assert hw6["missing"] and hw6["impact_pct"] == pytest.approx(13.33, abs=0.01)
    assert b["stats"]["missing"] == 1

    # Check off HW 7 -> Canvas planner override created; it moves to done.
    r = board.toggle("canvas:1:201", True)
    assert r["synced"] and ("POST", "/api/v1/planner/overrides") in [(m, p) for m, p, _ in calls]
    b2 = board.load()
    assert "HW 7" in [x["title"] for x in b2["done"]]
    # Un-check -> PUT on the existing override.
    assert board.toggle("canvas:1:201", False)["synced"]
    assert any(m == "PUT" and p.endswith("/77") for m, p, _ in calls)
    assert "HW 7" in [x["title"] for x in board.load()["todo"]]


class Feed:
    def available(self):
        return True

    def list_events(self, start, end):
        from monkey.integrations.base import Event

        return [Event("event-assignment-55", "canvas", "Reading quiz [PSYCH 202]",
                      datetime.now(timezone.utc) + timedelta(days=1))]


def test_feed_fallback_and_local_checks(tmp_path):
    api = CanvasAPI(lambda: "https://canvas.test", lambda: "")
    board = AssignmentBoard(api, Feed(), LocalChecks(tmp_path / "t.db"))
    b = board.load()
    assert b["source"] == "feed" and b["todo"][0]["course"] == "PSYCH 202"
    assert b["todo"][0]["title"] == "Reading quiz"
    assert board.toggle(b["todo"][0]["id"], True) == {"synced": False}
    assert board.load()["todo"] == []


# ------------------------------------------------------------------ Garmin parsing
SLEEP = {"dailySleepDTO": {"sleepTimeSeconds": 26100, "deepSleepSeconds": 5400, "lightSleepSeconds": 14400,
                           "remSleepSeconds": 5700, "awakeSleepSeconds": 600,
                           "sleepScores": {"overall": {"value": 81, "qualifierKey": "GOOD"}}},
         "restingHeartRate": 52, "avgOvernightHrv": 61}
T0 = 1_763_442_000_000
HR = {"restingHeartRate": 51, "maxHeartRate": 148, "minHeartRate": 47,
      "heartRateValues": [[T0, 60], [T0 + 120_000, 64], [T0 + 360_000, None], [T0 + 400_000, 90], ["bad"]]}
STATS = {"totalSteps": 8421, "bodyBatteryMostRecentValue": 64, "averageStressLevel": 28}
HRV = {"hrvSummary": {"lastNightAvg": 61, "weeklyAvg": 58, "status": "BALANCED"}}


def test_parse_health():
    h = parse_health("2026-11-18", SLEEP, HR, STATS, HRV)
    assert h["sleep"]["score"] == 81 and h["sleep"]["quality"] == "Good"
    assert h["sleep"]["stages_min"] == {"deep": 90, "light": 240, "rem": 95, "awake": 10}
    assert h["heart"]["resting"] == 51 and h["heart"]["max"] == 148
    assert h["heart"]["series"] == [[T0, 62], [T0 + 300_000, 90]]
    assert h["hrv"]["status"] == "Balanced"
    s = summarize(h)
    assert "sleep score 81" in s and "7h15m" in s and "8421 steps" in s


def test_parse_health_handles_missing_data():
    h = parse_health("2026-11-18", None, None, None, None)
    assert h["sleep"]["score"] is None and h["heart"]["series"] == []
    assert summarize(h) == "no data for that day"


def test_downsample_and_dates():
    assert downsample_hr([[0, 50], [1000, 70], [400_000, 80]]) == [[0, 60], [300_000, 80]]
    assert resolve_day("2026-11-01") == "2026-11-01"
    with pytest.raises(ValueError):
        resolve_day("someday")


# ------------------------------------------------------------------ routing
@pytest.mark.parametrize("q", ["what's due this week", "how did I sleep", "check off HW 7", "what's my heart rate"])
def test_lookups_route_to_sonnet_low(q):
    r = Router().route(q)
    assert r.model == "claude-sonnet-5-5" and r.effort == "low", r

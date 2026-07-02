# tests/test_tools_project_status_report.py
import datetime as dt
import json

from odoo_mcp import tools_workflows


# today is fixed at 2026-07-01 (cutoff 2026-07-08 with default lookahead 7).
PROJECTS = [
    {"id": 1, "name": "Alpha", "user_id": [5, "PM One"], "partner_id": [7, "Cust A"],
     "date_start": "2026-01-01", "date": "2026-06-01", "last_update_status": "on_track",
     "task_count": 10},   # past end date, PM says on_track -> off_track + divergent
    {"id": 2, "name": "Bravo", "user_id": [5, "PM One"], "partner_id": False,
     "date_start": "2026-01-01", "date": "2026-12-31", "last_update_status": "to_define",
     "task_count": 20},   # overdue milestone -> off_track, to_define -> not divergent
    {"id": 3, "name": "Charlie", "user_id": [6, "PM Two"], "partner_id": [8, "Cust B"],
     "date_start": "2026-01-01", "date": False, "last_update_status": "on_track",
     "task_count": 5},    # milestone due soon -> at_risk, PM says on_track -> divergent
    {"id": 4, "name": "Delta", "user_id": [6, "PM Two"], "partner_id": [9, "Cust C"],
     "date_start": "2026-01-01", "date": "2026-12-01", "last_update_status": "on_track",
     "task_count": 8},    # all milestones reached, future end -> on_track, not divergent
]

MILESTONES = [
    {"id": 20, "name": "M2", "deadline": "2026-06-15", "is_reached": False,
     "project_id": [2, "Bravo"]},                                   # Bravo overdue
    {"id": 30, "name": "M3", "deadline": "2026-07-05", "is_reached": False,
     "project_id": [3, "Charlie"]},                                 # Charlie soon
    {"id": 40, "name": "M4a", "deadline": "2026-01-01", "is_reached": True,
     "project_id": [4, "Delta"]},                                   # Delta reached
    {"id": 41, "name": "M4b", "deadline": "2026-02-01", "is_reached": True,
     "project_id": [4, "Delta"]},                                   # Delta reached
]


def _setup(fake_client, projects=PROJECTS, milestones=MILESTONES):
    fake_client.search_responses["project.project"] = projects
    fake_client.search_responses["project.milestone"] = milestones


def _fix_today(monkeypatch):
    monkeypatch.setattr(tools_workflows, "today_in_tz", lambda offset: dt.date(2026, 7, 1))


def _project_call(fake_client):
    return next(
        c for c in fake_client.calls
        if c["method"] == "search_read" and c["model"] == "project.project"
    )


def _milestone_call(fake_client):
    return next(
        c for c in fake_client.calls
        if c["method"] == "search_read" and c["model"] == "project.milestone"
    )


def test_builds_project_domain(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    tools_workflows.project_status_report(
        manager="PM", customer="Cust", project="Al",
        include_done=False, include_on_hold=False,
    )
    domain = _project_call(fake_client)["domain"]
    assert ("active", "=", True) in domain
    assert ("user_id.name", "ilike", "PM") in domain
    assert ("partner_id.name", "ilike", "Cust") in domain
    assert ("name", "ilike", "Al") in domain
    assert ("last_update_status", "!=", "done") in domain
    assert ("last_update_status", "!=", "on_hold") in domain


def test_milestone_domain_fetches_all_for_project_ids(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    tools_workflows.project_status_report()
    domain = _milestone_call(fake_client)["domain"]
    assert ("project_id", "in", [1, 2, 3, 4]) in domain
    # No is_reached filter: reached milestones are needed for the reached/total count.
    assert not any(isinstance(t, tuple) and t[0] == "is_reached" for t in domain)


def test_per_project_derived_health(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_workflows.project_status_report())
    by = {r["project"]: r for r in out["breakdown"]["by_project"]}

    assert by["Alpha"]["derived_health"] == "off_track"      # past end date
    assert by["Alpha"]["divergent"] is True                  # native on_track
    assert by["Alpha"]["milestones"] == {"reached": 0, "total": 0}
    assert by["Alpha"]["next_milestone"] is None
    assert by["Alpha"]["manager"] == "PM One"
    assert by["Alpha"]["customer"] == "Cust A"
    assert by["Alpha"]["end_date"] == "2026-06-01"

    assert by["Bravo"]["derived_health"] == "off_track"      # overdue milestone
    assert by["Bravo"]["overdue_milestones"] == 1
    assert by["Bravo"]["divergent"] is False                 # native to_define
    assert by["Bravo"]["milestones"] == {"reached": 0, "total": 1}
    assert by["Bravo"]["next_milestone"] == {"name": "M2", "deadline": "2026-06-15"}
    assert by["Bravo"]["customer"] is None

    assert by["Charlie"]["derived_health"] == "at_risk"      # milestone due soon
    assert by["Charlie"]["divergent"] is True                # native on_track
    assert by["Charlie"]["milestones"] == {"reached": 0, "total": 1}
    assert by["Charlie"]["next_milestone"] == {"name": "M3", "deadline": "2026-07-05"}

    assert by["Delta"]["derived_health"] == "on_track"
    assert by["Delta"]["divergent"] is False
    assert by["Delta"]["milestones"] == {"reached": 2, "total": 2}
    assert by["Delta"]["next_milestone"] is None


def test_summary_and_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_workflows.project_status_report())
    s = out["summary"]
    assert s["projects"] == 4
    assert s["off_track"] == 2       # Alpha, Bravo
    assert s["at_risk"] == 1         # Charlie
    assert s["on_track"] == 1        # Delta
    assert s["overdue_milestones"] == 1   # Bravo's M2
    assert s["past_end_projects"] == 1    # Alpha
    assert s["divergent"] == 2       # Alpha, Charlie
    assert s["verdict"] == "action_needed"
    codes = {r["code"] for r in out["risks"]}
    assert {"off_track_projects", "overdue_milestones", "past_end_projects",
            "health_divergence"} <= codes


def test_by_project_sort_order(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_workflows.project_status_report())
    order = [r["project"] for r in out["breakdown"]["by_project"]]
    # off_track first, tie broken by overdue_milestones desc (Bravo 1 > Alpha 0),
    # then at_risk (Charlie), then on_track (Delta).
    assert order == ["Bravo", "Alpha", "Charlie", "Delta"]
    assert out["tool"] == "project_status_report"
    assert out["as_of"] == "2026-07-01"


def test_healthy_verdict_when_clean(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    clean_projects = [
        {"id": 1, "name": "Uno", "user_id": [5, "PM One"], "partner_id": [7, "Cust A"],
         "date_start": "2026-01-01", "date": "2026-12-31", "last_update_status": "on_track",
         "task_count": 3},
        {"id": 2, "name": "Dos", "user_id": [5, "PM One"], "partner_id": False,
         "date_start": "2026-01-01", "date": False, "last_update_status": "to_define",
         "task_count": 4},
    ]
    _setup(fake_client, clean_projects, [])
    out = json.loads(tools_workflows.project_status_report())
    assert out["summary"]["verdict"] == "healthy"
    assert out["risks"] == []
    assert out["summary"]["off_track"] == 0
    assert out["summary"]["at_risk"] == 0


def _clean_project(i):
    return {"id": i, "name": f"Proj{i}", "user_id": [5, "PM One"], "partner_id": False,
            "date_start": "2026-01-01", "date": "2026-12-31",
            "last_update_status": "on_track", "task_count": 1}


def test_project_status_report_flags_truncation_on_projects(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    capped_projects = [_clean_project(i) for i in range(200)]
    _setup(fake_client, capped_projects, [])
    fake_client.search_count_responses["project.project"] = 240

    out = json.loads(tools_workflows.project_status_report())

    assert out["summary"]["projects_truncated"] is True
    assert out["summary"]["total_projects_matching"] == 240
    assert "milestones_truncated" not in out["summary"]
    codes = {r["code"]: r for r in out["risks"]}
    assert "truncated_data" in codes
    assert codes["truncated_data"]["count"] == 40
    assert "truncated_milestone_data" not in codes


def test_project_status_report_flags_truncation_on_milestones(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    projects = [
        {"id": 1, "name": "Alpha", "user_id": [5, "PM One"], "partner_id": False,
         "date_start": "2026-01-01", "date": "2026-12-31",
         "last_update_status": "on_track", "task_count": 1},
    ]
    capped_milestones = [
        {"id": 100 + i, "name": f"M{i}", "deadline": "2026-12-01", "is_reached": True,
         "project_id": [1, "Alpha"]}
        for i in range(200)
    ]
    _setup(fake_client, projects, capped_milestones)
    fake_client.search_count_responses["project.milestone"] = 205

    out = json.loads(tools_workflows.project_status_report())

    assert "projects_truncated" not in out["summary"]
    assert out["summary"]["milestones_truncated"] is True
    assert out["summary"]["total_milestones_matching"] == 205
    codes = {r["code"]: r for r in out["risks"]}
    assert "truncated_milestone_data" in codes
    assert codes["truncated_milestone_data"]["count"] == 5
    assert "truncated_data" not in codes


def test_project_status_report_no_truncation_when_under_cap(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)  # default fixtures: 4 projects, 4 milestones
    fake_client.search_count_responses["project.project"] = 999
    fake_client.search_count_responses["project.milestone"] = 999

    out = json.loads(tools_workflows.project_status_report())

    assert "projects_truncated" not in out["summary"]
    assert "milestones_truncated" not in out["summary"]
    assert all(
        r["code"] not in ("truncated_data", "truncated_milestone_data")
        for r in out["risks"]
    )
    assert all(c["method"] != "search_count" for c in fake_client.calls)


def test_watch_verdict_when_only_at_risk(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    watch_projects = [
        {"id": 1, "name": "Uno", "user_id": [5, "PM One"], "partner_id": False,
         "date_start": "2026-01-01", "date": False, "last_update_status": "to_define",
         "task_count": 3},
    ]
    watch_milestones = [
        {"id": 10, "name": "M1", "deadline": "2026-07-04", "is_reached": False,
         "project_id": [1, "Uno"]},   # due soon -> at_risk; native to_define -> not divergent
    ]
    _setup(fake_client, watch_projects, watch_milestones)
    out = json.loads(tools_workflows.project_status_report())
    assert out["summary"]["verdict"] == "watch"
    assert out["summary"]["at_risk"] == 1
    assert out["summary"]["divergent"] == 0

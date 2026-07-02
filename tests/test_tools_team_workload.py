# tests/test_tools_team_workload.py
import datetime as dt
import json

from odoo_mcp import tools_workflows


# today is fixed at 2026-06-30 (cutoff 2026-07-07 with default lookahead 7).
TASKS = [
    {"id": 1, "name": "A", "user_ids": [10], "stage_id": [2, "In Progress"],
     "date_deadline": "2026-06-25", "priority": "1", "parent_id": [99, "P"]},   # Alice overdue, high
    {"id": 2, "name": "B", "user_ids": [10], "stage_id": [3, "To Do"],
     "date_deadline": "2026-07-03", "priority": "0", "parent_id": [99, "P"]},   # Alice due_soon
    {"id": 3, "name": "C", "user_ids": [10], "stage_id": [3, "To Do"],
     "date_deadline": "2026-06-30", "priority": "0", "parent_id": [99, "P"]},   # Alice due_soon (today)
    {"id": 4, "name": "D", "user_ids": [11], "stage_id": [1, "Done"],
     "date_deadline": "2026-06-20", "priority": "0", "parent_id": [99, "P"]},   # Bob done -> skipped
    {"id": 5, "name": "E", "user_ids": [11], "stage_id": [2, "In Progress"],
     "date_deadline": False, "priority": "1", "parent_id": [99, "P"]},          # Bob no_deadline, high
    {"id": 6, "name": "F", "user_ids": [], "stage_id": [3, "To Do"],
     "date_deadline": "2026-07-10", "priority": "0", "parent_id": [99, "P"]},   # unassigned, later
    {"id": 7, "name": "G", "user_ids": [12], "stage_id": [2, "In Progress"],
     "date_deadline": "2026-06-28", "priority": "0", "parent_id": [99, "P"]},   # Carol overdue
]


def _setup(fake_client, tasks=TASKS):
    fake_client.search_responses["project.task"] = tasks
    fake_client.execute_kw_responses[("res.users", "search_read")] = [
        {"id": 10, "name": "Alice"},
        {"id": 11, "name": "Bob"},
        {"id": 12, "name": "Carol"},
    ]


def _fix_today(monkeypatch):
    monkeypatch.setattr(tools_workflows, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


def _task_search_call(fake_client):
    return next(
        c for c in fake_client.calls
        if c["method"] == "search_read" and c["model"] == "project.task"
    )


def test_team_workload_builds_domain(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    tools_workflows.team_workload(project="Acme", sprint_id=12)
    call = _task_search_call(fake_client)
    assert ("sprint_id", "=", 12) in call["domain"]
    assert ("parent_id", "!=", False) in call["domain"]
    assert ("project_id.name", "ilike", "Acme") in call["domain"]
    assert ("stage_id.name", "not in", ["Cancelled"]) in call["domain"]


def test_team_workload_per_assignee_load(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_workflows.team_workload(sprint_id=12))
    by = {r["assignee"]: r for r in out["breakdown"]["by_assignee"]}
    assert by["Alice"]["open"] == 3
    assert by["Alice"]["overdue"] == 1
    assert by["Alice"]["due_soon"] == 2
    assert by["Alice"]["high_priority"] == 1
    assert by["Alice"]["status"] == "ok"
    assert by["Bob"]["open"] == 1          # done task 4 excluded
    assert by["Bob"]["no_deadline"] == 1
    assert by["Bob"]["high_priority"] == 1
    assert by["Carol"]["open"] == 1
    assert by["Carol"]["overdue"] == 1
    assert by["(unassigned)"]["open"] == 1
    assert by["(unassigned)"]["status"] == "unassigned"


def test_team_workload_summary(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_workflows.team_workload(sprint_id=12))
    s = out["summary"]
    assert s["members"] == 3             # Alice, Bob, Carol (not unassigned)
    assert s["open_tasks"] == 6          # distinct non-done tasks
    assert s["unassigned"] == 1
    assert s["overloaded_members"] == 0  # default threshold 8
    assert s["busiest"] == "Alice"
    assert s["busiest_open"] == 3
    assert s["avg_open_per_member"] == 1.7
    assert s["verdict"] == "action_needed"   # unassigned > 0


def test_team_workload_overload_threshold_flags_member(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_workflows.team_workload(sprint_id=12, overload_threshold=2))
    by = {r["assignee"]: r for r in out["breakdown"]["by_assignee"]}
    assert by["Alice"]["status"] == "overloaded"   # 3 > 2
    assert out["summary"]["overloaded_members"] == 1
    codes = {r["code"] for r in out["risks"]}
    assert "overloaded_members" in codes
    assert "unassigned_open_tasks" in codes


def test_team_workload_balanced_when_clean(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    clean = [
        {"id": 1, "name": "A", "user_ids": [10], "stage_id": [1, "Done"],
         "date_deadline": "2026-06-20", "priority": "0", "parent_id": [99, "P"]},
        {"id": 2, "name": "B", "user_ids": [11], "stage_id": [3, "To Do"],
         "date_deadline": "2026-07-02", "priority": "0", "parent_id": [99, "P"]},
        {"id": 3, "name": "C", "user_ids": [12], "stage_id": [2, "In Progress"],
         "date_deadline": "2026-07-05", "priority": "0", "parent_id": [99, "P"]},
    ]
    _setup(fake_client, clean)
    out = json.loads(tools_workflows.team_workload(sprint_id=12))
    assert out["summary"]["verdict"] == "balanced"
    assert out["risks"] == []
    assert out["summary"]["members"] == 2     # Bob, Carol (Alice's only task is done)
    assert out["summary"]["unassigned"] == 0
    assert out["tool"] == "team_workload"
    assert out["as_of"] == "2026-06-30"
    assert out["sprint_id"] == 12


def test_team_workload_flags_truncation_when_row_cap_hit(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    capped = [
        {"id": i, "name": f"T{i}", "user_ids": [10], "stage_id": [1, "Done"],
         "date_deadline": "2026-06-20", "priority": "0", "parent_id": [99, "P"]}
        for i in range(200)
    ]
    _setup(fake_client, capped)
    fake_client.search_count_responses["project.task"] = 300

    out = json.loads(tools_workflows.team_workload(sprint_id=12))

    assert out["summary"]["truncated"] is True
    assert out["summary"]["total_matching"] == 300
    codes = {r["code"]: r for r in out["risks"]}
    assert "truncated_data" in codes
    assert codes["truncated_data"]["count"] == 100
    count_calls = [c for c in fake_client.calls if c["method"] == "search_count"]
    assert len(count_calls) == 1


def test_team_workload_no_truncation_when_under_cap(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)  # only 7 tasks
    fake_client.search_count_responses["project.task"] = 999

    out = json.loads(tools_workflows.team_workload(sprint_id=12))

    assert "truncated" not in out["summary"]
    assert all(r["code"] != "truncated_data" for r in out["risks"])
    assert all(c["method"] != "search_count" for c in fake_client.calls)

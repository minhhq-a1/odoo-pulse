# tests/test_tools_sprint_health.py
import datetime as dt
import json

from odoo_pulse import tools_workflows


# today is fixed at 2026-06-30 for every test via monkeypatch.
TASKS = [
    {"id": 1, "name": "A", "user_ids": [10], "stage_id": [1, "Done"],
     "date_deadline": "2026-06-20", "priority": "0", "parent_id": [99, "P"]},
    {"id": 2, "name": "B", "user_ids": [11], "stage_id": [2, "In Progress"],
     "date_deadline": "2026-06-25", "priority": "1", "parent_id": [99, "P"]},
    {"id": 3, "name": "C", "user_ids": [], "stage_id": [2, "In Progress"],
     "date_deadline": False, "priority": "0", "parent_id": [99, "P"]},
    {"id": 4, "name": "D", "user_ids": [10, 11], "stage_id": [3, "To Do"],
     "date_deadline": "2026-06-30", "priority": "0", "parent_id": [99, "P"]},
    {"id": 5, "name": "E", "user_ids": [12], "stage_id": [3, "To Do"],
     "date_deadline": "2026-07-05", "priority": "0", "parent_id": [99, "P"]},
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


def test_sprint_health_builds_domain(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    tools_workflows.sprint_health(12, project="Acme")
    call = _task_search_call(fake_client)
    assert ("sprint_id", "=", 12) in call["domain"]
    assert ("parent_id", "!=", False) in call["domain"]
    assert ("project_id.name", "ilike", "Acme") in call["domain"]
    assert ("stage_id.name", "not in", ["Cancelled"]) in call["domain"]


def test_sprint_health_summary_counts(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_workflows.sprint_health(12))
    s = out["summary"]
    assert s["total"] == 5
    assert s["done"] == 1
    assert s["open"] == 4
    assert s["pct_done"] == 20.0
    assert s["overdue"] == 1          # task 2 (2026-06-25)
    assert s["due_today"] == 1        # task 4 (2026-06-30)
    assert s["upcoming"] == 1         # task 5 (2026-07-05, within +7)
    assert s["no_deadline"] == 1      # task 3
    assert s["unassigned"] == 1       # task 3
    assert s["over_assigned"] == 1    # task 4 has 2 assignees
    assert s["verdict"] == "off_track"  # overdue > 0


def test_sprint_health_breakdown(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_workflows.sprint_health(12))
    by_stage = {r["stage"]: r["count"] for r in out["breakdown"]["by_stage"]}
    assert by_stage == {"Done": 1, "In Progress": 2, "To Do": 2}
    by_assignee = {r["assignee"]: r["open"] for r in out["breakdown"]["by_assignee"]}
    assert by_assignee == {"Bob": 2, "Alice": 1, "Carol": 1, "(unassigned)": 1}


def test_sprint_health_risks_present(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_workflows.sprint_health(12))
    codes = {r["code"] for r in out["risks"]}
    assert codes == {
        "overdue_open_tasks",
        "open_tasks_without_deadline",
        "unassigned_open_tasks",
        "multiple_assignees",
    }


def test_sprint_health_on_track_when_clean(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    clean = [
        {"id": 1, "name": "A", "user_ids": [10], "stage_id": [1, "Done"],
         "date_deadline": "2026-06-20", "priority": "0", "parent_id": [99, "P"]},
        {"id": 2, "name": "B", "user_ids": [11], "stage_id": [3, "To Do"],
         "date_deadline": "2026-07-02", "priority": "0", "parent_id": [99, "P"]},
    ]
    _setup(fake_client, clean)
    out = json.loads(tools_workflows.sprint_health(12))
    assert out["summary"]["verdict"] == "on_track"
    assert out["risks"] == []
    assert out["tool"] == "sprint_health"
    assert out["as_of"] == "2026-06-30"
    assert out["sprint_id"] == 12


def _clean_task(i):
    return {"id": i, "name": f"T{i}", "user_ids": [10], "stage_id": [1, "Done"],
            "date_deadline": "2026-06-20", "priority": "0", "parent_id": [99, "P"]}


def test_sprint_health_flags_truncation_when_row_cap_hit(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    # Exactly 200 rows: the row count that search_read (capped at
    # config.max_records=200) hits, so the tool should notice more rows
    # exist server-side and issue a search_count to confirm.
    capped = [_clean_task(i) for i in range(200)]
    _setup(fake_client, capped)
    fake_client.search_count_responses["project.task"] = 250

    out = json.loads(tools_workflows.sprint_health(12))

    assert out["summary"]["truncated"] is True
    assert out["summary"]["total_matching"] == 250
    codes = {r["code"]: r for r in out["risks"]}
    assert "truncated_data" in codes
    assert codes["truncated_data"]["count"] == 50

    count_calls = [c for c in fake_client.calls if c["method"] == "search_count"]
    assert len(count_calls) == 1
    assert count_calls[0]["model"] == "project.task"


def test_sprint_health_no_truncation_when_under_cap(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)  # only 5 tasks, well under the 200 cap
    fake_client.search_count_responses["project.task"] = 999  # would be wrong if used

    out = json.loads(tools_workflows.sprint_health(12))

    assert "truncated" not in out["summary"]
    assert "total_matching" not in out["summary"]
    assert all(r["code"] != "truncated_data" for r in out["risks"])
    assert all(c["method"] != "search_count" for c in fake_client.calls)


def test_sprint_health_no_truncation_when_count_matches_fetched(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    capped = [_clean_task(i) for i in range(200)]
    _setup(fake_client, capped)
    fake_client.search_count_responses["project.task"] = 200  # exactly what we fetched

    out = json.loads(tools_workflows.sprint_health(12))

    assert "truncated" not in out["summary"]
    assert all(r["code"] != "truncated_data" for r in out["risks"])


def test_sprint_health_friendly_error_without_sprint_field(fake_client):
    fake_client.fields_responses["project.task"] = {"name": {"type": "char"}}
    out = json.loads(tools_workflows.sprint_health(sprint_id=5))
    assert "sprint_id" in out["error"]
    assert "custom" in out["error"]

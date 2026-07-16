# tests/test_tools_project_detail.py
import json

from odoo_pulse import tools_project_detail
from odoo_pulse.tools_project_detail import project_subtask_hours

_TASK_SCHEMA = {
    "name": {"type": "char"}, "user_ids": {"type": "many2many"},
    "date_end": {"type": "datetime"}, "delivery_hours": {"type": "float"},
    "allocated_hours": {"type": "float"}, "effective_hours": {"type": "float"},
}


def _seed_tasks(fake, schema=None):
    fake.fields_responses["project.task"] = schema or dict(_TASK_SCHEMA)
    fake.search_responses["project.task"] = [
        {"id": 1, "user_ids": [11], "date_end": "2025-10-05 10:00:00",
         "delivery_hours": 10.0, "allocated_hours": 8.0,
         "effective_hours": 9.5},
        {"id": 2, "user_ids": [11, 12], "date_end": "2025-10-20 10:00:00",
         "delivery_hours": 5.0, "allocated_hours": 4.0,
         "effective_hours": 4.5},
        {"id": 3, "user_ids": [], "date_end": False,
         "delivery_hours": 2.0, "allocated_hours": 1.0,
         "effective_hours": 1.5},
    ]


def test_subtask_hours_envelope_and_totals(fake_client):
    _seed_tasks(fake_client)
    out = json.loads(project_subtask_hours(project_id=59))
    assert out["tool"] == "project_subtask_hours"
    assert out["project_id"] == 59
    assert "as_of" in out
    assert out["totals"] == {"task_count": 3, "delivery_hours": 17.0,
                             "allocated_hours": 13.0,
                             "effective_hours": 15.5}
    assert "by_month" not in out          # group_by_month off
    assert "warnings" not in out          # all fields present
    assert out["filters"]["single_assignee_only"] is False


def test_subtask_hours_single_call_no_client_side_paging(fake_client):
    _seed_tasks(fake_client)
    json.loads(project_subtask_hours(
        project_id=59, only_closed_stages=True,
        single_assignee_only=True))
    reads = [c for c in fake_client.calls if c["method"] == "search_read"
             and c["model"] == "project.task"]
    assert len(reads) == 1  # everything in one server-side fetch


def test_subtask_hours_group_by_month(fake_client):
    _seed_tasks(fake_client)
    out = json.loads(project_subtask_hours(project_id=59,
                                           group_by_month=True))
    assert [r["month"] for r in out["by_month"]] == ["2025-10"]
    assert out["no_date_end"]["task_count"] == 1
    assert out["no_date_end"]["delivery_hours"] == 2.0


def test_subtask_hours_missing_delivery_field_warns(fake_client):
    schema = dict(_TASK_SCHEMA)
    del schema["delivery_hours"]
    _seed_tasks(fake_client, schema=schema)
    out = json.loads(project_subtask_hours(project_id=59))
    assert out["totals"]["delivery_hours"] is None
    assert out["warnings"] == \
        ["field delivery_hours does not exist on project.task"]


def test_subtask_hours_bad_period_is_clean_error(fake_client):
    _seed_tasks(fake_client)
    out = json.loads(project_subtask_hours(
        project_id=59, periods=[{"date_from": "garbage"}]))
    assert "error" in out
    assert "date_from" in out["error"]


def test_module_registered_in_reports_group():
    from odoo_pulse.tool_groups import GROUP_MODULES
    assert "tools_project_detail" in GROUP_MODULES["reports"]


from odoo_pulse.tools_project_detail import (
    _core_section,
    _hours_section,
    _weekly_logged,
)

_PROJECT_SCHEMA = {
    "name": {"type": "char"}, "user_id": {"type": "many2one"},
    "partner_id": {"type": "many2one"}, "date": {"type": "date"},
    "task_count": {"type": "integer"},
    "last_update_status": {"type": "selection"},
    "delivery_hours": {"type": "float"},
    "account_id": {"type": "many2one"},
}

_MILESTONE_SCHEMA = {
    "name": {"type": "char"}, "deadline": {"type": "date"},
    "is_reached": {"type": "boolean"},
}


def _seed_core(fake):
    fake.fields_responses["project.project"] = dict(_PROJECT_SCHEMA)
    fake.fields_responses["project.milestone"] = dict(_MILESTONE_SCHEMA)
    fake.search_responses["project.project"] = [
        {"id": 59, "name": "The Body Shop", "user_id": [7, "Minh"],
         "partner_id": False, "date": "2026-07-31", "task_count": 744,
         "last_update_status": "off_track", "delivery_hours": 1500.0,
         "account_id": [5, "AA TBS"]},
    ]
    fake.search_responses["project.milestone"] = [
        {"id": 1, "name": "1.2 Go-live", "deadline": "2026-01-16",
         "is_reached": False},
        {"id": 2, "name": "Kickoff", "deadline": "2025-04-01",
         "is_reached": True},
    ]
    fake.aggregate_responses_seq["account.analytic.line"] = [
        [{"account_id": [5, "AA TBS"], "amount:sum": -1000.0}],  # cost
        [{"account_id": [5, "AA TBS"], "amount:sum": 200.0}],    # revenue
    ]
    fake.search_responses["account.analytic.line"] = [
        {"id": 900, "date": "2026-07-13", "unit_amount": 4.0},
        {"id": 901, "date": "2026-07-14", "unit_amount": 3.5},
        {"id": 902, "date": "2026-07-06", "unit_amount": 8.0},
    ]


def test_core_section_shape(fake_client):
    _seed_core(fake_client)
    core = _core_section(fake_client, 59, 7, 7)
    p = core["project"]
    assert p["id"] == 59 and p["name"] == "The Body Shop"
    assert p["manager"] == "Minh" and p["customer"] is None
    assert p["end_date"] == "2026-07-31" and p["task_count"] == 744
    assert p["native_status"] == "off_track"
    assert p["derived_health"] == "off_track"   # overdue Go-live
    assert p["divergent"] is False
    assert p["delivery_hours"] == 1500.0
    ms = core["milestones"]
    assert ms["reached"] == 1 and ms["total"] == 2 and ms["overdue"] == 1
    assert ms["next_unreached"]["name"] == "1.2 Go-live"
    assert len(ms["list"]) == 2
    fin = core["finance"]
    assert fin == {"revenue": 200.0, "cost_all_time": 1000.0,
                   "margin": -800.0}
    assert core["warnings"] == []


def test_core_section_missing_project_raises(fake_client):
    fake_client.fields_responses["project.project"] = dict(_PROJECT_SCHEMA)
    fake_client.search_responses["project.project"] = []
    import pytest
    from odoo_pulse.odoo_client import OdooError
    with pytest.raises(OdooError, match="No project.project with id 999"):
        _core_section(fake_client, 999, 7, 7)


def test_core_section_missing_delivery_hours_warns(fake_client):
    _seed_core(fake_client)
    schema = dict(_PROJECT_SCHEMA)
    del schema["delivery_hours"]
    fake_client.fields_responses["project.project"] = schema
    core = _core_section(fake_client, 59, 7, 7)
    assert core["project"]["delivery_hours"] is None
    assert core["warnings"] == \
        ["field delivery_hours does not exist on project.project"]


def test_weekly_logged_iso_monday_buckets(fake_client):
    import datetime as dt
    fake_client.search_responses["account.analytic.line"] = [
        {"id": 1, "date": "2026-07-13", "unit_amount": 4.0},   # Mon
        {"id": 2, "date": "2026-07-14", "unit_amount": 3.5},   # Tue same wk
        {"id": 3, "date": "2026-07-06", "unit_amount": 8.0},   # prev week
    ]
    weeks = _weekly_logged(fake_client, 59, dt.date(2026, 7, 15))
    assert weeks == [
        {"week_start": "2026-07-06", "hours": 8.0},
        {"week_start": "2026-07-13", "hours": 7.5},
    ]
    call = fake_client.last("search_read")
    assert ("date", ">=", "2026-04-22") in call["domain"]   # today - 84d


def test_hours_section_totals_and_leaderboards(fake_client):
    fake_client.fields_responses["project.task"] = {
        "user_ids": {"type": "many2many"}, "date_end": {"type": "datetime"},
        "delivery_hours": {"type": "float"},
        "allocated_hours": {"type": "float"},
        "effective_hours": {"type": "float"},
    }
    fake_client.search_responses["project.task"] = [
        {"id": 1, "user_ids": [11], "date_end": False,
         "delivery_hours": 10.0, "allocated_hours": 8.0,
         "effective_hours": 9.0},
    ]
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"employee_id": [155, "Nguyễn Văn A"], "unit_amount:sum": 320.5}],
        [{"task_id": [8554, "Build X"], "unit_amount:sum": 84.0}],
    ]
    out = _hours_section(fake_client, 59, False, None, False, 7)
    h = out["hours"]
    assert h["subtask_delivery"] == 10.0
    assert h["by_employee"] == [{"employee_id": 155,
                                 "employee": "Nguyễn Văn A",
                                 "hours": 320.5}]
    assert h["by_task"] == [{"task_id": 8554, "task": "Build X",
                             "hours": 84.0}]

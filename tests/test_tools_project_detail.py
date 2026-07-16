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

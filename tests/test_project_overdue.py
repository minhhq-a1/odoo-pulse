import datetime as dt

from odoo_pulse.services.projects.subtasks import (
    overdue_project_subtask_count,
    overdue_subtask_count_by_project,
)
from odoo_pulse.services.report_context import ReportContext


def context(fake_client):
    return ReportContext(fake_client, dt.date(2026, 6, 30), 7, None)


def test_overdue_project_subtask_count_filters_by_project_name(fake_client):
    fake_client.search_count_responses["project.task"] = 2
    count = overdue_project_subtask_count(context(fake_client), project_name="Alpha")
    assert count == 2
    call = fake_client.last("search_count")
    assert ("project_id.name", "=", "Alpha") in call["domain"]
    assert ("parent_id", "!=", False) in call["domain"]
    assert ("date_deadline", "<", "2026-06-30") in call["domain"]


def test_overdue_subtask_count_by_project_groups_by_project_name(fake_client):
    fake_client.search_responses["project.task"] = [
        {"id": 1, "project_id": [1, "Alpha"], "date_deadline": "2026-06-20"},
        {"id": 2, "project_id": [2, "Beta"], "date_deadline": "2026-06-25"},
    ]
    counts = overdue_subtask_count_by_project(
        context(fake_client), project_names=["Alpha", "Beta"]
    )
    assert counts == {"Alpha": 1, "Beta": 1}
    call = fake_client.last("search_read")
    assert ("project_id.name", "in", ["Alpha", "Beta"]) in call["domain"]

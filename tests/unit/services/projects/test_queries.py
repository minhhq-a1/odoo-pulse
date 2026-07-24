import pytest

from odoo_pulse.core.errors import OdooError
from odoo_pulse.services.projects.queries import build_task_list, build_timesheet_list


def test_build_task_list_resolves_user_names(fake_client):
    fake_client.search_responses["project.task"] = [
        {"id": 1, "name": "Task 1", "user_ids": [10]}
    ]
    fake_client.execute_kw_responses[("res.users", "search_read")] = [
        {"id": 10, "name": "Alice"}
    ]
    tasks = build_task_list(fake_client, query="Task 1")
    assert tasks[0]["user_ids"] == [{"id": 10, "name": "Alice"}]


def test_build_timesheet_list_verifies_schema_field(fake_client):
    fake_client.fields_responses["account.analytic.line"] = {}
    with pytest.raises(OdooError, match="hr_timesheet"):
        build_timesheet_list(fake_client)

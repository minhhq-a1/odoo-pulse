import datetime as dt

import pytest

from odoo_pulse.core.errors import OdooError
from odoo_pulse.services.projects.metrics import overdue_open_tasks
from odoo_pulse.services.report_context import ReportContext


def context(fake_client, field_type="date", company_id=None):
    fake_client.fields_responses["project.task"] = {
        "date_deadline": {"type": field_type}
    }
    return ReportContext(fake_client, dt.date(2026, 6, 30), 7, company_id)


def test_overdue_tasks_uses_plain_bound_for_date_field(fake_client):
    fake_client.search_count_responses["project.task"] = 2
    assert overdue_open_tasks(
        context(fake_client, "date", 5), overdue_before=dt.date(2026, 6, 30)
    ) == {"overdue_tasks": 2}
    assert fake_client.last("search_count")["domain"] == [
        ("date_deadline", "<", "2026-06-30"),
        ("stage_id.fold", "=", False),
        ("company_id", "=", 5),
    ]


def test_overdue_tasks_uses_local_midnight_for_datetime(fake_client):
    overdue_open_tasks(
        context(fake_client, "datetime"), overdue_before=dt.date(2026, 6, 30)
    )
    assert ("date_deadline", "<", "2026-06-29 17:00:00") in (
        fake_client.last("search_count")["domain"]
    )


def test_overdue_tasks_requires_deadline_field(fake_client):
    fake_client.fields_responses["project.task"] = {}
    ctx = ReportContext(fake_client, dt.date(2026, 6, 30), 7, None)
    with pytest.raises(OdooError, match="date_deadline"):
        overdue_open_tasks(ctx, overdue_before=dt.date(2026, 6, 30))

import datetime as dt

from odoo_pulse.services.hr.metrics import (
    approved_leave_domain,
    distinct_employee_count,
    employees_off,
)
from odoo_pulse.services.report_context import ReportContext


def context(fake_client, company_id=None):
    return ReportContext(fake_client, dt.date(2026, 6, 30), 7, company_id)


def test_approved_leave_domain_is_overlap_and_company_scoped(fake_client):
    assert approved_leave_domain(
        context(fake_client, 5),
        starts_before="2026-06-30 17:00:00",
        ends_at_or_after="2026-06-29 17:00:00",
    ) == [
        ("state", "=", "validate"),
        ("date_from", "<", "2026-06-30 17:00:00"),
        ("date_to", ">=", "2026-06-29 17:00:00"),
        ("company_id", "=", 5),
    ]


def test_distinct_employee_count_ignores_empty_and_duplicates():
    assert distinct_employee_count([
        {"employee_id": [10, "Alice"]},
        {"employee_id": [10, "Alice"]},
        {"employee_id": [11, "Bob"]},
        {"employee_id": False},
    ]) == 2


def test_employees_off_pages_and_returns_distinct_count(fake_client):
    fake_client.search_responses["hr.leave"] = [
        {"employee_id": [10, "Alice"]},
        {"employee_id": [10, "Alice"]},
    ]
    assert employees_off(
        context(fake_client), starts_before="b", ends_at_or_after="a"
    ) == {"off_today": 1}
    call = fake_client.last("search_read")
    assert call["model"] == "hr.leave"
    assert call["fields"] == ["employee_id"]

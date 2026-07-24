import datetime as dt

from odoo_pulse.services.crm.metrics import new_leads
from odoo_pulse.services.report_context import ReportContext


def context(fake_client, company_id=None):
    return ReportContext(fake_client, dt.date(2026, 6, 30), 7, company_id)


def test_new_leads_uses_half_open_window_and_company(fake_client):
    fake_client.search_count_responses["crm.lead"] = 4
    assert new_leads(
        context(fake_client, 5),
        date_from="2026-06-28 17:00:00",
        date_to_exclusive="2026-06-29 17:00:00",
    ) == {"new_leads": 4}
    assert fake_client.last("search_count")["domain"] == [
        ("create_date", ">=", "2026-06-28 17:00:00"),
        ("create_date", "<", "2026-06-29 17:00:00"),
        ("company_id", "=", 5),
    ]


def test_new_leads_without_company_has_no_company_leaf(fake_client):
    new_leads(
        context(fake_client),
        date_from="2026-06-28 17:00:00",
        date_to_exclusive="2026-06-29 17:00:00",
    )
    assert all(
        leaf[0] != "company_id"
        for leaf in fake_client.last("search_count")["domain"]
    )

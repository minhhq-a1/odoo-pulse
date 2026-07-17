import json

import pytest

from odoo_pulse import (
    domain_tools,
    tools_engagement,
    tools_hr,
    tools_operations,
    tools_projects,
)


@pytest.mark.parametrize(
    "func,model,field",
    [
        (domain_tools.list_sale_orders, "sale.order", "date_order"),
        (tools_operations.list_pos_orders, "pos.order", "date_order"),
        (tools_engagement.list_events, "event.event", "date_begin"),
        (tools_engagement.list_calendar_events, "calendar.event", "start"),
        (tools_hr.list_time_off, "hr.leave", "date_from"),
        (tools_hr.list_attendances, "hr.attendance", "check_in"),
    ],
)
def test_datetime_wrappers_include_the_complete_last_day(
    fake_client, func, model, field
):
    json.loads(func(date_from="2026-01-01", date_to="2026-06-30"))
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == model)
    assert (field, ">=", "2026-01-01") in call["domain"]
    assert (field, "<", "2026-07-01") in call["domain"]
    assert (field, "<=", "2026-06-30") not in call["domain"]


@pytest.mark.parametrize(
    "func,model,field",
    [
        (domain_tools.list_invoices, "account.move", "invoice_date"),
        (domain_tools.list_payments, "account.payment", "date"),
        (tools_projects.list_timesheets, "account.analytic.line", "date"),
    ],
)
def test_date_wrappers_keep_inclusive_last_day(fake_client, func, model, field):
    json.loads(func(date_from="2026-01-01", date_to="2026-06-30"))
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == model)
    assert (field, "<=", "2026-06-30") in call["domain"]


def test_invalid_wrapper_date_is_a_json_error(fake_client):
    out = json.loads(domain_tools.list_sale_orders(date_to="not-a-date"))
    assert "date_to" in out["error"]


def test_purchase_order_wrapper_does_not_gain_a_date_filter(fake_client):
    json.loads(domain_tools.list_purchase_orders())
    call = fake_client.last("search_read")
    assert all(leaf[0] != "date_order" for leaf in call["domain"]
               if isinstance(leaf, tuple))

import datetime as dt

from odoo_pulse.services.report_context import ReportContext
from odoo_pulse.services.sales.metrics import confirmed_sales


def context(fake_client, company_id=None):
    return ReportContext(fake_client, dt.date(2026, 6, 30), 7, company_id)


def test_confirmed_sales_domain_count_and_single_currency(fake_client):
    fake_client.aggregate_responses_seq["sale.order"] = [[{
        "currency_id": [1, "USD"], "amount_total:sum": 150.0, "__count": 2,
    }]]
    result = confirmed_sales(
        context(fake_client, 5),
        date_from="2026-06-01 00:00:00",
        date_to_exclusive="2026-07-01 00:00:00",
        group_limit=200,
    )
    assert result == {"orders": 2, "revenue": 150.0, "currency": "USD"}
    call = fake_client.last("aggregate_records")
    assert call["limit"] == 200
    assert call["domain"] == [
        ("state", "in", ["sale", "done"]),
        ("date_order", ">=", "2026-06-01 00:00:00"),
        ("date_order", "<", "2026-07-01 00:00:00"),
        ("company_id", "=", 5),
    ]


def test_confirmed_sales_preserves_uncapped_mixed_currency_payload(fake_client):
    fake_client.aggregate_responses_seq["sale.order"] = [[
        {"currency_id": [1, "USD"], "amount_total:sum": 100.0, "__count": 1},
        {"currency_id": [2, "VND"], "amount_total:sum": 2_500_000.0,
         "__count": 250},
    ]]
    result = confirmed_sales(
        context(fake_client), date_from="a", date_to_exclusive="b"
    )
    assert result == {
        "orders": 251,
        "revenue": 2_500_100.0,
        "by_currency": {"USD": 100.0, "VND": 2_500_000.0},
        "mixed_currencies": True,
        "totals_comparable": False,
    }
    assert fake_client.last("aggregate_records")["limit"] is None


def test_confirmed_sales_empty_aggregate(fake_client):
    fake_client.aggregate_responses_seq["sale.order"] = [[]]
    assert confirmed_sales(
        context(fake_client), date_from="a", date_to_exclusive="b"
    ) == {"orders": 0, "revenue": 0.0}

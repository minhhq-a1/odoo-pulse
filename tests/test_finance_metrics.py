import datetime as dt

from odoo_pulse.services.finance.metrics import (
    open_move_domain,
    overdue_receivables,
)
from odoo_pulse.services.report_context import ReportContext


def test_open_move_domain_is_explicit_and_company_scoped(fake_client):
    ctx = ReportContext(fake_client, dt.date(2026, 6, 30), 7, 5)
    assert open_move_domain(
        ctx, move_types=("out_invoice", "in_invoice")
    ) == [
        ("move_type", "in", ["out_invoice", "in_invoice"]),
        ("state", "=", "posted"),
        ("payment_state", "in", ["not_paid", "partial"]),
        ("company_id", "=", 5),
    ]


def test_overdue_receivables_uses_exclusive_due_bound(fake_client):
    fake_client.aggregate_responses_seq["account.move"] = [[{
        "currency_id": [1, "USD"], "amount_residual:sum": 700.0,
        "__count": 3,
    }]]
    ctx = ReportContext(fake_client, dt.date(2026, 6, 30), 7, None)
    assert overdue_receivables(ctx, overdue_before="2026-06-30") == {
        "overdue_invoices": 3, "overdue_amount": 700.0, "currency": "USD",
    }
    domain = fake_client.last("aggregate_records")["domain"]
    assert ("move_type", "=", "out_invoice") in domain
    assert ("invoice_date_due", "<", "2026-06-30") in domain


def test_overdue_receivables_mixed_currency_is_not_comparable(fake_client):
    fake_client.aggregate_responses_seq["account.move"] = [[
        {"currency_id": [1, "USD"], "amount_residual:sum": 1.0, "__count": 1},
        {"currency_id": [2, "VND"], "amount_residual:sum": 2.0, "__count": 1},
    ]]
    ctx = ReportContext(fake_client, dt.date(2026, 6, 30), 7, None)
    result = overdue_receivables(ctx, overdue_before="2026-06-30")
    assert result["by_currency"] == {"USD": 1.0, "VND": 2.0}
    assert result["mixed_currencies"] is True
    assert result["totals_comparable"] is False

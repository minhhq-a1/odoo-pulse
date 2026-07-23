"""Narrow finance metrics shared by cross-domain reports."""

from __future__ import annotations

from ...common.money import aggregate_currency_totals
from ..report_context import ReportContext


def open_move_domain(
    context: ReportContext,
    *,
    move_types: tuple[str, ...],
    overdue_before: str | None = None,
) -> list:
    move_type_leaf = (
        ("move_type", "=", move_types[0])
        if len(move_types) == 1
        else ("move_type", "in", list(move_types))
    )
    domain = [
        move_type_leaf,
        ("state", "=", "posted"),
        ("payment_state", "in", ["not_paid", "partial"]),
    ]
    if overdue_before is not None:
        domain.append(("invoice_date_due", "<", overdue_before))
    domain.extend(context.company_domain)
    return domain


def overdue_receivables(
    context: ReportContext, *, overdue_before: str,
) -> dict:
    aggregate = context.client.aggregate_records(
        "account.move",
        group_by=["currency_id"],
        measures=[("amount_residual", "sum")],
        domain=open_move_domain(
            context, move_types=("out_invoice",),
            overdue_before=overdue_before,
        ),
    )
    count, total, by_currency = aggregate_currency_totals(
        aggregate.get("rows", []), "amount_residual"
    )
    payload = {"overdue_invoices": count, "overdue_amount": total}
    if len(by_currency) == 1:
        payload["currency"] = next(iter(by_currency))
    elif len(by_currency) > 1:
        payload["by_currency"] = by_currency
        payload["mixed_currencies"] = True
        payload["totals_comparable"] = False
    return payload

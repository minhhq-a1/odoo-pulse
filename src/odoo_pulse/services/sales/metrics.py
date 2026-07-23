"""Confirmed-order metrics shared by sales snapshot and business pulse."""

from __future__ import annotations

from ...common.money import aggregate_currency_totals
from ..report_context import ReportContext


def confirmed_sales(
    context: ReportContext,
    *,
    date_from: str,
    date_to_exclusive: str,
    group_limit: int | None = None,
) -> dict:
    aggregate = context.client.aggregate_records(
        "sale.order",
        group_by=["currency_id"],
        measures=[("amount_total", "sum")],
        domain=[
            ("state", "in", ["sale", "done"]),
            ("date_order", ">=", date_from),
            ("date_order", "<", date_to_exclusive),
            *context.company_domain,
        ],
        limit=group_limit,
    )
    count, total, by_currency = aggregate_currency_totals(
        aggregate.get("rows", []), "amount_total"
    )
    payload = {"orders": count, "revenue": total}
    if len(by_currency) == 1:
        payload["currency"] = next(iter(by_currency))
    elif len(by_currency) > 1:
        payload["by_currency"] = by_currency
        payload["mixed_currencies"] = True
        payload["totals_comparable"] = False
    return payload

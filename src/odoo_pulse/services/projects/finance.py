"""Canonical analytic cost/revenue classification for project services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ...common.schema import optional_fields

AnalyticClassification = Literal[
    "odoo_profitability", "sign_fallback", "not_evaluated"
]
AnalyticBucket = Literal["cost", "revenue"]

FALLBACK_WARNING = (
    "account.analytic.line.analytic_profitability is unavailable; "
    "cost/revenue use amount-sign fallback"
)


@dataclass(frozen=True)
class AnalyticMoneyResult:
    cost_by_account: dict[int, float]
    revenue_by_account: dict[int, float]
    classification: AnalyticClassification


def analytic_classification(client) -> AnalyticClassification:
    fields = optional_fields(
        client, "account.analytic.line", ["analytic_profitability"]
    )
    return "odoo_profitability" if fields else "sign_fallback"


def analytic_bucket(
    row: dict, classification: AnalyticClassification
) -> AnalyticBucket | None:
    if classification == "odoo_profitability":
        value = row.get("analytic_profitability")
        if value == "loss":
            return "cost"
        if value == "revenue":
            return "revenue"
        return None
    if classification == "sign_fallback":
        amount = row.get("amount") or 0.0
        if amount < 0:
            return "cost"
        if amount > 0:
            return "revenue"
    return None


def analytic_money(
    client, account_ids: list[int], extra_domain: list | None = None
) -> AnalyticMoneyResult:
    if not account_ids:
        return AnalyticMoneyResult({}, {}, "not_evaluated")

    classification = analytic_classification(client)
    extra = list(extra_domain or [])
    if classification == "odoo_profitability":
        buckets = (
            ("cost", ("analytic_profitability", "=", "loss")),
            ("revenue", ("analytic_profitability", "=", "revenue")),
        )
    else:
        buckets = (
            ("cost", ("amount", "<", 0)),
            ("revenue", ("amount", ">", 0)),
        )

    values: dict[str, dict[int, float]] = {"cost": {}, "revenue": {}}
    for bucket, classifier_domain in buckets:
        aggregate = client.aggregate_records(
            "account.analytic.line",
            group_by=["account_id"],
            measures=[("amount", "sum")],
            domain=[
                ("account_id", "in", account_ids),
                classifier_domain,
                *extra,
            ],
        )
        target = values[bucket]
        for row in aggregate.get("rows", []):
            account = row.get("account_id")
            if not account:
                continue
            amount = row.get("amount:sum") or 0.0
            normalized = -amount if bucket == "cost" else amount
            target[account[0]] = target.get(account[0], 0.0) + normalized

    return AnalyticMoneyResult(
        values["cost"], values["revenue"], classification
    )

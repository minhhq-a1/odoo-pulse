# odoo_pulse/common/money.py
"""Money-shaping primitives shared by report and workflow tools."""

from __future__ import annotations


def totals_by_currency(
    rows: list[dict], amount_field: str, currency_field: str = "currency_id"
) -> dict[str, float]:
    """Sum amount_field per currency name. Falsy currency -> '(unknown)'."""
    totals: dict[str, float] = {}
    for row in rows:
        cur = row.get(currency_field)
        name = cur[1] if cur else "(unknown)"
        totals[name] = totals.get(name, 0.0) + (row.get(amount_field) or 0.0)
    return {name: round(value, 2) for name, value in totals.items()}


def aggregate_currency_totals(
    rows: list[dict], amount_field: str,
) -> tuple[int, float, dict[str, float]]:
    """Count aggregate rows and sum a spec-keyed amount by currency name."""
    count = 0
    total = 0.0
    by_currency: dict[str, float] = {}
    key = f"{amount_field}:sum"
    for row in rows:
        currency = row.get("currency_id")
        name = currency[1] if currency else "(unknown)"
        amount = row.get(key) or 0.0
        count += row.get("__count") or 0
        total += amount
        by_currency[name] = by_currency.get(name, 0.0) + amount
    return count, round(total, 2), {
        name: round(value, 2) for name, value in by_currency.items()
    }


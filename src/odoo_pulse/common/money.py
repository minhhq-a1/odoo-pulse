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

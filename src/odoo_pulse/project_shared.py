# odoo_pulse/project_shared.py
"""Shared, non-tool helpers for the project-status tool family.

Everything here is read-only and client-agnostic (real OdooClient or the
test FakeClient). Budget primitives live in
services/projects/budget.py (single source of truth for planned/practical
figures — spec rule #7); this module now holds analytic_money only.
"""

from __future__ import annotations


def analytic_money(
    client, account_ids: list[int], extra_domain: list | None = None
) -> tuple[dict[int, float], dict[int, float]]:
    """(cost_by_account, revenue_by_account) from account.analytic.line.

    Cost comes back POSITIVE (analytic cost lines are negative in Odoo;
    the sign is flipped here once, so every consumer shows the same
    number). Fixed call order cost-then-revenue: consumers that bundle
    this with other analytic-line calls must keep it inside one thunk.
    """
    if not account_ids:
        return {}, {}
    extra = list(extra_domain or [])
    out: list[dict[int, float]] = []
    for op in ("<", ">"):
        agg = client.aggregate_records(
            "account.analytic.line", group_by=["account_id"],
            measures=[("amount", "sum")],
            domain=[("account_id", "in", account_ids),
                    ("amount", op, 0), *extra])
        acc: dict[int, float] = {}
        for row in agg.get("rows", []):
            m2o = row.get("account_id")
            if m2o:
                acc[m2o[0]] = abs(row.get("amount:sum") or 0.0)
        out.append(acc)
    return out[0], out[1]

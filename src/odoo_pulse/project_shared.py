# odoo_pulse/project_shared.py
"""Shared, non-tool helpers for the project-status tool family.

Everything here is read-only and client-agnostic (real OdooClient or the
test FakeClient). Budget helpers were moved verbatim from
tools_reports_projects so project_dashboard / portfolio_health can reuse
them without importing a tool module (single source of truth for planned/
practical figures — spec rule #7).
"""

from __future__ import annotations

from .common.schema import optional_fields
from .core.errors import OdooError

# (model, analytic-account field candidates, planned-amount field candidates,
#  extra domain). Order below fits Odoo 18+; it is reversed for <= 17.
_BUDGET_CANDIDATES = [
    ("budget.line",
     ["account_id", "analytic_account_id"],
     ["budget_amount", "planned_amount"],
     # != "revenue" keeps expense AND mixed ("both") budgets; a faulting
     # dotted field drops to the next candidate via the aggregate try/except.
     [("budget_analytic_id.budget_type", "!=", "revenue")]),
    ("crossovered.budget.lines",
     ["analytic_account_id"],
     ["planned_amount"],
     # planned_amount <= 0 keeps Expense lines only. Unlike budget.line,
     # this model has no technical revenue/expense field on
     # general_budget_id (account.budget.post only has a translatable
     # name) -- the sign of planned_amount is the reliable signal, same
     # convention as analytic_money's account.analytic.line.amount.
     # Without this, a budget with a Revenue-category line (e.g. a
     # matching "Doanh thu" position) alongside its Expense lines gets
     # summed via abs() over both, silently doubling planned/practical.
     # <= (not <) so a "practical-only" Expense budget -- actuals booked
     # but planned_amount left at 0 -- still surfaces; a strict < 0 hid it
     # entirely, making project_dashboard report its id as "match no
     # budget". Positive Revenue lines stay excluded either way.
     [("crossovered_budget_id.state", "in", ["confirm", "validate", "done"]),
      ("planned_amount", "<=", 0)]),
]

_PRACTICAL_CANDIDATES = ["practical_amount", "achieved_amount"]
# Odoo spells the crossovered-era field "theoritical" in some series.
_THEORETICAL_CANDIDATES = ["theoretical_amount", "theoritical_amount"]

# parent m2o field on a budget line -> the parent budget model it points to
_PARENT_MODEL = {
    "crossovered_budget_id": "crossovered.budget",
    "budget_analytic_id": "budget.analytic",
}
# Derived from _PARENT_MODEL's keys (not hand-duplicated) so a new parent
# field only needs adding in one place.
_PARENT_CANDIDATES = list(_PARENT_MODEL)


def _budget_sources(client, account_ids: list[int]):
    """Yield usable (model, link_field, acct_field, amount_field, extra_domain).

    The FIRST call against each candidate model is a real RPC
    (search_count) inside try/except OdooError — fields_get is NOT a
    reliable absence probe (see the design doc: the FakeClient returns a
    default schema for unknown models, and the degradation path must be
    identical under test and in production). A candidate is usable when an
    amount field resolves AND it can be matched to projects: either the
    line model carries a project_id m2o (custom field seen in the wild) or
    an analytic-account field resolves and there are account ids to match.
    """
    candidates = list(_BUDGET_CANDIDATES)
    major = client.major_version()
    if major is not None and major <= 17:
        candidates.reverse()
    for model, acct_candidates, amount_candidates, extra_domain in candidates:
        try:
            client.search_count(model, [])
        except OdooError:
            continue
        link = (optional_fields(client, model, ["project_id"]) or [None])[0]
        acct = (optional_fields(client, model, acct_candidates) or [None])[0]
        amount = (optional_fields(client, model, amount_candidates)
                  or [None])[0]
        if not amount or not (link or (acct and account_ids)):
            continue
        yield model, link, acct, amount, extra_domain


def _budget_by_project(
    client, project_ids: list[int], acct_by_project: dict[int, int]
) -> tuple[dict[int, float], bool]:
    """Planned budget (absolute) per project id + budgets_available.

    Uses the first usable :func:`_budget_sources` candidate. Line-level
    project_id matching is authoritative per project; analytic-account
    matching (the classic path) fills projects the project aggregate did
    not cover — two projects sharing one account each get the account's
    full amount (accepted double-count caveat). Fixed aggregate order
    (project first, then account) keeps the FakeClient queue deterministic.
    None usable -> ({}, False).
    """
    if not project_ids:
        return {}, False
    account_ids = sorted(set(acct_by_project.values()))
    for model, link, acct, amount, extra_domain in _budget_sources(
            client, account_ids):
        by_project: dict[int, float] = {}
        by_account: dict[int, float] = {}
        try:
            if link:
                agg = client.aggregate_records(
                    model, group_by=[link],
                    measures=[(amount, "sum")],
                    domain=[(link, "in", project_ids), *extra_domain])
                for row in agg.get("rows", []):
                    m2o = row.get(link)
                    if m2o:
                        by_project[m2o[0]] = abs(
                            row.get(f"{amount}:sum") or 0.0)
            if acct and account_ids:
                agg = client.aggregate_records(
                    model, group_by=[acct],
                    measures=[(amount, "sum")],
                    domain=[(acct, "in", account_ids), *extra_domain])
                for row in agg.get("rows", []):
                    m2o = row.get(acct)
                    if m2o:
                        by_account[m2o[0]] = abs(
                            row.get(f"{amount}:sum") or 0.0)
        except OdooError:
            continue
        budgets = {pid: by_account[aid]
                   for pid, aid in acct_by_project.items()
                   if aid in by_account}
        budgets.update(by_project)
        return budgets, True
    return {}, False


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

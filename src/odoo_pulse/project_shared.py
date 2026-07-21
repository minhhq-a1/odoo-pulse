# odoo_pulse/project_shared.py
"""Shared, non-tool helpers for the project-status tool family.

Everything here is read-only and client-agnostic (real OdooClient or the
test FakeClient). Budget helpers were moved verbatim from
tools_reports_projects so project_dashboard / portfolio_health can reuse
them without importing a tool module (single source of truth for planned/
practical figures — spec rule #7).
"""

from __future__ import annotations

from .common.dates import parse_when
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


def derive_project_health(
    project_row: dict,
    milestones: list[dict],
    today,
    cutoff,
    timezone_offset: int,
) -> dict:
    """Milestone/end-date health verdict for one project.

    THE single source of truth for derived health — used by
    project_status_report, project_dashboard and portfolio_health, so the
    artifact's two tabs can never show different verdicts for the same
    project. Rules: any overdue unreached milestone or a passed end date
    -> off_track; anything due within the cutoff -> at_risk; else
    on_track. Divergent means the PM declared a healthier status than the
    data supports.
    """
    native = project_row.get("last_update_status") or "to_define"
    total = len(milestones)
    reached = sum(1 for m in milestones if m.get("is_reached"))
    overdue = soon = 0
    next_milestone = None
    ordered = sorted(milestones,
                     key=lambda m: str(m.get("deadline") or "9999-99-99"))
    for m in ordered:
        if m.get("is_reached"):
            continue
        dd = parse_when(m.get("deadline"), timezone_offset)
        if dd is None:
            continue
        if next_milestone is None:
            next_milestone = {"name": m["name"], "deadline": m["deadline"]}
        if dd < today:
            overdue += 1
        elif dd <= cutoff:
            soon += 1
    end = parse_when(project_row.get("date"), timezone_offset)
    past_end = end is not None and end < today and native != "done"
    end_soon = end is not None and today <= end <= cutoff
    if overdue > 0 or past_end:
        derived = "off_track"
    elif soon > 0 or end_soon:
        derived = "at_risk"
    else:
        derived = "on_track"
    divergent = (
        (native in ("on_track", "on_hold") and derived == "off_track")
        or (native == "on_track" and derived == "at_risk"))
    return {"native_status": native, "derived_health": derived,
            "divergent": divergent, "reached": reached, "total": total,
            "overdue": overdue, "soon": soon,
            "next_milestone": next_milestone,
            "past_end": past_end, "end_soon": end_soon}


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

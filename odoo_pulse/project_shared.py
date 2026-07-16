# odoo_pulse/project_shared.py
"""Shared, non-tool helpers for the project-status tool family.

Everything here is read-only and client-agnostic (real OdooClient or the
test FakeClient). Budget helpers were moved verbatim from
tools_reports_projects so project_dashboard / portfolio_health can reuse
them without importing a tool module (single source of truth for planned/
practical figures — spec rule #7).
"""

from __future__ import annotations

from datetime import datetime, time as dt_time, timedelta

from .odoo_client import OdooError
from .workflow_helpers import optional_fields

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
     [("crossovered_budget_id.state", "in", ["confirm", "validate", "done"])]),
]

_PRACTICAL_CANDIDATES = ["practical_amount", "achieved_amount"]
# Odoo spells the crossovered-era field "theoritical" in some series.
_THEORETICAL_CANDIDATES = ["theoretical_amount", "theoritical_amount"]
_PARENT_CANDIDATES = ["crossovered_budget_id", "budget_analytic_id"]

# parent m2o field on a budget line -> the parent budget model it points to
_PARENT_MODEL = {
    "crossovered_budget_id": "crossovered.budget",
    "budget_analytic_id": "budget.analytic",
}


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


def _parse_ymd(value, param: str):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise OdooError(f"Invalid {param} {value!r}: expected YYYY-MM-DD")


def periods_domain(
    field: str,
    periods: list[dict] | None,
    timezone_offset: int,
    as_datetime: bool = True,
) -> list:
    """OR-of-closed-ranges domain on `field` (spec: OR between periods,
    NOT a union — gaps between non-adjacent budgets stay excluded).

    as_datetime=True: bounds are local 00:00:00 / 23:59:59 at
    timezone_offset, converted to UTC datetime strings. False: plain
    YYYY-MM-DD strings for date (not datetime) fields.
    """
    subs: list[list] = []
    for i, period in enumerate(periods or []):
        d_from = (period or {}).get("date_from")
        d_to = (period or {}).get("date_to")
        if not d_from and not d_to:
            raise OdooError(
                f"periods[{i}] needs date_from and/or date_to")
        leaves: list = []
        if d_from:
            day = _parse_ymd(d_from, f"periods[{i}].date_from")
            if as_datetime:
                low = (datetime.combine(day, dt_time.min)
                       - timedelta(hours=timezone_offset)
                       ).strftime("%Y-%m-%d %H:%M:%S")
            else:
                low = day.isoformat()
            leaves.append((field, ">=", low))
        if d_to:
            day = _parse_ymd(d_to, f"periods[{i}].date_to")
            if as_datetime:
                high = (datetime.combine(day, dt_time(23, 59, 59))
                        - timedelta(hours=timezone_offset)
                        ).strftime("%Y-%m-%d %H:%M:%S")
            else:
                high = day.isoformat()
            leaves.append((field, "<=", high))
        subs.append(leaves)
    if not subs:
        return []
    if len(subs) == 1:
        return subs[0]
    out: list = ["|"] * (len(subs) - 1)
    for leaves in subs:
        if len(leaves) == 2:
            out.append("&")
        out.extend(leaves)
    return out


def paged_search_read(
    client,
    model: str,
    domain: list,
    fields: list[str],
    page: int = 500,
    max_pages: int = 50,
    order: str = "id",
) -> list[dict]:
    """Fetch ALL matching rows by offset pagination, server-side.

    The MCP client still sees one tool call; only this process talks to
    Odoo repeatedly. Page size respects client.config.max_records the same
    way client.search_read caps limits. A stable `order` keeps pages
    non-overlapping. Stops on the first short page; raises past max_pages
    so a runaway filter cannot loop forever.
    """
    step = min(page, client.config.max_records)
    rows: list[dict] = []
    for i in range(max_pages):
        batch = client.search_read(
            model, domain=domain, fields=fields,
            limit=step, offset=i * step, order=order)
        rows.extend(batch)
        if len(batch) < step:
            return rows
    raise OdooError(
        f"{model}: more than {max_pages * step} rows match; "
        "narrow the filters.")

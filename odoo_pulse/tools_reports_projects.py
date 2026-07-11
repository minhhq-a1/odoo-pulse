# odoo_pulse/tools_reports_projects.py
"""Project profitability report: delivery hours, money and budget burn.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based burn verdict. Read-only.

Caveats for callers:
- Analytic amounts are in each company's currency (mixed_companies risk).
- Two projects sharing one analytic account each get the full account's
  cost/revenue/budget (accepted double-count; splitting would be arbitrary).
- On Odoo 18+ the budget state filter is skipped (state lives on the parent
  budget.analytic and drifts across minor versions); revenue-type budgets
  ARE excluded via a dotted budget_type domain — when that field is missing
  on the instance the aggregate faults and budgets degrade to unavailable.
"""

from __future__ import annotations

from .odoo_client import OdooError
from .runtime import get_client, mcp, safe
from .workflow_helpers import (
    build_report,
    distinct_companies,
    ensure_field,
    fetch_with_truncation,
    gather_strict,
    optional_fields,
    parse_when,
    today_in_tz,
)

_TIMESHEET_HINT = ("Timesheets require the hr_timesheet app; install it to "
                   "report delivery hours.")

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


def _validate_date(value: str | None, param: str) -> str | None:
    """YYYY-MM-DD passthrough; garbage -> clean OdooError (parse_when raises
    ValueError, which safe() would render as an ugly 'internal error:')."""
    if not value:
        return None
    try:
        parse_when(value)
    except ValueError:
        raise OdooError(f"Invalid {param} {value!r}: expected YYYY-MM-DD")
    return str(value)[:10]


def _verdict(
    hours_burn: float | None,
    budget_burn: float | None,
    at_risk_pct: float,
    off_track_pct: float,
) -> tuple[str, float | None]:
    """(verdict, worst_burn). Nothing to burn against -> on_track, None
    (the no_allocation risk surfaces that case instead)."""
    burns = [b for b in (hours_burn, budget_burn) if b is not None]
    if not burns:
        return "on_track", None
    worst = max(burns)
    if worst >= off_track_pct:
        return "off_track", worst
    if worst >= at_risk_pct:
        return "at_risk", worst
    return "on_track", worst


def _budget_by_account(
    client, account_ids: list[int]
) -> tuple[dict[int, float], bool]:
    """Planned budget (absolute) per analytic account id + budgets_available.

    The FIRST call against each candidate model is a real RPC
    (search_count) inside try/except OdooError — fields_get is NOT a
    reliable absence probe (see the design doc: the FakeClient returns a
    default schema for unknown models, and the degradation path must be
    identical under test and in production). Model absent or candidate
    fields unresolvable -> next candidate; none usable -> ({}, False).
    """
    if not account_ids:
        return {}, False
    candidates = list(_BUDGET_CANDIDATES)
    major = client.major_version()
    if major is not None and major <= 17:
        candidates.reverse()
    for model, acct_candidates, amount_candidates, extra_domain in candidates:
        try:
            client.search_count(model, [])
        except OdooError:
            continue
        acct_fields = optional_fields(client, model, acct_candidates)
        amount_fields = optional_fields(client, model, amount_candidates)
        if not acct_fields or not amount_fields:
            continue
        acct_field, amount_field = acct_fields[0], amount_fields[0]
        try:
            agg = client.aggregate_records(
                model, group_by=[acct_field],
                measures=[(amount_field, "sum")],
                domain=[(acct_field, "in", account_ids), *extra_domain])
        except OdooError:
            continue
        budgets: dict[int, float] = {}
        for row in agg.get("rows", []):
            acct = row.get(acct_field)
            if acct:
                budgets[acct[0]] = abs(row.get(f"{amount_field}:sum") or 0.0)
        return budgets, True
    return {}, False

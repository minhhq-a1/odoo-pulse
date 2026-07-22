# odoo_pulse/tools_reports_projects.py
"""Project profitability report: delivery hours, money and budget burn.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based burn verdict. Read-only.

Caveats for callers:
- Analytic amounts are in each company's currency (mixed_companies risk).
- Two projects sharing one analytic account each get the full account's
  cost/revenue/budget (accepted double-count; splitting would be arbitrary).
- Budgets match per line: a line's own project_id link, when present and
  in scope, is authoritative; only unlinked lines fall back to matching by
  analytic account. An out-of-scope project link never leaks onto other
  projects, and a shared analytic account still double-counts across every
  project that shares it.
- On Odoo 18+ the budget state filter is skipped (state lives on the parent
  budget.analytic and drifts across minor versions); revenue-type budgets
  ARE excluded via a dotted budget_type domain — when that field is missing
  on the instance the aggregate faults and budgets degrade to unavailable.
"""

from __future__ import annotations

from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .services.projects.budget import build_project_budget_report
from .services.projects.profitability import build_project_profitability_report


@mcp.tool()
def project_budget(
    project: str | None = None,
    manager: str | None = None,
    customer: str | None = None,
    top_n: int = 10,
    burn_pct_at_risk: float = 80.0,
    burn_pct_off_track: float = 100.0,
    timezone_offset: int = 7,
) -> str:
    """Report planned vs actual budget per project, line by line.

    Reads the Budgets app (budget.line on Odoo 18+, else
    crossovered.budget.lines) and matches lines to active projects by a
    line-level project_id m2o when the instance has one, else through the
    project's analytic account. Amounts are absolute company-currency
    sums; server-computed practical/theoretical amounts are used as-is.
    Also compares each project's total analytic cost against the practical
    amounts booked on its budget lines, flagging spend the budget does not
    capture. When the filter matches exactly one project the report gains
    a per-line breakdown. No date filters: budget lines carry their own
    period.

    Args:
        project: Optional project-name filter (name ilike). Exactly one
            match switches on the per-line breakdown.
        manager: Optional project-manager filter (user_id.name ilike).
        customer: Optional customer filter (partner_id.name ilike).
        top_n: Rows in the per-line breakdown (default 10).
        burn_pct_at_risk: Burn %% >= this -> at_risk (default 80).
        burn_pct_off_track: Burn %% >= this -> off_track (default 100).
        timezone_offset: UTC offset for "today" (default 7).
    """

    return safe(lambda: build_project_budget_report(
        get_client(), project=project, manager=manager, customer=customer,
        top_n=top_n, burn_pct_at_risk=burn_pct_at_risk,
        burn_pct_off_track=burn_pct_off_track,
        timezone_offset=timezone_offset,
    ))


@mcp.tool()
def project_profitability(
    project: str | None = None,
    manager: str | None = None,
    customer: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    top_n: int = 5,
    burn_pct_at_risk: float = 80.0,
    burn_pct_off_track: float = 100.0,
    timezone_offset: int = 7,
) -> str:
    """Report delivery hours, money and budget burn per project in one call.

    Composes active project.project records (filtered by name / manager /
    customer) with timesheet hours (account.analytic.line grouped by
    project), analytic cost/revenue (grouped by analytic account) and the
    Budgets app when installed, into a per-project burn verdict
    (off_track / at_risk / on_track). When the filter matches exactly one
    project the report gains per-employee and per-task breakdowns.

    Args:
        project: Optional project-name filter (name ilike). Exactly one
            match switches on the drill-down breakdowns.
        manager: Optional project-manager filter (user_id.name ilike).
        customer: Optional customer filter (partner_id.name ilike).
        date_from: Optional YYYY-MM-DD lower bound on logged hours and
            analytic amounts. Allocated hours and budgets stay lifetime
            totals, so ANY date filter disables the burn verdicts
            (verdict "n/a", burn percentages null).
        date_to: Optional YYYY-MM-DD upper bound (same caveat).
        top_n: Rows in the drill-down breakdowns (default 5).
        burn_pct_at_risk: Worst burn %% >= this -> at_risk (default 80).
        burn_pct_off_track: Worst burn %% >= this -> off_track (default 100).
        timezone_offset: UTC offset for "today" (default 7).
    """

    return safe(lambda: build_project_profitability_report(
        get_client(), project=project, manager=manager, customer=customer,
        date_from=date_from, date_to=date_to, top_n=top_n,
        burn_pct_at_risk=burn_pct_at_risk,
        burn_pct_off_track=burn_pct_off_track,
        timezone_offset=timezone_offset,
    ))

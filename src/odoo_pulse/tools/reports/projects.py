"""Project report and workflow tools."""

from __future__ import annotations

from ...mcp.app import mcp
from ...mcp.result import safe, safe_text
from ...mcp.runtime import get_client
from ...services.projects.budget import build_project_budget_report
from ...services.projects.dashboard import build_project_dashboard
from ...services.projects.health import build_portfolio_health, build_project_status_report
from ...services.projects.profitability import build_project_profitability_report
from ...services.projects.standup import build_standup_digest
from ...services.projects.subtasks import build_project_subtask_hours
from ...services.projects.workload import build_team_workload


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


@mcp.tool()
def project_subtask_hours(
    project_id: int,
    only_closed_stages: bool = False,
    closed_stage_names: list[str] | None = None,
    single_assignee_only: bool = False,
    group_by_month: bool = False,
    periods: list[dict] | None = None,
    timezone_offset: int = 7,
) -> str:
    """Total sub-task hours for one project, filtered server-side, in ONE call.

    Sums delivery/allocated/effective hours over the project's sub-tasks
    (project.task with parent_id set). Use this instead of paginating
    project.task through search_read — especially for the "exactly one
    assignee" condition, which Odoo domains cannot express.

    Args:
        project_id: project.project id (int, not name).
        only_closed_stages: Count only tasks whose stage name is in
            closed_stage_names (default False). Cancelled tasks DO count
            toward delivery hours (business decision 2026-07-15).
        closed_stage_names: Stage names treated as closed (default
            ["Done", "Cancelled", "Delivered"]).
        single_assignee_only: Count only tasks with exactly 1 user in
            user_ids (default False).
        group_by_month: Also bucket by local-time month of date_end;
            tasks without date_end are excluded from the buckets and
            summarised under "no_date_end" (default False).
        periods: Optional list of {"date_from": "YYYY-MM-DD",
            "date_to": "YYYY-MM-DD"} ranges applied to date_end,
            OR-combined (matching per-budget-period filtering, not a
            union). Empty/omitted = no date filter.
        timezone_offset: UTC offset for dates (default 7).
    """
    return safe(lambda: build_project_subtask_hours(
        get_client(),
        project_id=project_id,
        only_closed_stages=only_closed_stages,
        closed_stage_names=closed_stage_names,
        single_assignee_only=single_assignee_only,
        group_by_month=group_by_month,
        periods=periods,
        timezone_offset=timezone_offset,
    ))


@mcp.tool()
def project_dashboard(
    project_id: int,
    only_closed_stages: bool = False,
    closed_stage_names: list[str] | None = None,
    single_assignee_only: bool = False,
    budget_ids: list[int] | None = None,
    include: list[str] | None = None,
    lookahead_days: int = 7,
    timezone_offset: int = 7,
) -> str:
    """Everything the project-detail page needs, in one call.

    Replaces ~12 separate calls (status, profitability, milestones,
    weekly hours, budgets, budget lines, cost breakdowns, delivery by
    month). Use `include` to re-fetch only what changed: checkbox toggles
    -> ["hours", "delivery_monthly"]; budget chip changes ->
    ["budget_detail", "delivery_monthly"].

    Sections fail soft: a broken section lands in "errors" while the
    rest return.

    Args:
        project_id: project.project id.
        only_closed_stages / closed_stage_names / single_assignee_only:
            sub-task filters, as in project_subtask_hours; they shape the
            "hours" and "delivery_monthly" sections.
        budget_ids: crossovered.budget / budget.analytic ids to select.
            OMIT (null) for ALL budgets of the project; pass [] for NO
            selection (budget_detail then shows all-time cost only).
            These two states are different on purpose — do not send []
            to mean "all".
        include: Subset of ["core", "hours", "budgets", "budget_detail",
            "delivery_monthly"]; omitted = all. "core" covers project,
            milestones, finance and weekly_logged.
        lookahead_days: "due soon" window for derived health (default 7).
        timezone_offset: UTC offset for dates (default 7).
    """
    return safe(lambda: build_project_dashboard(
        get_client(), project_id=project_id,
        only_closed_stages=only_closed_stages,
        closed_stage_names=closed_stage_names,
        single_assignee_only=single_assignee_only,
        budget_ids=budget_ids, include=include,
        lookahead_days=lookahead_days,
        timezone_offset=timezone_offset,
    ))


@mcp.tool()
def portfolio_health(
    manager: str | None = None,
    customer: str | None = None,
    include_on_hold: bool = True,
    include_done: bool = False,
    lookahead_days: int = 7,
    timezone_offset: int = 7,
) -> str:
    """Portfolio overview: one row per project, joined by id server-side.

    Replaces the project_status_report + project_profitability pair the
    overview tab used to call and join BY NAME in JS (which broke on
    duplicate project names). Returns raw signals only — the client
    computes its own health score from user-configured thresholds.

    Args:
        manager: Optional project-manager filter (user_id.name ilike).
        customer: Optional customer filter (partner_id.name ilike).
        include_on_hold: Keep on_hold projects (default True).
        include_done: Keep done projects (default False).
        lookahead_days: "due soon" window for derived health (default 7).
        timezone_offset: UTC offset for dates (default 7).
    """
    return safe(lambda: build_portfolio_health(
        get_client(), manager=manager, customer=customer,
        include_on_hold=include_on_hold, include_done=include_done,
        lookahead_days=lookahead_days, timezone_offset=timezone_offset,
    ))


@mcp.tool()
def team_workload(
    project: str | None = None,
    exclude_stages: list[str] | None = None,
    done_stages: list[str] | None = None,
    lookahead_days: int = 7,
    overload_threshold: int = 8,
    timezone_offset: int = 7,
    subtasks_only: bool = True,
) -> str:
    """Report who is over- or under-loaded, in one call.

    Composes the open project.task records in scope into a per-assignee load
    (open count plus overdue / due-soon / high-priority / no-deadline tallies),
    flags overloaded members and unassigned work, and returns a rule-based
    verdict. Done tasks carry no current load and are excluded.

    Args:
        project: Optional project-name filter (ilike).
        exclude_stages: Stage names dropped from scope. Default ["Cancelled"].
        done_stages: Stage names treated as completed. Default ["Done", "Delivered"].
        lookahead_days: Days ahead that count as "due soon" (default 7).
        overload_threshold: Open-task count above which a member is flagged
            "overloaded" (default 8). Sign-off point with the workflow owner.
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
        subtasks_only: Count only subtasks (parent_id != False), the team's unit
            of work. Default True.
    """
    return safe(lambda: build_team_workload(
        get_client(), project=project, exclude_stages=exclude_stages,
        done_stages=done_stages, lookahead_days=lookahead_days,
        overload_threshold=overload_threshold, timezone_offset=timezone_offset,
        subtasks_only=subtasks_only,
    ))


@mcp.tool()
def project_status_report(
    manager: str | None = None,
    customer: str | None = None,
    project: str | None = None,
    include_on_hold: bool = True,
    include_done: bool = False,
    lookahead_days: int = 7,
    timezone_offset: int = 7,
) -> str:
    """Report which projects are in trouble, across a portfolio, in one call.

    Composes project.project records (filtered by manager / customer / name)
    with their project.milestone rows into a per-project derived health verdict
    (off_track / at_risk / on_track) driven by overdue-or-unreached milestones
    and the project end date. Surfaces the PM's declared status alongside, flags
    projects declared healthier than the data (divergence), and ranks by risk.

    Args:
        manager: Optional project-manager filter (user_id.name ilike).
        customer: Optional customer filter (partner_id.name ilike).
        project: Optional project-name filter (name ilike) to narrow the set.
        include_on_hold: Keep projects whose declared status is on_hold (default True).
        include_done: Keep projects whose declared status is done (default False).
        lookahead_days: Days ahead that count as "due soon" for at_risk (default 7).
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
    """
    return safe(lambda: build_project_status_report(
        get_client(), manager=manager, customer=customer, project=project,
        include_on_hold=include_on_hold, include_done=include_done,
        lookahead_days=lookahead_days, timezone_offset=timezone_offset,
    ))


@mcp.tool()
def standup_digest(
    project: str,
    exclude_stages: list[str] | None = None,
    lookahead_days: int = 7,
    timezone_offset: int = 7,
) -> str:
    """Generate a daily standup digest for a project.

    Fetches all active subtasks (parent_id != False, stage not in exclude_stages,
    exactly 1 assigned user) and categorises them by deadline into OVERDUE / TODAY /
    UPCOMING / NO DEADLINE sections.  Returns a plain-text digest ready to paste or
    send as an email body.

    Args:
        project: Project name (ilike match, e.g. "The Body Shop").
        exclude_stages: Stage names to treat as closed. Defaults to
            ["Done", "Cancelled", "Delivered"].
        lookahead_days: Days ahead to include in UPCOMING (default 7).
        timezone_offset: UTC offset in hours for "today" (default 7 = Asia/Ho_Chi_Minh).
    """
    return safe_text(lambda: build_standup_digest(
        get_client(), project=project, exclude_stages=exclude_stages,
        lookahead_days=lookahead_days, timezone_offset=timezone_offset,
    ))

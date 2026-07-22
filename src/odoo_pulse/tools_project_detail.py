# odoo_pulse/tools_project_detail.py
"""Project-detail tools backing the "Project Status" artifact.

One MCP call replaces the 10-30 paginated client-side calls the artifact
used to make (the direct cause of its MCP rate-limit errors). Output is
the spec's free-form schema, NOT the build_report envelope — intentional:
these tools feed a dashboard, not a reader. Read-only. Everything
computes on this server in Python; odoo-pulse has no SQL access.

Spec: docs/superpowers/specs/spec-odoo-pulse-project-status.md (Rev 2).
"""

from __future__ import annotations

from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .services.projects.dashboard import build_project_dashboard
from .services.projects.health import build_portfolio_health
from .services.projects.subtasks import build_project_subtask_hours


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

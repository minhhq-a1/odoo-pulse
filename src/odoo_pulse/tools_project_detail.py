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

from datetime import timedelta

from .common.dates import today_in_tz
from .common.paging import fetch_with_truncation
from .common.schema import optional_fields
from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .services.projects.budget import budget_by_project
from .services.projects.dashboard import build_project_dashboard
from .services.projects.health import derive_project_health
from .services.projects.profitability import analytic_money
from .services.projects.queries import account_ids_by_project
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

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        cutoff = today + timedelta(days=lookahead_days)

        domain: list = [("active", "=", True)]
        if manager:
            domain.append(("user_id.name", "ilike", manager))
        if customer:
            domain.append(("partner_id.name", "ilike", customer))
        if not include_done:
            domain.append(("last_update_status", "!=", "done"))
        if not include_on_hold:
            domain.append(("last_update_status", "!=", "on_hold"))

        opt = optional_fields(client, "project.project",
                              ["allocated_hours", "account_id",
                               "analytic_account_id"])
        projects, truncation = fetch_with_truncation(
            client, "project.project", domain,
            fields=["id", "name", "user_id", "partner_id", "date",
                    "task_count", "last_update_status", *opt],
            limit=200, order="name")

        ids = [p["id"] for p in projects]
        acct_by_project = account_ids_by_project(projects, opt)
        account_ids = sorted(set(acct_by_project.values()))
        has_alloc = "allocated_hours" in opt

        ms_by_project: dict[int, list] = {}
        hours_by_project: dict[int, float] = {}
        cost_by: dict[int, float] = {}
        rev_by: dict[int, float] = {}
        budgets: dict[int, float] = {}
        budgets_available = False
        milestones_truncation = None
        if ids:
            milestones, milestones_truncation = fetch_with_truncation(
                client, "project.milestone",
                [("project_id", "in", ids)],
                fields=["id", "name", "deadline", "is_reached",
                        "project_id"],
                limit=200, order="deadline")
            for m in milestones:
                pid = m["project_id"][0] if m.get("project_id") else None
                if pid is not None:
                    ms_by_project.setdefault(pid, []).append(m)
            hours_agg = client.aggregate_records(
                "account.analytic.line", group_by=["project_id"],
                measures=[("unit_amount", "sum")],
                domain=[("project_id", "in", ids)])
            for row in hours_agg.get("rows", []):
                m2o = row.get("project_id")
                if m2o:
                    hours_by_project[m2o[0]] = (
                        row.get("unit_amount:sum") or 0.0)
            cost_by, rev_by = analytic_money(client, account_ids)
            budgets, budgets_available = budget_by_project(
                client, ids, acct_by_project)

        rows_out: list[dict] = []
        off_track = total_overdue = divergent = past_end = 0
        for p in projects:
            pid = p["id"]
            h = derive_project_health(
                p, ms_by_project.get(pid, []), today, cutoff,
                timezone_offset)
            acct_id = acct_by_project.get(pid)
            cost = cost_by.get(acct_id, 0.0) if acct_id is not None else 0.0
            revenue = (rev_by.get(acct_id, 0.0)
                       if acct_id is not None else 0.0)
            budget = budgets.get(pid) if budgets_available else None
            alloc = (p.get("allocated_hours") or 0.0) if has_alloc else 0.0
            hours = hours_by_project.get(pid, 0.0)

            if h["derived_health"] == "off_track":
                off_track += 1
            total_overdue += h["overdue"]
            if h["divergent"]:
                divergent += 1
            if h["past_end"]:
                past_end += 1

            rows_out.append({
                "project_id": pid,
                "project": p["name"],
                "manager": p["user_id"][1] if p.get("user_id") else None,
                "customer": (p["partner_id"][1]
                             if p.get("partner_id") else None),
                "end_date": p.get("date") or None,
                "task_count": p.get("task_count", 0),
                "milestones": {"reached": h["reached"],
                               "total": h["total"]},
                "overdue_milestones": h["overdue"],
                "next_milestone": h["next_milestone"],
                "native_status": h["native_status"],
                "derived_health": h["derived_health"],
                "divergent": h["divergent"],
                "revenue": round(revenue, 2),
                "cost": round(cost, 2),
                "margin": round(revenue - cost, 2),
                "budget": round(budget, 2) if budget is not None else None,
                "budget_burn_pct": (round(cost / budget * 100, 1)
                                    if budget else None),
                "hours_burn_pct": (round(hours / alloc * 100, 1)
                                   if alloc else None),
            })

        rank = {"off_track": 0, "at_risk": 1, "on_track": 2}
        rows_out.sort(key=lambda r: (rank[r["derived_health"]],
                                     -r["overdue_milestones"],
                                     r["project"]))

        risks: list[dict] = []
        if truncation:
            risks.append({
                "code": "truncated_data", "count": truncation["missing"],
                "message": (
                    f"Report covers only {truncation['fetched']} of "
                    f"{truncation['total_matching']} matching projects.")})
        if milestones_truncation:
            risks.append({
                "code": "truncated_milestone_data",
                "count": milestones_truncation["missing"],
                "message": (
                    f"Report covers only {milestones_truncation['fetched']} "
                    f"of {milestones_truncation['total_matching']} matching "
                    "milestone(s); per-project milestone counts may be "
                    "incomplete.")})
        if off_track:
            risks.append({"code": "off_track_projects", "count": off_track,
                          "message": f"{off_track} project(s) off track"})
        if total_overdue:
            risks.append({
                "code": "overdue_milestones", "count": total_overdue,
                "message": (f"{total_overdue} milestone(s) overdue and "
                            "unreached")})
        if past_end:
            risks.append({
                "code": "past_end_projects", "count": past_end,
                "message": f"{past_end} project(s) past their end date"})
        if divergent:
            risks.append({
                "code": "health_divergence", "count": divergent,
                "message": (f"{divergent} project(s) declared healthier "
                            "than the data")})

        return {"tool": "portfolio_health", "as_of": today.isoformat(),
                "filters": {"manager": manager, "customer": customer,
                            "include_on_hold": include_on_hold,
                            "include_done": include_done},
                "budgets_available": budgets_available,
                "projects": rows_out, "risks": risks}

    return safe(run)

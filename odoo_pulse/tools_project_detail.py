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

from .odoo_client import OdooError
from .project_shared import (
    DEFAULT_CLOSED_STAGES,
    analytic_money,
    derive_project_health,
    fetch_subtasks,
    paged_search_read,
    subtasks_by_month,
    sum_hours,
)
from .runtime import get_client, mcp, safe
from .workflow_helpers import optional_fields, parse_when, today_in_tz


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

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        tasks, available, warnings = fetch_subtasks(
            client, project_id,
            only_closed_stages=only_closed_stages,
            closed_stage_names=closed_stage_names,
            single_assignee_only=single_assignee_only,
            periods=periods, timezone_offset=timezone_offset)
        report: dict = {
            "tool": "project_subtask_hours",
            "as_of": today.isoformat(),
            "project_id": project_id,
            "filters": {
                "only_closed_stages": only_closed_stages,
                "closed_stage_names": list(
                    closed_stage_names or DEFAULT_CLOSED_STAGES),
                "single_assignee_only": single_assignee_only,
                "periods": periods or [],
            },
        }
        if warnings:
            report["warnings"] = warnings
        report["totals"] = sum_hours(tasks, available)
        if group_by_month:
            by_month, no_date_end = subtasks_by_month(
                tasks, available, timezone_offset)
            report["by_month"] = by_month
            report["no_date_end"] = no_date_end
        return report

    return safe(run)


def _acct_id_of(project_row: dict, opt: list[str]) -> int | None:
    field = next((f for f in ("account_id", "analytic_account_id")
                  if f in opt), None)
    m2o = project_row.get(field) if field else None
    return m2o[0] if m2o else None


def _weekly_logged(client, project_id: int, today) -> list[dict]:
    """Hours per ISO week (Monday week_start) over the last 84 days.

    Bucketing happens here in Python instead of read_group's date:week —
    read_group returns localized week labels that vary by lang/version,
    while a raw date field is stable. The current partial week is
    included; the client decides how to render it.
    """
    since = today - timedelta(days=84)
    lines = paged_search_read(
        client, "account.analytic.line",
        [("project_id", "=", project_id), ("date", ">=", since.isoformat())],
        fields=["date", "unit_amount"])
    buckets: dict = {}
    for ln in lines:
        day = parse_when(ln.get("date"))
        if day is None:
            continue
        monday = day - timedelta(days=day.weekday())
        buckets[monday] = buckets.get(monday, 0.0) + (ln.get("unit_amount")
                                                      or 0.0)
    return [{"week_start": d.isoformat(), "hours": round(h, 2)}
            for d, h in sorted(buckets.items())]


def _core_section(client, project_id: int, timezone_offset: int,
                  lookahead_days: int) -> dict:
    today = today_in_tz(timezone_offset)
    cutoff = today + timedelta(days=lookahead_days)
    opt = optional_fields(client, "project.project",
                          ["delivery_hours", "account_id",
                           "analytic_account_id"])
    warnings = ([] if "delivery_hours" in opt else
                ["field delivery_hours does not exist on project.project"])
    rows = client.search_read(
        "project.project", domain=[("id", "=", project_id)],
        fields=["id", "name", "user_id", "partner_id", "date",
                "task_count", "last_update_status", *opt],
        limit=1)
    if not rows:
        raise OdooError(f"No project.project with id {project_id}")
    p = rows[0]

    ms_opt = optional_fields(client, "project.milestone",
                             ["revised_date", "actual_date"])
    milestones = client.search_read(
        "project.milestone", domain=[("project_id", "=", project_id)],
        fields=["id", "name", "deadline", "is_reached", *ms_opt],
        limit=200, order="deadline")
    h = derive_project_health(p, milestones, today, cutoff,
                              timezone_offset)

    acct_id = _acct_id_of(p, opt)
    cost_by, rev_by = analytic_money(
        client, [acct_id] if acct_id is not None else [])
    cost = cost_by.get(acct_id, 0.0) if acct_id is not None else 0.0
    revenue = rev_by.get(acct_id, 0.0) if acct_id is not None else 0.0

    return {
        "project": {
            "id": p["id"], "name": p["name"],
            "manager": p["user_id"][1] if p.get("user_id") else None,
            "customer": p["partner_id"][1] if p.get("partner_id") else None,
            "end_date": p.get("date") or None,
            "task_count": p.get("task_count", 0),
            "native_status": h["native_status"],
            "derived_health": h["derived_health"],
            "divergent": h["divergent"],
            "delivery_hours": (p.get("delivery_hours")
                               if "delivery_hours" in opt else None),
        },
        "milestones": {
            "reached": h["reached"], "total": h["total"],
            "overdue": h["overdue"],
            "next_unreached": h["next_milestone"],
            "list": [{
                "name": m["name"],
                "deadline": m.get("deadline") or None,
                "revised_date": (m.get("revised_date") or None
                                 if "revised_date" in ms_opt else None),
                "actual_date": (m.get("actual_date") or None
                                if "actual_date" in ms_opt else None),
                "is_reached": bool(m.get("is_reached")),
            } for m in milestones],
        },
        "finance": {
            "revenue": round(revenue, 2),
            "cost_all_time": round(cost, 2),
            "margin": round(revenue - cost, 2),
        },
        "weekly_logged": _weekly_logged(client, project_id, today),
        "warnings": warnings,
    }


def _hours_section(client, project_id: int, only_closed_stages: bool,
                   closed_stage_names: list[str] | None,
                   single_assignee_only: bool,
                   timezone_offset: int) -> dict:
    tasks, available, warnings = fetch_subtasks(
        client, project_id, only_closed_stages=only_closed_stages,
        closed_stage_names=closed_stage_names,
        single_assignee_only=single_assignee_only,
        timezone_offset=timezone_offset)
    totals = sum_hours(tasks, available)

    def leaderboard(group_field: str, id_key: str, label_key: str):
        agg = client.aggregate_records(
            "account.analytic.line", group_by=[group_field],
            measures=[("unit_amount", "sum")],
            domain=[("project_id", "=", project_id)],
            limit=50, order="unit_amount:sum desc")
        return [{id_key: row[group_field][0],
                 label_key: row[group_field][1],
                 "hours": round(row.get("unit_amount:sum") or 0.0, 2)}
                for row in agg.get("rows", []) if row.get(group_field)]

    return {
        "hours": {
            "subtask_delivery": totals["delivery_hours"],
            "subtask_allocated": totals["allocated_hours"],
            "subtask_effective": totals["effective_hours"],
            "by_employee": leaderboard("employee_id", "employee_id",
                                       "employee"),
            "by_task": leaderboard("task_id", "task_id", "task"),
        },
        "warnings": warnings,
    }

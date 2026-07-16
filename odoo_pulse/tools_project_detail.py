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

from .project_shared import (
    DEFAULT_CLOSED_STAGES,
    fetch_subtasks,
    subtasks_by_month,
    sum_hours,
)
from .runtime import get_client, mcp, safe
from .workflow_helpers import today_in_tz


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

# odoo_pulse/tools_workflows.py
"""Composed workflow tools: business questions answered in one call.

Each tool composes several reads/aggregates server-side and returns a
decision-ready report (the envelope from common.reporting.build_report).
Read-only; no new write surface.
"""

from __future__ import annotations

from .mcp.app import mcp
from .mcp.result import safe, safe_text
from .mcp.runtime import get_client
from .services.projects.health import build_project_status_report
from .services.projects.standup import build_standup_digest
from .services.projects.workload import build_team_workload


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

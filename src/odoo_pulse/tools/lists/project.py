"""Read-only domain tools for Project management and Timesheets.

Covered models:
  - project.project          (projects)
  - project.task             (tasks)
  - account.analytic.line    (timesheets, via hr_timesheet)
"""

from __future__ import annotations

import json

from ...common.domains import name_domain
from ...core.errors import OdooConfigError, OdooError
from ...mcp.app import mcp
from ...mcp.result import safe
from ...mcp.runtime import get_client
from ...services.generic import search_records
from ...services.projects.queries import build_task_list, build_timesheet_list


@mcp.tool()
def list_projects(query: str | None = None, limit: int = 20) -> str:
    """List projects (project.project).

    Args:
        query: Free text matched against the project name.
        limit: Max results.
    """
    domain = name_domain(query, ["name"])
    return safe(
        lambda: search_records(
            get_client(),
            "project.project",
            domain=domain,
            fields=[
                "name",
                "partner_id",
                "user_id",
                "task_count",
                "date_start",
                "date",
            ],
            limit=limit,
            order="name",
        )
    )


@mcp.tool()
def list_tasks(
    query: str | None = None,
    project: str | None = None,
    assignee: str | None = None,
    stage: str | None = None,
    include_subtasks: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List project tasks (project.task).

    Odoo caps XML-RPC results at 200 per call. Use offset to paginate when a
    project has more tasks than the limit (e.g. limit=200, offset=200 for page 2).

    user_ids is resolved to [{id, name}] objects via a single batch lookup.

    Args:
        query: Free text matched against the task name.
        project: Filter by project name.
        assignee: Filter by an assigned user's name.
        stage: Filter by stage name (e.g. 'To Do', 'In Progress', 'Done').
        include_subtasks: When False (default) only top-level tasks are returned.
            Set to True to include subtasks (parent_id != False) as well.
        limit: Max results per page (Odoo hard-caps at 200).
        offset: Number of records to skip; use with limit to paginate.
    """
    try:
        tasks = build_task_list(
            get_client(),
            query=query,
            project=project,
            assignee=assignee,
            stage=stage,
            include_subtasks=include_subtasks,
            limit=limit,
            offset=offset,
        )
        return json.dumps(tasks, ensure_ascii=False, indent=2, default=str)
    except (OdooConfigError, OdooError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)


@mcp.tool()
def list_timesheets(
    employee: str | None = None,
    project: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> str:
    """List timesheet entries (account.analytic.line with a project set).

    Args:
        employee: Filter by employee name.
        project: Filter by project name.
        date_from: Inclusive lower bound on the entry date (YYYY-MM-DD).
        date_to: Inclusive upper bound on the entry date (YYYY-MM-DD).
        limit: Max results.
    """
    return safe(
        lambda: build_timesheet_list(
            get_client(),
            employee=employee,
            project=project,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    )

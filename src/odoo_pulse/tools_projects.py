"""Read-only domain tools for Project management and Timesheets.

Covered models:
  - project.project          (projects)
  - project.task             (tasks)
  - account.analytic.line    (timesheets, via hr_timesheet)
"""

from __future__ import annotations

import json

from .common.dates import date_domain
from .common.domains import name_domain
from .core.errors import OdooConfigError, OdooError
from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .workflow_helpers import ensure_field, resolve_user_names



@mcp.tool()
def list_projects(query: str | None = None, limit: int = 20) -> str:
    """List projects (project.project).

    Args:
        query: Free text matched against the project name.
        limit: Max results.
    """
    domain = name_domain(query, ["name"])
    return safe(
        lambda: get_client().search_read(
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
    domain = name_domain(query, ["name"])
    if not include_subtasks:
        domain.append(("parent_id", "=", False))
    if project:
        domain.append(("project_id.name", "ilike", project))
    if assignee:
        domain.append(("user_ids.name", "ilike", assignee))
    if stage:
        domain.append(("stage_id.name", "ilike", stage))

    try:
        client = get_client()
        fields = [
            "name",
            "project_id",
            "user_ids",
            "stage_id",
            "date_deadline",
            "priority",
            "state",
            "parent_id",
        ]
        tasks = client.search_read(
            "project.task",
            domain=domain,
            fields=fields,
            limit=limit,
            offset=offset,
            order="priority desc, date_deadline",
        )

        all_user_ids = {uid for t in tasks for uid in t.get("user_ids", [])}
        if all_user_ids:
            user_map = resolve_user_names(client, all_user_ids)
            for task in tasks:
                task["user_ids"] = [
                    {"id": uid, "name": user_map.get(uid, str(uid))}
                    for uid in task.get("user_ids", [])
                ]

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

    def run():
        client = get_client()
        ensure_field(
            client,
            "account.analytic.line",
            "project_id",
            hint="Timesheets require the hr_timesheet app; install it or use list_tasks instead.",
        )
        domain: list = [("project_id", "!=", False)]
        if employee:
            domain.append(("employee_id.name", "ilike", employee))
        if project:
            domain.append(("project_id.name", "ilike", project))
        domain.extend(date_domain("date", date_from, date_to))
        return client.search_read(
            "account.analytic.line",
            domain=domain,
            fields=["name", "employee_id", "project_id", "task_id", "unit_amount", "date"],
            limit=limit,
            order="date desc",
        )

    return safe(run)

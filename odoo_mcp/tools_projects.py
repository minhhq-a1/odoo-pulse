"""Read-only domain tools for Project management and Timesheets.

Covered models:
  - project.project          (projects)
  - project.task             (tasks)
  - account.analytic.line    (timesheets, via hr_timesheet)
"""

from __future__ import annotations

from .runtime import date_domain, get_client, mcp, name_domain, safe


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
    limit: int = 20,
) -> str:
    """List project tasks (project.task).

    Args:
        query: Free text matched against the task name.
        project: Filter by project name.
        assignee: Filter by an assigned user's name.
        stage: Filter by stage name (e.g. 'To Do', 'In Progress', 'Done').
        limit: Max results.
    """
    domain = name_domain(query, ["name"])
    if project:
        domain.append(("project_id.name", "ilike", project))
    if assignee:
        domain.append(("user_ids.name", "ilike", assignee))
    if stage:
        domain.append(("stage_id.name", "ilike", stage))
    return safe(
        lambda: get_client().search_read(
            "project.task",
            domain=domain,
            fields=[
                "name",
                "project_id",
                "user_ids",
                "stage_id",
                "date_deadline",
                "priority",
                "kanban_state",
            ],
            limit=limit,
            order="priority desc, date_deadline",
        )
    )


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
    domain: list = [("project_id", "!=", False)]
    if employee:
        domain.append(("employee_id.name", "ilike", employee))
    if project:
        domain.append(("project_id.name", "ilike", project))
    domain += date_domain("date", date_from, date_to)
    return safe(
        lambda: get_client().search_read(
            "account.analytic.line",
            domain=domain,
            fields=["name", "employee_id", "project_id", "task_id", "unit_amount", "date"],
            limit=limit,
            order="date desc",
        )
    )

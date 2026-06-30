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
    import json as _json

    from .odoo_client import OdooConfigError, OdooError

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
        tasks = client.search_read(
            "project.task",
            domain=domain,
            fields=[
                "name",
                "project_id",
                "user_ids",
                "stage_id",
                "date_deadline",
                "priority",
                "state",
                "parent_id",
            ],
            limit=limit,
            offset=offset,
            order="priority desc, date_deadline",
        )

        all_user_ids = {uid for t in tasks for uid in t.get("user_ids", [])}
        if all_user_ids:
            users = client.execute_kw(
                "res.users",
                "search_read",
                [[("id", "in", list(all_user_ids))]],
                {"fields": ["id", "name"], "limit": len(all_user_ids), "context": {"active_test": False}},
            )
            user_map = {u["id"]: u["name"] for u in users}
            for task in tasks:
                task["user_ids"] = [
                    {"id": uid, "name": user_map.get(uid, str(uid))}
                    for uid in task.get("user_ids", [])
                ]

        return _json.dumps(tasks, ensure_ascii=False, indent=2, default=str)
    except (OdooConfigError, OdooError) as exc:
        return _json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)


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
    import json as _json
    from datetime import datetime, timedelta, timezone

    from .odoo_client import OdooConfigError, OdooError

    if exclude_stages is None:
        exclude_stages = ["Done", "Cancelled", "Delivered"]
    exclude_lower = {s.lower() for s in exclude_stages}

    tz = timezone(timedelta(hours=timezone_offset))
    today = datetime.now(tz).date()
    today_str = today.strftime("%d/%m/%Y")
    cutoff = today + timedelta(days=lookahead_days)

    try:
        client = get_client()

        domain = [
            ("project_id.name", "ilike", project),
            ("parent_id", "!=", False),
            ("stage_id.name", "not in", exclude_stages),
        ]
        tasks = client.search_read(
            "project.task",
            domain=domain,
            fields=["id", "name", "user_ids", "stage_id", "date_deadline", "priority"],
            limit=200,
            order="date_deadline",
        )

        # Resolve user names including archived users
        all_uid = {uid for t in tasks for uid in t.get("user_ids", [])}
        user_map: dict[int, str] = {}
        if all_uid:
            users = client.execute_kw(
                "res.users",
                "search_read",
                [[("id", "in", list(all_uid))]],
                {"fields": ["id", "name"], "limit": len(all_uid), "context": {"active_test": False}},
            )
            user_map = {u["id"]: u["name"] for u in users}

        # Filter: exactly 1 assignee
        filtered = [t for t in tasks if len(t.get("user_ids", [])) == 1]

        overdue: list[dict] = []
        today_tasks: list[dict] = []
        upcoming: list[dict] = []
        no_deadline: list[dict] = []

        for t in filtered:
            uid = t["user_ids"][0]
            entry = {
                "id": t["id"],
                "name": t["name"],
                "assignee": user_map.get(uid, f"User#{uid}"),
                "priority": "High" if t.get("priority") == "1" else "Normal",
                "deadline": None,
            }
            dd_raw = t.get("date_deadline")
            if not dd_raw:
                no_deadline.append(entry)
                continue
            dd = datetime.strptime(dd_raw[:10], "%Y-%m-%d").date()
            entry["deadline"] = dd
            if dd < today:
                overdue.append(entry)
            elif dd == today:
                today_tasks.append(entry)
            elif dd <= cutoff:
                upcoming.append(entry)
            # beyond lookahead: omitted per spec

        overdue.sort(key=lambda x: x["deadline"])
        today_tasks.sort(key=lambda x: x["name"])
        upcoming.sort(key=lambda x: x["deadline"])
        no_deadline.sort(key=lambda x: x["name"])

        def days_ago(d) -> str:
            n = (today - d).days
            return f"{n} day{'s' if n != 1 else ''} ago"

        lines = [f"=== Daily Standup — {project} — {today_str} ===\n"]
        lines.append(f"OVERDUE ({len(overdue)})")
        for t in overdue:
            lines.append(f"  ❌ #{t['id']} [{t['priority']}] {t['name']} — Assigned: {t['assignee']} — Due: {days_ago(t['deadline'])}")
        lines.append(f"\nTODAY ({len(today_tasks)})")
        for t in today_tasks:
            lines.append(f"  ⏳ #{t['id']} [{t['priority']}] {t['name']} — Assigned: {t['assignee']} — Due: Today")
        lines.append(f"\nUPCOMING ({len(upcoming)})")
        for t in upcoming:
            lines.append(f"  ⭕ #{t['id']} [{t['priority']}] {t['name']} — Assigned: {t['assignee']} — Due: {t['deadline'].strftime('%d/%m/%Y')}")
        lines.append(f"\nNO DEADLINE ({len(no_deadline)})")
        for t in no_deadline:
            lines.append(f"  ❓ #{t['id']} [{t['priority']}] {t['name']} — Assigned: {t['assignee']}")
        lines.append(f"\n---\nSummary: {len(overdue)} overdue, {len(today_tasks)} today, {len(upcoming)} upcoming, {len(no_deadline)} no deadline")

        return "\n".join(lines)

    except (OdooConfigError, OdooError) as exc:
        return _json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)


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

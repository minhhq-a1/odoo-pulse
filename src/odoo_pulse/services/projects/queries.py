# odoo_pulse/services/projects/queries.py
"""Read-only project-domain query helpers.

These orchestrate reads through an Odoo client (real or fake). They never
write. Keeping them here lets multiple composed tools (and standup_digest)
stay DRY and independently testable.
"""

from __future__ import annotations

from typing import Any


from ...common.dates import date_domain
from ...common.domains import name_domain
from ...common.schema import ensure_field


def resolve_user_names(client: Any, user_ids: Any) -> dict[int, str]:
    """Map res.users ids to names, including archived users.

    Returns {} and makes no call when there are no ids. De-duplicates ids.
    """
    ids = list({uid for uid in user_ids})
    if not ids:
        return {}
    users = client.execute_kw(
        "res.users",
        "search_read",
        [[("id", "in", ids)]],
        {"fields": ["id", "name"], "limit": len(ids), "context": {"active_test": False}},
    )
    return {u["id"]: u["name"] for u in users}


def project_domain(
    *, project=None, manager=None, customer=None,
    include_on_hold=True, include_done=True,
) -> list:
    domain: list = [("active", "=", True)]
    if project:
        domain.append(("name", "ilike", project))
    if manager:
        domain.append(("user_id.name", "ilike", manager))
    if customer:
        domain.append(("partner_id.name", "ilike", customer))
    if not include_done:
        domain.append(("last_update_status", "!=", "done"))
    if not include_on_hold:
        domain.append(("last_update_status", "!=", "on_hold"))
    return domain


def milestones_by_project(rows: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        project = row.get("project_id")
        if project:
            grouped.setdefault(project[0], []).append(row)
    return grouped


# project.project's analytic account field was renamed analytic_account_id
# -> account_id in Odoo 18; this order tries the current name first.
_ACCOUNT_FIELD_CANDIDATES = ("account_id", "analytic_account_id")


def account_field_of(opt: list[str]) -> str | None:
    """Which analytic-account field exists on this project.project schema.

    `opt` is any optional_fields(...) result that included the candidates
    (it may also contain unrelated fields — only the account ones matter
    here). Single source of truth for the field-name pick so a future Odoo
    rename only needs updating in _ACCOUNT_FIELD_CANDIDATES.
    """
    return next((f for f in _ACCOUNT_FIELD_CANDIDATES if f in opt), None)


def account_id_of(project_row: dict, opt: list[str]) -> int | None:
    """The project's own analytic account id, or None if it has none."""
    field = account_field_of(opt)
    m2o = project_row.get(field) if field else None
    return m2o[0] if m2o else None


def account_ids_by_project(projects: list[dict], opt: list[str]
                           ) -> dict[int, int]:
    """{project_id: account_id} for every project in `projects` that has
    an analytic account set."""
    field = account_field_of(opt)
    return {p["id"]: p[field][0] for p in projects
            if field and p.get(field)}


def build_task_list(client: Any, *, query: str | None = None,
                    project: str | None = None,
                    assignee: str | None = None,
                    stage: str | None = None,
                    include_subtasks: bool = False,
                    limit: int = 20, offset: int = 0) -> list[dict]:
    domain = name_domain(query, ["name"])
    if not include_subtasks:
        domain.append(("parent_id", "=", False))
    if project:
        domain.append(("project_id.name", "ilike", project))
    if assignee:
        domain.append(("user_ids.name", "ilike", assignee))
    if stage:
        domain.append(("stage_id.name", "ilike", stage))

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

    return tasks


def build_timesheet_list(client: Any, *, employee: str | None = None,
                         project: str | None = None,
                         date_from: str | None = None,
                         date_to: str | None = None,
                         limit: int = 20) -> list[dict]:
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


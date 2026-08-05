# odoo_pulse/services/projects/subtasks.py
"""Task closed/open scope resolution shared by project workflow tools.

Scope is always resolved by matching stage_id.name against the caller's
stage_names. project.task's own `state`/`is_closed` flags are Kanban
fold/closed markers configured per stage -- they do not reliably correspond
to the named stages the caller asked for (a custom stage folded in the
Kanban view but not named "Done"/"Cancelled"/"Delivered" would be miscounted
as closed), so they are not used here. These never write.
"""

from __future__ import annotations

from ...common.dates import parse_period_date, parse_when, periods_domain, today_in_tz
from ...common.paging import paged_search_read
from ...common.schema import optional_fields


def stage_name_scope(*, closed: bool, stage_names: list[str]) -> list:
    """Server-side domain matching tasks by literal stage name."""
    operator = "in" if closed else "not in"
    return [("stage_id.name", operator, stage_names)]


def task_matches_stage(task: dict, *, closed: bool, stage_names: list[str]) -> bool:
    """Client-side case-insensitive re-check (Odoo's `in` domain operator on
    a related field is case-sensitive)."""
    stage = task.get("stage_id")
    name = stage[1].casefold() if stage else ""
    is_closed = name in {value.casefold() for value in stage_names}
    return is_closed if closed else not is_closed


# -- subtask fetch/filter/aggregate helpers ----------------------------------

HOUR_FIELDS = ("delivery_hours", "allocated_hours", "effective_hours")
DEFAULT_CLOSED_STAGES = ("Done", "Cancelled", "Delivered")


def fetch_subtasks(
    client,
    project_id: int,
    only_closed_stages: bool = False,
    closed_stage_names: list[str] | None = None,
    single_assignee_only: bool = False,
    periods: list[dict] | None = None,
    timezone_offset: int = 7,
) -> tuple[list[dict], list[str], list[str]]:
    """All sub-tasks of a project matching the spec filters.

    Returns (tasks, available_hour_fields, warnings). delivery_hours is a
    custom field in the wild — absent fields degrade to a warning instead
    of failing (spec Rev 2). single_assignee (count of a m2m) cannot be a
    domain, so it filters in Python — the whole point of this helper: the
    MCP client gets one call instead of paging 750 tasks itself.
    """
    available = optional_fields(client, "project.task", list(HOUR_FIELDS))
    warnings = [f"field {f} does not exist on project.task"
                for f in HOUR_FIELDS if f not in available]
    domain: list = [("project_id", "=", project_id),
                    ("parent_id", "!=", False)]
    names: list[str] = []
    if only_closed_stages:
        names = list(closed_stage_names or DEFAULT_CLOSED_STAGES)
        domain.extend(stage_name_scope(closed=True, stage_names=names))
    domain += periods_domain("date_end", periods, timezone_offset,
                             as_datetime=True)
    tasks = paged_search_read(
        client, "project.task", domain,
        fields=["id", "user_ids", "date_end", "stage_id", *available])
    if only_closed_stages:
        tasks = [t for t in tasks if task_matches_stage(
            t, closed=True, stage_names=names)]
    if single_assignee_only:
        tasks = [t for t in tasks if len(t.get("user_ids") or []) == 1]
    return tasks, available, warnings


def sum_hours(tasks: list[dict], available: list[str]) -> dict:
    """Totals for one task bucket; unavailable hour fields stay None."""
    out: dict = {"task_count": len(tasks)}
    for f in HOUR_FIELDS:
        out[f] = (round(sum(t.get(f) or 0.0 for t in tasks), 2)
                  if f in available else None)
    return out


def subtasks_by_month(
    tasks: list[dict], available: list[str], timezone_offset: int
) -> tuple[list[dict], dict]:
    """Bucket tasks by the local-time month of date_end.

    Tasks without date_end are excluded from the months and summarised in
    the second return value so the client can see what was dropped.
    """
    buckets: dict[str, list[dict]] = {}
    undated: list[dict] = []
    for t in tasks:
        day = parse_when(t.get("date_end"), timezone_offset)
        if day is None:
            undated.append(t)
        else:
            buckets.setdefault(day.strftime("%Y-%m"), []).append(t)
    by_month = [{"month": month, **sum_hours(rows, available)}
                for month, rows in sorted(buckets.items())]
    return by_month, sum_hours(undated, available)


def filter_subtasks_by_periods(
    tasks: list[dict], periods: list[dict] | None, timezone_offset: int
) -> list[dict]:
    """Python-side equivalent of adding periods_domain("date_end", periods,
    timezone_offset) to fetch_subtasks' domain.

    Same semantics as the server-side domain: OR-of-ranges (a task matching
    ANY period is kept, not just tasks inside the min..max span across all
    periods), no periods -> no filter at all, and — once a period filter IS
    active — tasks without date_end are excluded (a domain comparison
    against a null date_end matches nothing server-side; here that has to
    be done explicitly rather than falling out of the comparison).
    """
    if not periods:
        return list(tasks)
    ranges = [
        (parse_period_date(p["date_from"], "date_from")
         if p.get("date_from") else None,
         parse_period_date(p["date_to"], "date_to")
         if p.get("date_to") else None)
        for p in periods
    ]
    out = []
    for t in tasks:
        day = parse_when(t.get("date_end"), timezone_offset)
        if day is None:
            continue
        if any((lo is None or day >= lo) and (hi is None or day <= hi)
               for lo, hi in ranges):
            out.append(t)
    return out


def build_project_subtask_hours(
    client, *, project_id, only_closed_stages=False,
    closed_stage_names=None, single_assignee_only=False,
    group_by_month=False, periods=None, timezone_offset=7,
) -> dict:
    today = today_in_tz(timezone_offset)
    tasks, available, warnings = fetch_subtasks(
        client, project_id,
        only_closed_stages=only_closed_stages,
        closed_stage_names=closed_stage_names,
        single_assignee_only=single_assignee_only,
        periods=periods,
        timezone_offset=timezone_offset,
    )
    report = {
        "tool": "project_subtask_hours",
        "as_of": today.isoformat(),
        "project_id": project_id,
        "filters": {
            "only_closed_stages": only_closed_stages,
            "closed_stage_names": list(
                closed_stage_names or DEFAULT_CLOSED_STAGES
            ),
            "single_assignee_only": single_assignee_only,
            "periods": periods or [],
        },
    }
    if warnings:
        report["warnings"] = warnings
    report["totals"] = sum_hours(tasks, available)
    if group_by_month:
        by_month, no_date_end = subtasks_by_month(
            tasks, available, timezone_offset
        )
        report["by_month"] = by_month
        report["no_date_end"] = no_date_end
    return report

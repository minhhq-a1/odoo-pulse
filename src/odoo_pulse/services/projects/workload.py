"""Team workload report service."""

from __future__ import annotations

from datetime import timedelta

from ...common.dates import parse_when
from ...common.paging import fetch_with_truncation
from ...common.reporting import build_report
from ..report_context import build_report_context
from .queries import resolve_user_names
from .subtasks import (
    task_closed_scope,
    task_matches_scope,
    task_scope_warning,
)


def build_team_workload(
    client,
    *,
    project: str | None = None,
    exclude_stages: list[str] | None = None,
    done_stages: list[str] | None = None,
    lookahead_days: int = 7,
    overload_threshold: int = 8,
    timezone_offset: int = 7,
    subtasks_only: bool = True,
) -> dict:
    context = build_report_context(client, timezone_offset=timezone_offset)
    today = context.today
    ex = exclude_stages if exclude_stages is not None else ["Cancelled"]
    done_names = done_stages if done_stages is not None else ["Done", "Delivered"]

    domain: list = []
    if subtasks_only:
        domain.append(("parent_id", "!=", False))
    if project:
        domain.append(("project_id.name", "ilike", project))
    if ex:
        domain.append(("stage_id.name", "not in", ex))

    scope_domain, scope_fields, scope_strategy = task_closed_scope(
        client, closed=False, stage_names=done_names)
    domain.extend(scope_domain)

    tasks, truncation = fetch_with_truncation(
        client,
        "project.task",
        domain,
        fields=[
            "id", "name", "user_ids", "stage_id",
            "date_deadline", "priority", "parent_id",
            *scope_fields,
        ],
        limit=200,
        order="date_deadline",
    )

    cutoff = today + timedelta(days=lookahead_days)

    # uid (or None for unassigned) -> load tallies
    load: dict[object, dict] = {}
    open_tasks = 0
    unassigned = 0

    def _bucket(uid):
        return load.setdefault(
            uid,
            {"open": 0, "overdue": 0, "due_soon": 0, "high_priority": 0, "no_deadline": 0},
        )

    for t in tasks:
        if not task_matches_scope(
                t, scope_strategy, closed=False, stage_names=done_names):
            continue

        open_tasks += 1
        assignees = t.get("user_ids") or []
        if not assignees:
            unassigned += 1

        dd = parse_when(t.get("date_deadline"), timezone_offset)
        high = t.get("priority") == "1"

        for uid in assignees or [None]:
            rec = _bucket(uid)
            rec["open"] += 1
            if dd is None:
                rec["no_deadline"] += 1
            elif dd < today:
                rec["overdue"] += 1
            elif dd <= cutoff:
                rec["due_soon"] += 1
            if high:
                rec["high_priority"] += 1

    real_uids = [uid for uid in load if uid is not None]
    names = resolve_user_names(client, real_uids)

    by_assignee = []
    overloaded_members = 0
    busiest = None
    busiest_open = 0
    assigned_load = 0
    for uid, rec in load.items():
        if uid is None:
            name = "(unassigned)"
            status = "unassigned"
        else:
            name = names.get(uid, f"User#{uid}")
            status = "overloaded" if rec["open"] > overload_threshold else "ok"
            if status == "overloaded":
                overloaded_members += 1
            assigned_load += rec["open"]
            if rec["open"] > busiest_open:
                busiest_open = rec["open"]
                busiest = name
        by_assignee.append({"assignee": name, **rec, "status": status})

    by_assignee.sort(key=lambda r: (-r["open"], r["assignee"]))

    members = len(real_uids)
    avg_open_per_member = round(assigned_load / members, 1) if members else 0.0

    if overloaded_members > 0 or unassigned > 0:
        verdict = "action_needed"
    else:
        verdict = "balanced"

    summary = {
        "members": members,
        "open_tasks": open_tasks,
        "unassigned": unassigned,
        "overloaded_members": overloaded_members,
        "busiest": busiest,
        "busiest_open": busiest_open,
        "avg_open_per_member": avg_open_per_member,
        "verdict": verdict,
    }
    if truncation:
        summary["truncated"] = True
        summary["total_matching"] = truncation["total_matching"]

    highlights = [f"{open_tasks} open task(s) across {members} member(s)"]
    if busiest:
        highlights.append(f"busiest: {busiest} ({busiest_open} open)")
    if overloaded_members:
        highlights.append(f"{overloaded_members} member(s) over {overload_threshold} open")

    risks: list[dict] = []
    if truncation:
        risks.append({
            "code": "truncated_data", "count": truncation["missing"],
            "message": (
                f"Report covers only {truncation['fetched']} of "
                f"{truncation['total_matching']} matching task(s); "
                "workload figures may not reflect everyone in scope."
            ),
        })
    if overloaded_members:
        risks.append({"code": "overloaded_members", "count": overloaded_members,
                      "message": f"{overloaded_members} member(s) above {overload_threshold} open tasks"})
    if unassigned:
        risks.append({"code": "unassigned_open_tasks", "count": unassigned,
                      "message": f"{unassigned} open task(s) with no assignee"})
    scope_warning = task_scope_warning(scope_strategy)
    if scope_warning:
        risks.append({
            "code": "task_state_fallback",
            "count": truncation["missing"] if truncation else 1,
            "message": scope_warning,
        })

    return build_report(
        "team_workload",
        today,
        summary=summary,
        breakdown={"by_assignee": by_assignee},
        highlights=highlights,
        risks=risks,
        extra={"project": project},
    )

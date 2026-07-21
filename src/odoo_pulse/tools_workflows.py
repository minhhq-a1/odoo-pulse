# odoo_pulse/tools_workflows.py
"""Composed workflow tools: business questions answered in one call.

Each tool composes several reads/aggregates server-side and returns a
decision-ready report (the envelope from common.reporting.build_report).
Read-only; no new write surface.
"""

from __future__ import annotations

import json
from datetime import timedelta

from .common.dates import parse_when, today_in_tz
from .common.paging import fetch_with_truncation
from .common.reporting import build_report
from .core.errors import OdooConfigError, OdooError
from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .services.projects.health import build_project_status_report
from .services.projects.queries import resolve_user_names
from .services.projects.subtasks import (
    task_closed_scope,
    task_matches_scope,
    task_scope_warning,
)




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

    def run() -> dict:
        client = get_client()
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

        today = today_in_tz(timezone_offset)
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

    return safe(run)


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
    if exclude_stages is None:
        exclude_stages = ["Done", "Cancelled", "Delivered"]

    today = today_in_tz(timezone_offset)
    today_str = today.strftime("%d/%m/%Y")
    cutoff = today + timedelta(days=lookahead_days)

    try:
        client = get_client()
        domain = [
            ("project_id.name", "ilike", project),
            ("parent_id", "!=", False),
            ("stage_id.name", "not in", exclude_stages),
        ]

        scope_domain, scope_fields, scope_strategy = task_closed_scope(
            client, closed=False, stage_names=exclude_stages)
        domain.extend(scope_domain)
        scope_warning = task_scope_warning(scope_strategy)

        tasks, truncation = fetch_with_truncation(
            client, "project.task", domain,
            fields=["id", "name", "user_ids", "stage_id",
                    "date_deadline", "priority", *scope_fields],
            limit=200, order="date_deadline",
        )

        # Defensively re-filter client-side (stable state/is_closed schemas
        # already filter server-side; the stage-name fallback needs this).
        tasks = [t for t in tasks if task_matches_scope(
            t, scope_strategy, closed=False, stage_names=exclude_stages)]

        # Resolve user names including archived users (shared helper).
        all_uid = {uid for t in tasks for uid in t.get("user_ids", [])}
        user_map = resolve_user_names(client, all_uid)

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
            dd = parse_when(t.get("date_deadline"), timezone_offset)
            if dd is None:
                no_deadline.append(entry)
                continue
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
            return f"{n} ngày trước" if n > 1 else "hôm qua"

        def task_table(rows: list[dict], deadline_col: str, deadline_fn) -> list[str]:
            out = [
                f"| # | Task | Assignee | {deadline_col} |",
                f"|---|------|----------|{''.join(['-'] * len(deadline_col))}--|",
            ]
            for t in rows:
                raw_name = t["name"].replace("|", "\\|")
                name = f"🔴 {raw_name}" if t["priority"] == "High" else raw_name
                out.append(f"| #{t['id']} | {name} | {t['assignee']} | {deadline_fn(t)} |")
            return out

        lines = [f"## 🗓️ Daily Standup — {project}", f"**{today_str}**"]
        if scope_warning:
            lines.append(f"> ⚠️ {scope_warning}")
        lines.append("")

        if truncation:
            lines.append(
                f"⚠️ Chỉ hiển thị {truncation['fetched']}/"
                f"{truncation['total_matching']} task — dữ liệu bị cắt bớt.")
            lines.append("")

        if overdue:
            lines.append(f"### ❌ Quá hạn ({len(overdue)})")
            lines += task_table(overdue, "Quá hạn", lambda t: days_ago(t["deadline"]))
            lines.append("")

        if today_tasks:
            lines.append(f"### ⏳ Hôm nay ({len(today_tasks)})")
            lines += task_table(today_tasks, "Deadline", lambda t: "Hôm nay")
            lines.append("")

        if upcoming:
            lines.append(f"### ⭕ Sắp đến hạn ({len(upcoming)})")
            lines += task_table(upcoming, "Deadline", lambda t: t["deadline"].strftime("%d/%m/%Y"))
            lines.append("")

        if no_deadline:
            lines.append(f"### ❓ Chưa có deadline ({len(no_deadline)})")
            lines += task_table(no_deadline, "Deadline", lambda t: "—")
            lines.append("")

        total = len(overdue) + len(today_tasks) + len(upcoming) + len(no_deadline)
        if total == 0:
            lines.append("✅ Không có task pending nào hôm nay.")
        else:
            parts = []
            if overdue:
                parts.append(f"**{len(overdue)} quá hạn**")
            if today_tasks:
                parts.append(f"**{len(today_tasks)} hôm nay**")
            if upcoming:
                parts.append(f"{len(upcoming)} sắp đến")
            if no_deadline:
                parts.append(f"{len(no_deadline)} chưa có deadline")
            lines.append(f"---\n📊 Tổng: {' · '.join(parts)}")

        return "\n".join(lines)

    # This tool's success contract is markdown, not JSON, so `safe()` (which
    # always serialises to JSON) is unsuitable here; keep a local try/except
    # that still returns a JSON error string on failure.
    except (OdooConfigError, OdooError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)
    except Exception as exc:  # shaping bugs must not leak raw tracebacks
        return json.dumps(
            {"error": f"internal error: {type(exc).__name__}: {exc}"},
            ensure_ascii=False, indent=2,
        )


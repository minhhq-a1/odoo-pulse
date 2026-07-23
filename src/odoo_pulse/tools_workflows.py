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


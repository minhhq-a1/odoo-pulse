# odoo_pulse/tools_workflows.py
"""Composed workflow tools: business questions answered in one call.

Each tool composes several reads/aggregates server-side and returns a
decision-ready report (the envelope from workflow_helpers.build_report).
Read-only; no new write surface.
"""

from __future__ import annotations

from datetime import timedelta

from .runtime import get_client, mcp, safe
from .workflow_helpers import (
    build_report,
    fetch_with_truncation,
    parse_deadline,
    resolve_user_names,
    today_in_tz,
)


@mcp.tool()
def sprint_health(
    sprint_id: int,
    project: str | None = None,
    exclude_stages: list[str] | None = None,
    done_stages: list[str] | None = None,
    lookahead_days: int = 7,
    timezone_offset: int = 7,
    subtasks_only: bool = True,
) -> str:
    """Report whether a sprint is on track, in one call.

    Composes project.task records for the sprint into completion %, deadline
    buckets (overdue / due today / upcoming / no deadline), assignment health,
    a per-stage and per-assignee breakdown, and a rule-based verdict.

    Args:
        sprint_id: The project.task sprint_id to report on.
        project: Optional project-name filter (ilike).
        exclude_stages: Stage names dropped from sprint scope. Default ["Cancelled"].
        done_stages: Stage names counted as completed. Default ["Done", "Delivered"].
        lookahead_days: Days ahead that count as "upcoming" (default 7).
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
        subtasks_only: Count only subtasks (parent_id != False), the team's unit
            of work. Default True.
    """

    def run() -> dict:
        client = get_client()
        ex = exclude_stages if exclude_stages is not None else ["Cancelled"]
        done_set = {
            s.lower() for s in (done_stages if done_stages is not None else ["Done", "Delivered"])
        }

        domain: list = [("sprint_id", "=", sprint_id)]
        if subtasks_only:
            domain.append(("parent_id", "!=", False))
        if project:
            domain.append(("project_id.name", "ilike", project))
        if ex:
            domain.append(("stage_id.name", "not in", ex))

        tasks, truncation = fetch_with_truncation(
            client,
            "project.task",
            domain,
            fields=[
                "id", "name", "user_ids", "stage_id",
                "date_deadline", "priority", "parent_id",
            ],
            limit=200,
            order="date_deadline",
        )

        today = today_in_tz(timezone_offset)
        cutoff = today + timedelta(days=lookahead_days)

        total = len(tasks)
        done = 0
        overdue = due_today = upcoming = no_deadline = unassigned = over_assigned = 0
        stage_counts: dict[str, int] = {}
        assignee_open: dict[object, int] = {}

        for t in tasks:
            stage = t["stage_id"][1] if t.get("stage_id") else "(none)"
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
            if stage.lower() in done_set:
                done += 1
                continue

            assignees = t.get("user_ids") or []
            if not assignees:
                unassigned += 1
                assignee_open[None] = assignee_open.get(None, 0) + 1
            else:
                if len(assignees) > 1:
                    over_assigned += 1
                for uid in assignees:
                    assignee_open[uid] = assignee_open.get(uid, 0) + 1

            dd = parse_deadline(t.get("date_deadline"))
            if dd is None:
                no_deadline += 1
            elif dd < today:
                overdue += 1
            elif dd == today:
                due_today += 1
            elif dd <= cutoff:
                upcoming += 1

        open_ = total - done
        pct_done = round(done / total * 100, 1) if total else 0.0

        if overdue > 0 or unassigned > 0:
            verdict = "off_track"
        elif no_deadline > 0:
            verdict = "at_risk"
        else:
            verdict = "on_track"

        names = resolve_user_names(client, [uid for uid in assignee_open if uid is not None])
        by_assignee = [
            {
                "assignee": "(unassigned)" if uid is None else names.get(uid, f"User#{uid}"),
                "open": cnt,
            }
            for uid, cnt in assignee_open.items()
        ]
        by_assignee.sort(key=lambda r: (-r["open"], r["assignee"]))

        by_stage = [{"stage": s, "count": c} for s, c in stage_counts.items()]
        by_stage.sort(key=lambda r: (-r["count"], r["stage"]))

        summary = {
            "total": total,
            "done": done,
            "open": open_,
            "pct_done": pct_done,
            "overdue": overdue,
            "due_today": due_today,
            "upcoming": upcoming,
            "no_deadline": no_deadline,
            "unassigned": unassigned,
            "over_assigned": over_assigned,
            "verdict": verdict,
        }
        if truncation:
            summary["truncated"] = True
            summary["total_matching"] = truncation["total_matching"]

        highlights = [f"{pct_done}% done ({done}/{total})"]
        if due_today:
            highlights.append(f"{due_today} due today")
        if upcoming:
            highlights.append(f"{upcoming} due within {lookahead_days} days")

        risks: list[dict] = []
        if truncation:
            risks.append({
                "code": "truncated_data", "count": truncation["missing"],
                "message": (
                    f"Report covers only {truncation['fetched']} of "
                    f"{truncation['total_matching']} matching task(s); "
                    "the verdict may not reflect the full sprint."
                ),
            })
        if overdue:
            risks.append({"code": "overdue_open_tasks", "count": overdue,
                          "message": f"{overdue} open task(s) past deadline"})
        if no_deadline:
            risks.append({"code": "open_tasks_without_deadline", "count": no_deadline,
                          "message": f"{no_deadline} open task(s) without a deadline"})
        if unassigned:
            risks.append({"code": "unassigned_open_tasks", "count": unassigned,
                          "message": f"{unassigned} open task(s) with no assignee"})
        if over_assigned:
            risks.append({"code": "multiple_assignees", "count": over_assigned,
                          "message": f"{over_assigned} open task(s) with multiple assignees"})

        return build_report(
            "sprint_health",
            today,
            summary=summary,
            breakdown={"by_stage": by_stage, "by_assignee": by_assignee},
            highlights=highlights,
            risks=risks,
            extra={"sprint_id": sprint_id, "project": project},
        )

    return safe(run)


@mcp.tool()
def team_workload(
    project: str | None = None,
    sprint_id: int | None = None,
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
        sprint_id: Optional sprint filter (project.task sprint_id).
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
        done_set = {
            s.lower() for s in (done_stages if done_stages is not None else ["Done", "Delivered"])
        }

        domain: list = []
        if sprint_id is not None:
            domain.append(("sprint_id", "=", sprint_id))
        if subtasks_only:
            domain.append(("parent_id", "!=", False))
        if project:
            domain.append(("project_id.name", "ilike", project))
        if ex:
            domain.append(("stage_id.name", "not in", ex))

        tasks, truncation = fetch_with_truncation(
            client,
            "project.task",
            domain,
            fields=[
                "id", "name", "user_ids", "stage_id",
                "date_deadline", "priority", "parent_id",
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
            stage = t["stage_id"][1] if t.get("stage_id") else "(none)"
            if stage.lower() in done_set:
                continue

            open_tasks += 1
            assignees = t.get("user_ids") or []
            if not assignees:
                unassigned += 1

            dd = parse_deadline(t.get("date_deadline"))
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

        return build_report(
            "team_workload",
            today,
            summary=summary,
            breakdown={"by_assignee": by_assignee},
            highlights=highlights,
            risks=risks,
            extra={"project": project, "sprint_id": sprint_id},
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

    def run() -> dict:
        client = get_client()

        domain: list = [("active", "=", True)]
        if manager:
            domain.append(("user_id.name", "ilike", manager))
        if customer:
            domain.append(("partner_id.name", "ilike", customer))
        if project:
            domain.append(("name", "ilike", project))
        if not include_done:
            domain.append(("last_update_status", "!=", "done"))
        if not include_on_hold:
            domain.append(("last_update_status", "!=", "on_hold"))

        projects, projects_truncation = fetch_with_truncation(
            client,
            "project.project",
            domain,
            fields=[
                "id", "name", "user_id", "partner_id",
                "date_start", "date", "last_update_status", "task_count",
            ],
            limit=200,
            order="name",
        )

        today = today_in_tz(timezone_offset)
        cutoff = today + timedelta(days=lookahead_days)

        ids = [p["id"] for p in projects]
        if ids:
            milestones, milestones_truncation = fetch_with_truncation(
                client,
                "project.milestone",
                [("project_id", "in", ids)],
                fields=["id", "name", "deadline", "is_reached", "project_id"],
                limit=200,
                order="deadline",
            )
        else:
            milestones, milestones_truncation = [], None

        ms_by_project: dict[int, list] = {}
        for m in milestones:
            pid = m["project_id"][0] if m.get("project_id") else None
            if pid is not None:
                ms_by_project.setdefault(pid, []).append(m)

        rank = {"off_track": 0, "at_risk": 1, "on_track": 2}
        rows: list[dict] = []
        off_track = at_risk = on_track = 0
        total_overdue_ms = 0
        past_end_projects = 0
        divergent = 0

        for p in projects:
            native = p.get("last_update_status") or "to_define"
            ms = ms_by_project.get(p["id"], [])
            total_ms = len(ms)
            reached_ms = sum(1 for m in ms if m.get("is_reached"))

            overdue_ms = 0
            soon_ms = 0
            next_milestone = None
            for m in ms:  # ordered by deadline asc from the query
                if m.get("is_reached"):
                    continue
                dd = parse_deadline(m.get("deadline"))
                if dd is None:
                    continue
                if next_milestone is None:
                    next_milestone = {"name": m["name"], "deadline": m["deadline"]}
                if dd < today:
                    overdue_ms += 1
                elif dd <= cutoff:
                    soon_ms += 1

            end = parse_deadline(p.get("date"))
            past_end = end is not None and end < today and native != "done"
            end_soon = end is not None and today <= end <= cutoff

            if overdue_ms > 0 or past_end:
                derived = "off_track"
                off_track += 1
            elif soon_ms > 0 or end_soon:
                derived = "at_risk"
                at_risk += 1
            else:
                derived = "on_track"
                on_track += 1

            total_overdue_ms += overdue_ms
            if past_end:
                past_end_projects += 1

            is_div = (
                (native in ("on_track", "on_hold") and derived == "off_track")
                or (native == "on_track" and derived == "at_risk")
            )
            if is_div:
                divergent += 1

            rows.append({
                "project": p["name"],
                "manager": p["user_id"][1] if p.get("user_id") else None,
                "customer": p["partner_id"][1] if p.get("partner_id") else None,
                "end_date": p.get("date") or None,
                "task_count": p.get("task_count", 0),
                "milestones": {"reached": reached_ms, "total": total_ms},
                "overdue_milestones": overdue_ms,
                "next_milestone": next_milestone,
                "native_status": native,
                "derived_health": derived,
                "divergent": is_div,
            })

        rows.sort(key=lambda r: (rank[r["derived_health"]],
                                 -r["overdue_milestones"], r["project"]))

        if off_track > 0 or divergent > 0:
            verdict = "action_needed"
        elif at_risk > 0:
            verdict = "watch"
        else:
            verdict = "healthy"

        summary = {
            "projects": len(projects),
            "off_track": off_track,
            "at_risk": at_risk,
            "on_track": on_track,
            "overdue_milestones": total_overdue_ms,
            "past_end_projects": past_end_projects,
            "divergent": divergent,
            "verdict": verdict,
        }
        if projects_truncation:
            summary["projects_truncated"] = True
            summary["total_projects_matching"] = projects_truncation["total_matching"]
        if milestones_truncation:
            summary["milestones_truncated"] = True
            summary["total_milestones_matching"] = milestones_truncation["total_matching"]

        highlights = [f"{off_track} of {len(projects)} project(s) off track"]
        if rows and rows[0]["overdue_milestones"] > 0:
            top = rows[0]
            highlights.append(
                f"{top['project']}: {top['overdue_milestones']} milestone(s) overdue"
            )
        if divergent:
            highlights.append(f"{divergent} project(s) declared healthier than actual")

        risks: list[dict] = []
        if projects_truncation:
            risks.append({
                "code": "truncated_data", "count": projects_truncation["missing"],
                "message": (
                    f"Report covers only {projects_truncation['fetched']} of "
                    f"{projects_truncation['total_matching']} matching project(s); "
                    "the portfolio verdict may not reflect the full set."
                ),
            })
        if milestones_truncation:
            risks.append({
                "code": "truncated_milestone_data", "count": milestones_truncation["missing"],
                "message": (
                    f"Report covers only {milestones_truncation['fetched']} of "
                    f"{milestones_truncation['total_matching']} matching milestone(s); "
                    "per-project milestone counts may be incomplete."
                ),
            })
        if off_track:
            risks.append({"code": "off_track_projects", "count": off_track,
                          "message": f"{off_track} project(s) off track"})
        if total_overdue_ms:
            risks.append({"code": "overdue_milestones", "count": total_overdue_ms,
                          "message": f"{total_overdue_ms} milestone(s) overdue and unreached"})
        if past_end_projects:
            risks.append({"code": "past_end_projects", "count": past_end_projects,
                          "message": f"{past_end_projects} project(s) past their end date"})
        if divergent:
            risks.append({"code": "health_divergence", "count": divergent,
                          "message": f"{divergent} project(s) declared healthier than the data"})

        return build_report(
            "project_status_report",
            today,
            summary=summary,
            breakdown={"by_project": rows},
            highlights=highlights,
            risks=risks,
            extra={"manager": manager, "customer": customer, "project": project},
        )

    return safe(run)


@mcp.tool()
def standup_digest(
    project: str,
    sprint_id: int | None = None,
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
        sprint_id: Optional sprint ID to filter tasks by sprint.
        exclude_stages: Stage names to treat as closed. Defaults to
            ["Done", "Cancelled", "Delivered"].
        lookahead_days: Days ahead to include in UPCOMING (default 7).
        timezone_offset: UTC offset in hours for "today" (default 7 = Asia/Ho_Chi_Minh).
    """
    import json as _json
    from datetime import timedelta

    from .odoo_client import OdooConfigError, OdooError

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
        if sprint_id is not None:
            domain.append(("sprint_id", "=", sprint_id))
        tasks = client.search_read(
            "project.task",
            domain=domain,
            fields=["id", "name", "user_ids", "stage_id", "date_deadline", "priority"],
            limit=200,
            order="date_deadline",
        )

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
            dd = parse_deadline(t.get("date_deadline"))
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

        lines = [f"## 🗓️ Daily Standup — {project}", f"**{today_str}**", ""]

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

    except (OdooConfigError, OdooError) as exc:
        return _json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)


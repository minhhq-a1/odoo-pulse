# odoo_mcp/tools_workflows.py
"""Composed workflow tools: business questions answered in one call.

Each tool composes several reads/aggregates server-side and returns a
decision-ready report (the envelope from workflow_helpers.build_report).
Read-only; no new write surface.
"""

from __future__ import annotations

from datetime import timedelta

from .runtime import get_client, mcp, safe
from .workflow_helpers import build_report, parse_deadline, resolve_user_names, today_in_tz


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

        tasks = client.search_read(
            "project.task",
            domain=domain,
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

        highlights = [f"{pct_done}% done ({done}/{total})"]
        if due_today:
            highlights.append(f"{due_today} due today")
        if upcoming:
            highlights.append(f"{upcoming} due within {lookahead_days} days")

        risks: list[dict] = []
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

# odoo_pulse/services/projects/health.py
"""Derived project health and the project_status_report business logic.

Everything here is read-only and client-agnostic (real OdooClient or the
test FakeClient). `derive_project_health` is THE single source of truth for
derived health -- used by project_status_report, project_dashboard and
portfolio_health, so the artifact's two tabs can never show different
verdicts for the same project.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.dates import parse_when, today_in_tz
from ...common.paging import fetch_with_truncation
from ...common.reporting import build_report
from .queries import milestones_by_project, project_domain


def derive_project_health(
    project_row: dict,
    milestones: list[dict],
    today,
    cutoff,
    timezone_offset: int,
) -> dict:
    """Milestone/end-date health verdict for one project.

    THE single source of truth for derived health — used by
    project_status_report, project_dashboard and portfolio_health, so the
    artifact's two tabs can never show different verdicts for the same
    project. Rules: any overdue unreached milestone or a passed end date
    -> off_track; anything due within the cutoff -> at_risk; else
    on_track. Divergent means the PM declared a healthier status than the
    data supports.
    """
    native = project_row.get("last_update_status") or "to_define"
    total = len(milestones)
    reached = sum(1 for m in milestones if m.get("is_reached"))
    overdue = soon = 0
    next_milestone = None
    ordered = sorted(milestones,
                     key=lambda m: str(m.get("deadline") or "9999-99-99"))
    for m in ordered:
        if m.get("is_reached"):
            continue
        dd = parse_when(m.get("deadline"), timezone_offset)
        if dd is None:
            continue
        if next_milestone is None:
            next_milestone = {"name": m["name"], "deadline": m["deadline"]}
        if dd < today:
            overdue += 1
        elif dd <= cutoff:
            soon += 1
    end = parse_when(project_row.get("date"), timezone_offset)
    past_end = end is not None and end < today and native != "done"
    end_soon = end is not None and today <= end <= cutoff
    if overdue > 0 or past_end:
        derived = "off_track"
    elif soon > 0 or end_soon:
        derived = "at_risk"
    else:
        derived = "on_track"
    divergent = (
        (native in ("on_track", "on_hold") and derived == "off_track")
        or (native == "on_track" and derived == "at_risk"))
    return {"native_status": native, "derived_health": derived,
            "divergent": divergent, "reached": reached, "total": total,
            "overdue": overdue, "soon": soon,
            "next_milestone": next_milestone,
            "past_end": past_end, "end_soon": end_soon}


def build_project_status_report(
    client, *, manager=None, customer=None, project=None,
    include_on_hold=True, include_done=False,
    lookahead_days=7, timezone_offset=7,
) -> dict:
    domain = project_domain(
        project=project, manager=manager, customer=customer,
        include_on_hold=include_on_hold, include_done=include_done,
    )

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

    ms_by_project = milestones_by_project(milestones)

    rank = {"off_track": 0, "at_risk": 1, "on_track": 2}
    rows: list[dict] = []
    off_track = at_risk = on_track = 0
    total_overdue_ms = 0
    past_end_projects = 0
    divergent = 0

    for p in projects:
        ms = ms_by_project.get(p["id"], [])
        h = derive_project_health(p, ms, today, cutoff, timezone_offset)

        if h["derived_health"] == "off_track":
            off_track += 1
        elif h["derived_health"] == "at_risk":
            at_risk += 1
        else:
            on_track += 1

        total_overdue_ms += h["overdue"]
        if h["past_end"]:
            past_end_projects += 1
        if h["divergent"]:
            divergent += 1

        rows.append({
            "project_id": p["id"],
            "project": p["name"],
            "manager": p["user_id"][1] if p.get("user_id") else None,
            "customer": p["partner_id"][1] if p.get("partner_id") else None,
            "end_date": p.get("date") or None,
            "task_count": p.get("task_count", 0),
            "milestones": {"reached": h["reached"], "total": h["total"]},
            "overdue_milestones": h["overdue"],
            "next_milestone": h["next_milestone"],
            "native_status": h["native_status"],
            "derived_health": h["derived_health"],
            "divergent": h["divergent"],
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

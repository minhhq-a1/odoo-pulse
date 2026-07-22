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
from ...common.schema import optional_fields
from .budget import budget_by_project
from .finance import FALLBACK_WARNING, analytic_money
from .queries import (
    account_ids_by_project,
    milestones_by_project,
    project_domain,
)


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


def build_portfolio_health(
    client, *, manager=None, customer=None,
    include_on_hold=True, include_done=False,
    lookahead_days=7, timezone_offset=7,
) -> dict:
    """Portfolio overview: one row per project, joined by id server-side.

    Raw signals only — the client computes its own health score from
    user-configured thresholds. Composes the query, health, profitability
    and budget services so the two artifact tabs can never diverge on a
    project's verdict. Call order is fixed (projects -> milestones ->
    hours aggregate -> cost -> revenue -> budget) to keep the FakeClient
    per-model queue deterministic; milestone truncation is annotated as a
    risk rather than failing the whole report.
    """
    today = today_in_tz(timezone_offset)
    cutoff = today + timedelta(days=lookahead_days)

    domain = project_domain(
        manager=manager, customer=customer,
        include_on_hold=include_on_hold, include_done=include_done,
    )

    opt = optional_fields(client, "project.project",
                          ["allocated_hours", "account_id",
                           "analytic_account_id"])
    projects, truncation = fetch_with_truncation(
        client, "project.project", domain,
        fields=["id", "name", "user_id", "partner_id", "date",
                "task_count", "last_update_status", *opt],
        limit=200, order="name")

    ids = [p["id"] for p in projects]
    acct_by_project = account_ids_by_project(projects, opt)
    account_ids = sorted(set(acct_by_project.values()))
    has_alloc = "allocated_hours" in opt

    ms_by_project: dict[int, list] = {}
    hours_by_project: dict[int, float] = {}
    cost_by: dict[int, float] = {}
    rev_by: dict[int, float] = {}
    money = analytic_money(client, [])
    budgets: dict[int, float] = {}
    budgets_available = False
    milestones_truncation = None
    if ids:
        milestones, milestones_truncation = fetch_with_truncation(
            client, "project.milestone",
            [("project_id", "in", ids)],
            fields=["id", "name", "deadline", "is_reached",
                    "project_id"],
            limit=200, order="deadline")
        ms_by_project = milestones_by_project(milestones)
        hours_agg = client.aggregate_records(
            "account.analytic.line", group_by=["project_id"],
            measures=[("unit_amount", "sum")],
            domain=[("project_id", "in", ids)])
        for row in hours_agg.get("rows", []):
            m2o = row.get("project_id")
            if m2o:
                hours_by_project[m2o[0]] = (
                    row.get("unit_amount:sum") or 0.0)
        money = analytic_money(client, account_ids)
        cost_by, rev_by = money.cost_by_account, money.revenue_by_account
        budgets, budgets_available = budget_by_project(
            client, ids, acct_by_project)

    rows_out: list[dict] = []
    off_track = total_overdue = divergent = past_end = 0
    for p in projects:
        pid = p["id"]
        h = derive_project_health(
            p, ms_by_project.get(pid, []), today, cutoff,
            timezone_offset)
        acct_id = acct_by_project.get(pid)
        cost = cost_by.get(acct_id, 0.0) if acct_id is not None else 0.0
        revenue = (rev_by.get(acct_id, 0.0)
                   if acct_id is not None else 0.0)
        budget = budgets.get(pid) if budgets_available else None
        alloc = (p.get("allocated_hours") or 0.0) if has_alloc else 0.0
        hours = hours_by_project.get(pid, 0.0)

        if h["derived_health"] == "off_track":
            off_track += 1
        total_overdue += h["overdue"]
        if h["divergent"]:
            divergent += 1
        if h["past_end"]:
            past_end += 1

        rows_out.append({
            "project_id": pid,
            "project": p["name"],
            "manager": p["user_id"][1] if p.get("user_id") else None,
            "customer": (p["partner_id"][1]
                         if p.get("partner_id") else None),
            "end_date": p.get("date") or None,
            "task_count": p.get("task_count", 0),
            "milestones": {"reached": h["reached"],
                           "total": h["total"]},
            "overdue_milestones": h["overdue"],
            "next_milestone": h["next_milestone"],
            "native_status": h["native_status"],
            "derived_health": h["derived_health"],
            "divergent": h["divergent"],
            "revenue": round(revenue, 2),
            "cost": round(cost, 2),
            "margin": round(revenue - cost, 2),
            "budget": round(budget, 2) if budget is not None else None,
            "budget_burn_pct": (round(cost / budget * 100, 1)
                                if budget else None),
            "hours_burn_pct": (round(hours / alloc * 100, 1)
                               if alloc else None),
        })

    rank = {"off_track": 0, "at_risk": 1, "on_track": 2}
    rows_out.sort(key=lambda r: (rank[r["derived_health"]],
                                 -r["overdue_milestones"],
                                 r["project"]))

    risks: list[dict] = []
    if truncation:
        risks.append({
            "code": "truncated_data", "count": truncation["missing"],
            "message": (
                f"Report covers only {truncation['fetched']} of "
                f"{truncation['total_matching']} matching projects.")})
    if milestones_truncation:
        risks.append({
            "code": "truncated_milestone_data",
            "count": milestones_truncation["missing"],
            "message": (
                f"Report covers only {milestones_truncation['fetched']} "
                f"of {milestones_truncation['total_matching']} matching "
                "milestone(s); per-project milestone counts may be "
                "incomplete.")})
    if off_track:
        risks.append({"code": "off_track_projects", "count": off_track,
                      "message": f"{off_track} project(s) off track"})
    if total_overdue:
        risks.append({
            "code": "overdue_milestones", "count": total_overdue,
            "message": (f"{total_overdue} milestone(s) overdue and "
                        "unreached")})
    if past_end:
        risks.append({
            "code": "past_end_projects", "count": past_end,
            "message": f"{past_end} project(s) past their end date"})
    if divergent:
        risks.append({
            "code": "health_divergence", "count": divergent,
            "message": (f"{divergent} project(s) declared healthier "
                        "than the data")})
    if money.classification == "sign_fallback":
        risks.append({
            "code": "analytic_classification_fallback",
            "count": len(account_ids),
            "message": FALLBACK_WARNING,
        })

    return {"tool": "portfolio_health", "as_of": today.isoformat(),
            "filters": {"manager": manager, "customer": customer,
                        "include_on_hold": include_on_hold,
                        "include_done": include_done},
            "budgets_available": budgets_available,
            "projects": rows_out, "risks": risks}

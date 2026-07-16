# odoo_pulse/tools_project_detail.py
"""Project-detail tools backing the "Project Status" artifact.

One MCP call replaces the 10-30 paginated client-side calls the artifact
used to make (the direct cause of its MCP rate-limit errors). Output is
the spec's free-form schema, NOT the build_report envelope — intentional:
these tools feed a dashboard, not a reader. Read-only. Everything
computes on this server in Python; odoo-pulse has no SQL access.

Spec: docs/superpowers/specs/spec-odoo-pulse-project-status.md (Rev 2).
"""

from __future__ import annotations

from datetime import timedelta

from .odoo_client import OdooError
from .project_shared import (
    DEFAULT_CLOSED_STAGES,
    _PARENT_CANDIDATES,
    _PARENT_MODEL,
    _PRACTICAL_CANDIDATES,
    _budget_sources,
    analytic_money,
    derive_project_health,
    fetch_subtasks,
    paged_search_read,
    periods_domain,
    subtasks_by_month,
    sum_hours,
)
from .runtime import get_client, mcp, safe
from .workflow_helpers import optional_fields, parse_when, today_in_tz


@mcp.tool()
def project_subtask_hours(
    project_id: int,
    only_closed_stages: bool = False,
    closed_stage_names: list[str] | None = None,
    single_assignee_only: bool = False,
    group_by_month: bool = False,
    periods: list[dict] | None = None,
    timezone_offset: int = 7,
) -> str:
    """Total sub-task hours for one project, filtered server-side, in ONE call.

    Sums delivery/allocated/effective hours over the project's sub-tasks
    (project.task with parent_id set). Use this instead of paginating
    project.task through search_read — especially for the "exactly one
    assignee" condition, which Odoo domains cannot express.

    Args:
        project_id: project.project id (int, not name).
        only_closed_stages: Count only tasks whose stage name is in
            closed_stage_names (default False). Cancelled tasks DO count
            toward delivery hours (business decision 2026-07-15).
        closed_stage_names: Stage names treated as closed (default
            ["Done", "Cancelled", "Delivered"]).
        single_assignee_only: Count only tasks with exactly 1 user in
            user_ids (default False).
        group_by_month: Also bucket by local-time month of date_end;
            tasks without date_end are excluded from the buckets and
            summarised under "no_date_end" (default False).
        periods: Optional list of {"date_from": "YYYY-MM-DD",
            "date_to": "YYYY-MM-DD"} ranges applied to date_end,
            OR-combined (matching per-budget-period filtering, not a
            union). Empty/omitted = no date filter.
        timezone_offset: UTC offset for dates (default 7).
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        tasks, available, warnings = fetch_subtasks(
            client, project_id,
            only_closed_stages=only_closed_stages,
            closed_stage_names=closed_stage_names,
            single_assignee_only=single_assignee_only,
            periods=periods, timezone_offset=timezone_offset)
        report: dict = {
            "tool": "project_subtask_hours",
            "as_of": today.isoformat(),
            "project_id": project_id,
            "filters": {
                "only_closed_stages": only_closed_stages,
                "closed_stage_names": list(
                    closed_stage_names or DEFAULT_CLOSED_STAGES),
                "single_assignee_only": single_assignee_only,
                "periods": periods or [],
            },
        }
        if warnings:
            report["warnings"] = warnings
        report["totals"] = sum_hours(tasks, available)
        if group_by_month:
            by_month, no_date_end = subtasks_by_month(
                tasks, available, timezone_offset)
            report["by_month"] = by_month
            report["no_date_end"] = no_date_end
        return report

    return safe(run)


def _acct_id_of(project_row: dict, opt: list[str]) -> int | None:
    field = next((f for f in ("account_id", "analytic_account_id")
                  if f in opt), None)
    m2o = project_row.get(field) if field else None
    return m2o[0] if m2o else None


def _weekly_logged(client, project_id: int, today) -> list[dict]:
    """Hours per ISO week (Monday week_start) over the last 84 days.

    Bucketing happens here in Python instead of read_group's date:week —
    read_group returns localized week labels that vary by lang/version,
    while a raw date field is stable. The current partial week is
    included; the client decides how to render it.
    """
    since = today - timedelta(days=84)
    lines = paged_search_read(
        client, "account.analytic.line",
        [("project_id", "=", project_id), ("date", ">=", since.isoformat())],
        fields=["date", "unit_amount"])
    buckets: dict = {}
    for ln in lines:
        day = parse_when(ln.get("date"))
        if day is None:
            continue
        monday = day - timedelta(days=day.weekday())
        buckets[monday] = buckets.get(monday, 0.0) + (ln.get("unit_amount")
                                                      or 0.0)
    return [{"week_start": d.isoformat(), "hours": round(h, 2)}
            for d, h in sorted(buckets.items())]


def _core_section(client, project_id: int, timezone_offset: int,
                  lookahead_days: int) -> dict:
    today = today_in_tz(timezone_offset)
    cutoff = today + timedelta(days=lookahead_days)
    opt = optional_fields(client, "project.project",
                          ["delivery_hours", "account_id",
                           "analytic_account_id"])
    warnings = ([] if "delivery_hours" in opt else
                ["field delivery_hours does not exist on project.project"])
    rows = client.search_read(
        "project.project", domain=[("id", "=", project_id)],
        fields=["id", "name", "user_id", "partner_id", "date",
                "task_count", "last_update_status", *opt],
        limit=1)
    if not rows:
        raise OdooError(f"No project.project with id {project_id}")
    p = rows[0]

    ms_opt = optional_fields(client, "project.milestone",
                             ["revised_date", "actual_date"])
    milestones = client.search_read(
        "project.milestone", domain=[("project_id", "=", project_id)],
        fields=["id", "name", "deadline", "is_reached", *ms_opt],
        limit=200, order="deadline")
    h = derive_project_health(p, milestones, today, cutoff,
                              timezone_offset)

    acct_id = _acct_id_of(p, opt)
    cost_by, rev_by = analytic_money(
        client, [acct_id] if acct_id is not None else [])
    cost = cost_by.get(acct_id, 0.0) if acct_id is not None else 0.0
    revenue = rev_by.get(acct_id, 0.0) if acct_id is not None else 0.0

    return {
        "project": {
            "id": p["id"], "name": p["name"],
            "manager": p["user_id"][1] if p.get("user_id") else None,
            "customer": p["partner_id"][1] if p.get("partner_id") else None,
            "end_date": p.get("date") or None,
            "task_count": p.get("task_count", 0),
            "native_status": h["native_status"],
            "derived_health": h["derived_health"],
            "divergent": h["divergent"],
            "delivery_hours": (p.get("delivery_hours")
                               if "delivery_hours" in opt else None),
        },
        "milestones": {
            "reached": h["reached"], "total": h["total"],
            "overdue": h["overdue"],
            "next_unreached": h["next_milestone"],
            "list": [{
                "name": m["name"],
                "deadline": m.get("deadline") or None,
                "revised_date": (m.get("revised_date") or None
                                 if "revised_date" in ms_opt else None),
                "actual_date": (m.get("actual_date") or None
                                if "actual_date" in ms_opt else None),
                "is_reached": bool(m.get("is_reached")),
            } for m in milestones],
        },
        "finance": {
            "revenue": round(revenue, 2),
            "cost_all_time": round(cost, 2),
            "margin": round(revenue - cost, 2),
        },
        "weekly_logged": _weekly_logged(client, project_id, today),
        "warnings": warnings,
    }


def _hours_section(client, project_id: int, only_closed_stages: bool,
                   closed_stage_names: list[str] | None,
                   single_assignee_only: bool,
                   timezone_offset: int) -> dict:
    tasks, available, warnings = fetch_subtasks(
        client, project_id, only_closed_stages=only_closed_stages,
        closed_stage_names=closed_stage_names,
        single_assignee_only=single_assignee_only,
        timezone_offset=timezone_offset)
    totals = sum_hours(tasks, available)

    def leaderboard(group_field: str, id_key: str, label_key: str):
        agg = client.aggregate_records(
            "account.analytic.line", group_by=[group_field],
            measures=[("unit_amount", "sum")],
            domain=[("project_id", "=", project_id)],
            limit=50, order="unit_amount:sum desc")
        return [{id_key: row[group_field][0],
                 label_key: row[group_field][1],
                 "hours": round(row.get("unit_amount:sum") or 0.0, 2)}
                for row in agg.get("rows", []) if row.get(group_field)]

    return {
        "hours": {
            "subtask_delivery": totals["delivery_hours"],
            "subtask_allocated": totals["allocated_hours"],
            "subtask_effective": totals["effective_hours"],
            "by_employee": leaderboard("employee_id", "employee_id",
                                       "employee"),
            "by_task": leaderboard("task_id", "task_id", "task"),
        },
        "warnings": warnings,
    }


def _budget_context(client, project_id: int) -> dict:
    """One shared fetch of budget lines + parent budgets for a project.

    Abstracts crossovered.budget.lines vs budget.line exactly like
    project_budget does (same _budget_sources helper — spec rule #7).
    """
    opt = optional_fields(client, "project.project",
                          ["account_id", "analytic_account_id"])
    rows = client.search_read(
        "project.project", domain=[("id", "=", project_id)],
        fields=["id", *opt], limit=1)
    if not rows:
        raise OdooError(f"No project.project with id {project_id}")
    acct_id = _acct_id_of(rows[0], opt)
    account_ids = [acct_id] if acct_id is not None else []

    for model, link, acct, amount, extra_domain in _budget_sources(
            client, account_ids):
        line_opt = optional_fields(client, model, [
            *_PRACTICAL_CANDIDATES, *_PARENT_CANDIDATES,
            "date_from", "date_to"])
        fields = ["id", amount, *line_opt]
        match = ((link, "=", project_id) if link
                 else (acct, "in", account_ids))
        try:
            lines = paged_search_read(client, model,
                                      [match, *extra_domain],
                                      fields=fields)
        except OdooError:
            continue
        practical_field = next(
            (f for f in _PRACTICAL_CANDIDATES if f in line_opt), None)
        parent_field = next(
            (f for f in _PARENT_CANDIDATES if f in line_opt), None)
        budgets: list[dict] = []
        if parent_field and parent_field in _PARENT_MODEL:
            parent_model = _PARENT_MODEL[parent_field]
            pids = sorted({ln[parent_field][0] for ln in lines
                           if ln.get(parent_field)})
            if pids:
                popt = optional_fields(
                    client, parent_model, ["date_from", "date_to", "state"])
                parents = client.search_read(
                    parent_model, domain=[("id", "in", pids)],
                    fields=["id", "name", *popt], limit=len(pids))
                budgets = [{"id": b["id"], "name": b["name"],
                            "date_from": b.get("date_from") or None,
                            "date_to": b.get("date_to") or None,
                            "state": b.get("state") or None}
                           for b in parents]
        return {"budgets": budgets, "lines": lines,
                "amount_field": amount,
                "practical_field": practical_field,
                "parent_field": parent_field, "available": True}
    return {"budgets": [], "lines": [], "amount_field": None,
            "practical_field": None, "parent_field": None,
            "available": False}


def _selected(ctx: dict, budget_ids: list[int] | None
              ) -> tuple[list[int], list[dict]]:
    """(selected budget ids, their periods). None = all budgets of the
    project; [] = none selected (the two states are deliberately distinct
    — spec Rev 2; both branches are test-locked)."""
    if budget_ids is None:
        selected = [b["id"] for b in ctx["budgets"]]
    else:
        known = {b["id"] for b in ctx["budgets"]}
        selected = [bid for bid in budget_ids if bid in known]
    chosen = [b for b in ctx["budgets"] if b["id"] in set(selected)]
    periods = [{"date_from": b["date_from"], "date_to": b["date_to"]}
               for b in chosen if b["date_from"] or b["date_to"]]
    return selected, periods


def _budget_detail_section(client, project_id: int, ctx: dict,
                           budget_ids: list[int] | None,
                           timezone_offset: int) -> dict:
    selected, periods = _selected(ctx, budget_ids)
    sel = set(selected)
    parent_field = ctx["parent_field"]
    amount_field = ctx["amount_field"]
    practical_field = ctx["practical_field"]
    lines = [ln for ln in ctx["lines"]
             if parent_field and ln.get(parent_field)
             and ln[parent_field][0] in sel]
    planned = (round(sum(abs(ln.get(amount_field) or 0.0)
                         for ln in lines), 2)
               if amount_field else None)
    practical = (round(sum(abs(ln.get(practical_field) or 0.0)
                           for ln in lines), 2)
                 if practical_field else None)
    chosen = [b for b in ctx["budgets"] if b["id"] in sel]
    froms = sorted(b["date_from"] for b in chosen if b["date_from"])
    tos = sorted(b["date_to"] for b in chosen if b["date_to"])

    # valid_cost rule: ONLY task-linked timesheet lines, inside the OR'd
    # budget periods (account.analytic.line.date is a plain date field).
    domain = [("project_id", "=", project_id), ("task_id", "!=", False),
              *periods_domain("date", periods, timezone_offset,
                              as_datetime=False)]
    rows = paged_search_read(
        client, "account.analytic.line", domain,
        fields=["date", "amount", "unit_amount", "employee_id", "task_id"])

    def bucket(rows_subset, key_fn):
        out: dict = {}
        for r in rows_subset:
            cost_hours = out.setdefault(key_fn(r), [0.0, 0.0])
            cost_hours[0] -= r.get("amount") or 0.0     # flip sign once
            cost_hours[1] += r.get("unit_amount") or 0.0
        return out

    months = bucket(rows, lambda r: str(r.get("date") or "")[:7])
    emps = bucket([r for r in rows if r.get("employee_id")],
                  lambda r: (r["employee_id"][0], r["employee_id"][1]))
    tasks = bucket([r for r in rows if r.get("task_id")],
                   lambda r: (r["task_id"][0], r["task_id"][1]))
    return {
        "selected_budget_ids": selected,
        "planned": planned, "practical": practical,
        "date_from": froms[0] if froms else None,
        "date_to": tos[-1] if tos else None,
        "valid_cost": round(-sum(r.get("amount") or 0.0 for r in rows), 2),
        "valid_hours": round(sum(r.get("unit_amount") or 0.0
                                 for r in rows), 2),
        "by_month": [{"month": m, "cost": round(c, 2),
                      "hours": round(h, 2)}
                     for m, (c, h) in sorted(months.items()) if m],
        "by_employee": [{"employee_id": k[0], "employee": k[1],
                         "cost": round(c, 2), "hours": round(h, 2)}
                        for k, (c, h) in sorted(emps.items(),
                                                key=lambda kv: -kv[1][0])],
        "by_task": [{"task_id": k[0], "task": k[1],
                     "cost": round(c, 2), "hours": round(h, 2)}
                    for k, (c, h) in sorted(tasks.items(),
                                            key=lambda kv: -kv[1][0])],
    }


def _delivery_monthly_section(client, project_id: int,
                              only_closed_stages: bool,
                              closed_stage_names: list[str] | None,
                              single_assignee_only: bool,
                              periods: list[dict],
                              timezone_offset: int
                              ) -> tuple[list[dict], list[str]]:
    tasks, available, warnings = fetch_subtasks(
        client, project_id, only_closed_stages=only_closed_stages,
        closed_stage_names=closed_stage_names,
        single_assignee_only=single_assignee_only,
        periods=periods, timezone_offset=timezone_offset)
    by_month, _no_date_end = subtasks_by_month(tasks, available,
                                               timezone_offset)
    return ([{"month": r["month"], "delivery_hours": r["delivery_hours"]}
             for r in by_month], warnings)


_SECTIONS = ("core", "hours", "budgets", "budget_detail",
             "delivery_monthly")


@mcp.tool()
def project_dashboard(
    project_id: int,
    only_closed_stages: bool = False,
    closed_stage_names: list[str] | None = None,
    single_assignee_only: bool = False,
    budget_ids: list[int] | None = None,
    include: list[str] | None = None,
    lookahead_days: int = 7,
    timezone_offset: int = 7,
) -> str:
    """Everything the project-detail page needs, in one call.

    Replaces ~12 separate calls (status, profitability, milestones,
    weekly hours, budgets, budget lines, cost breakdowns, delivery by
    month). Use `include` to re-fetch only what changed: checkbox toggles
    -> ["hours", "delivery_monthly"]; budget chip changes ->
    ["budget_detail", "delivery_monthly"].

    Sections fail soft: a broken section lands in "errors" while the
    rest return.

    Args:
        project_id: project.project id.
        only_closed_stages / closed_stage_names / single_assignee_only:
            sub-task filters, as in project_subtask_hours; they shape the
            "hours" and "delivery_monthly" sections.
        budget_ids: crossovered.budget / budget.analytic ids to select.
            OMIT (null) for ALL budgets of the project; pass [] for NO
            selection (budget_detail then shows all-time cost only).
            These two states are different on purpose — do not send []
            to mean "all".
        include: Subset of ["core", "hours", "budgets", "budget_detail",
            "delivery_monthly"]; omitted = all. "core" covers project,
            milestones, finance and weekly_logged.
        lookahead_days: "due soon" window for derived health (default 7).
        timezone_offset: UTC offset for dates (default 7).
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        wanted = list(_SECTIONS) if include is None else list(include)
        unknown = [s for s in wanted if s not in _SECTIONS]
        if unknown:
            raise OdooError(
                f"Unknown include section(s): {', '.join(unknown)}. "
                f"Valid: {', '.join(_SECTIONS)}")

        report: dict = {
            "tool": "project_dashboard",
            "as_of": today.isoformat(),
            "project_id": project_id,
            "filters": {
                "only_closed_stages": only_closed_stages,
                "closed_stage_names": list(
                    closed_stage_names or DEFAULT_CLOSED_STAGES),
                "single_assignee_only": single_assignee_only,
                "budget_ids": budget_ids,
                "include": wanted,
            },
        }
        errors: dict[str, str] = {}
        warnings: list[str] = []

        def attempt(name: str, fn):
            # Soft-fail per spec rule #6; sections run sequentially so
            # the FakeClient's per-model queues stay deterministic.
            try:
                return fn()
            except Exception as exc:
                errors[name] = str(exc)
                return None

        if "core" in wanted:
            core = attempt("core", lambda: _core_section(
                client, project_id, timezone_offset, lookahead_days))
            if core is not None:
                report["project"] = core["project"]
                report["milestones"] = core["milestones"]
                report["finance"] = core["finance"]
                report["weekly_logged"] = core["weekly_logged"]
                warnings += core["warnings"]

        if "hours" in wanted:
            hours = attempt("hours", lambda: _hours_section(
                client, project_id, only_closed_stages,
                closed_stage_names, single_assignee_only,
                timezone_offset))
            if hours is not None:
                report["hours"] = hours["hours"]
                warnings += hours["warnings"]

        budget_sections = [s for s in
                           ("budgets", "budget_detail", "delivery_monthly")
                           if s in wanted]
        ctx = None
        if budget_sections:
            ctx = attempt(budget_sections[0],
                          lambda: _budget_context(client, project_id))
        if ctx is not None:
            if "budgets" in wanted:
                report["budgets"] = ctx["budgets"]
            if "budget_detail" in wanted:
                detail = attempt("budget_detail",
                                 lambda: _budget_detail_section(
                                     client, project_id, ctx,
                                     budget_ids, timezone_offset))
                if detail is not None:
                    report["budget_detail"] = detail
            if "delivery_monthly" in wanted:
                _ids, periods = _selected(ctx, budget_ids)

                def deliver():
                    rows, warns = _delivery_monthly_section(
                        client, project_id, only_closed_stages,
                        closed_stage_names, single_assignee_only,
                        periods, timezone_offset)
                    warnings.extend(warns)
                    return rows

                rows = attempt("delivery_monthly", deliver)
                if rows is not None:
                    report["delivery_monthly"] = rows

        risks: list[dict] = []
        ms = report.get("milestones")
        if ms and ms["overdue"]:
            risks.append({
                "code": "overdue_milestones", "count": ms["overdue"],
                "message": f"{ms['overdue']} milestone(s) overdue and "
                           "unreached"})
        proj = report.get("project")
        if proj and proj["divergent"]:
            risks.append({
                "code": "health_divergence", "count": 1,
                "message": "declared status is healthier than the "
                           "milestone/end-date data supports"})
        report["risks"] = risks
        deduped = sorted(set(warnings))
        if deduped:
            report["warnings"] = deduped
        if errors:
            report["errors"] = errors
        return report

    return safe(run)

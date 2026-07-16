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
    _budget_by_project,
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
from .workflow_helpers import (
    fetch_with_truncation,
    optional_fields,
    parse_when,
    today_in_tz,
)


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
              ) -> tuple[list[int], list[dict], list[int]]:
    """(selected budget ids, their periods, unknown ids). None = all budgets
    of the project; [] = none selected (the two states are deliberately
    distinct — spec Rev 2; both branches are test-locked). unknown_ids are
    entries in budget_ids that match no budget of this project — a stale or
    typo'd id would otherwise look identical to "select none"."""
    if budget_ids is None:
        selected = [b["id"] for b in ctx["budgets"]]
        unknown: list[int] = []
    else:
        known = {b["id"] for b in ctx["budgets"]}
        selected = [bid for bid in budget_ids if bid in known]
        unknown = [bid for bid in budget_ids if bid not in known]
    chosen = [b for b in ctx["budgets"] if b["id"] in set(selected)]
    periods = [{"date_from": b["date_from"], "date_to": b["date_to"]}
               for b in chosen if b["date_from"] or b["date_to"]]
    return selected, periods, unknown


def _budget_detail_section(client, project_id: int, ctx: dict,
                           budget_ids: list[int] | None,
                           timezone_offset: int) -> dict:
    selected, periods, unknown_budget_ids = _selected(ctx, budget_ids)
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
    detail = {
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
    if unknown_budget_ids:
        detail["unknown_budget_ids"] = unknown_budget_ids
    return detail


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
            except OdooError as exc:
                errors[name] = str(exc)
                return None
            except Exception as exc:
                # Not an OdooError -> a programming bug, not an
                # instance-config/data issue. Prefix so it isn't mistaken
                # for the latter (e.g. "field X does not exist").
                errors[name] = f"internal error: {type(exc).__name__}: {exc}"
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
                    stale = detail.get("unknown_budget_ids")
                    if stale:
                        warnings.append(
                            f"budget_ids {stale} match no budget of "
                            f"project {project_id}")
            if "delivery_monthly" in wanted:
                _ids, periods, _unknown = _selected(ctx, budget_ids)

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


@mcp.tool()
def portfolio_health(
    manager: str | None = None,
    customer: str | None = None,
    include_on_hold: bool = True,
    include_done: bool = False,
    lookahead_days: int = 7,
    timezone_offset: int = 7,
) -> str:
    """Portfolio overview: one row per project, joined by id server-side.

    Replaces the project_status_report + project_profitability pair the
    overview tab used to call and join BY NAME in JS (which broke on
    duplicate project names). Returns raw signals only — the client
    computes its own health score from user-configured thresholds.

    Args:
        manager: Optional project-manager filter (user_id.name ilike).
        customer: Optional customer filter (partner_id.name ilike).
        include_on_hold: Keep on_hold projects (default True).
        include_done: Keep done projects (default False).
        lookahead_days: "due soon" window for derived health (default 7).
        timezone_offset: UTC offset for dates (default 7).
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        cutoff = today + timedelta(days=lookahead_days)

        domain: list = [("active", "=", True)]
        if manager:
            domain.append(("user_id.name", "ilike", manager))
        if customer:
            domain.append(("partner_id.name", "ilike", customer))
        if not include_done:
            domain.append(("last_update_status", "!=", "done"))
        if not include_on_hold:
            domain.append(("last_update_status", "!=", "on_hold"))

        opt = optional_fields(client, "project.project",
                              ["allocated_hours", "account_id",
                               "analytic_account_id"])
        projects, truncation = fetch_with_truncation(
            client, "project.project", domain,
            fields=["id", "name", "user_id", "partner_id", "date",
                    "task_count", "last_update_status", *opt],
            limit=200, order="name")

        ids = [p["id"] for p in projects]
        acct_field = next((f for f in ("account_id",
                                       "analytic_account_id")
                           if f in opt), None)
        acct_by_project = {p["id"]: p[acct_field][0] for p in projects
                           if acct_field and p.get(acct_field)}
        account_ids = sorted(set(acct_by_project.values()))
        has_alloc = "allocated_hours" in opt

        ms_by_project: dict[int, list] = {}
        hours_by_project: dict[int, float] = {}
        cost_by: dict[int, float] = {}
        rev_by: dict[int, float] = {}
        budgets: dict[int, float] = {}
        budgets_available = False
        if ids:
            milestones = paged_search_read(
                client, "project.milestone",
                [("project_id", "in", ids)],
                fields=["id", "name", "deadline", "is_reached",
                        "project_id"],
                order="deadline")
            for m in milestones:
                pid = m["project_id"][0] if m.get("project_id") else None
                if pid is not None:
                    ms_by_project.setdefault(pid, []).append(m)
            hours_agg = client.aggregate_records(
                "account.analytic.line", group_by=["project_id"],
                measures=[("unit_amount", "sum")],
                domain=[("project_id", "in", ids)])
            for row in hours_agg.get("rows", []):
                m2o = row.get("project_id")
                if m2o:
                    hours_by_project[m2o[0]] = (
                        row.get("unit_amount:sum") or 0.0)
            cost_by, rev_by = analytic_money(client, account_ids)
            budgets, budgets_available = _budget_by_project(
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

        return {"tool": "portfolio_health", "as_of": today.isoformat(),
                "filters": {"manager": manager, "customer": customer,
                            "include_on_hold": include_on_hold,
                            "include_done": include_done},
                "budgets_available": budgets_available,
                "projects": rows_out, "risks": risks}

    return safe(run)

# odoo_pulse/services/projects/dashboard.py
"""Project dashboard orchestration for the "Project Status" artifact.

`build_project_dashboard` replaces ~12 separate client-side calls with one
server-side fan-out: core (project/milestones/finance/weekly hours), hours,
budgets, budget detail and delivery-by-month. Read-only and client-agnostic
(real OdooClient or the test FakeClient). Sections fail soft -- a broken
section lands in "errors" while the rest return.

The section builders here compose the single-source-of-truth primitives in
health/subtasks/budget/profitability/queries so the dashboard can never
disagree with project_status_report, project_budget, project_profitability
or portfolio_health on the same figures.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.dates import parse_when, today_in_tz
from ...common.paging import paged_search_read
from ...common.schema import optional_fields
from ...core.errors import OdooError
from .budget import (
    build_budget_context,
    build_budget_detail,
    select_budgets,
)
from .health import derive_project_health
from .profitability import analytic_money
from .queries import account_id_of
from .subtasks import (
    DEFAULT_CLOSED_STAGES,
    fetch_subtasks,
    filter_subtasks_by_periods,
    subtasks_by_month,
    sum_hours,
)


def weekly_logged(client, project_id: int, today) -> list[dict]:
    """Hours per ISO week (Monday week_start) over the last 84 days.

    Bucketing happens here in Python instead of read_group's date:week --
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


def error_message(exc: Exception) -> str:
    """OdooError -> its message as-is; anything else -> a prefixed, classed
    message so a programming bug isn't mistaken for a data/instance issue
    (e.g. "field X does not exist")."""
    if isinstance(exc, OdooError):
        return str(exc)
    return f"internal error: {type(exc).__name__}: {exc}"


def build_core_section(client, project_id: int, timezone_offset: int,
                       lookahead_days: int) -> dict:
    """project + milestones + finance + weekly_logged for one project.

    project/milestones always return together if the project itself exists
    (a fault fetching either one is a genuine failure of the whole section,
    same as the project not existing). finance and weekly_logged are each
    their own try/except: a fault in one (e.g. a missing module) must not
    take out the other or the project/milestones data already computed.
    """
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

    result: dict = {
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
        "warnings": warnings,
        # internal only -- never copied into the tool's output; lets
        # build_project_dashboard hand this row to build_budget_context
        # instead of it re-fetching project.project (finding #8).
        "_raw_project_row": p,
    }

    section_errors: dict[str, str] = {}
    try:
        acct_id = account_id_of(p, opt)
        cost_by, rev_by = analytic_money(
            client, [acct_id] if acct_id is not None else [])
        cost = cost_by.get(acct_id, 0.0) if acct_id is not None else 0.0
        revenue = rev_by.get(acct_id, 0.0) if acct_id is not None else 0.0
        result["finance"] = {
            "revenue": round(revenue, 2),
            "cost_all_time": round(cost, 2),
            "margin": round(revenue - cost, 2),
        }
    except Exception as exc:
        section_errors["finance"] = error_message(exc)

    try:
        result["weekly_logged"] = weekly_logged(client, project_id, today)
    except Exception as exc:
        section_errors["weekly_logged"] = error_message(exc)

    if section_errors:
        result["errors"] = section_errors
    return result


def build_hours_section(client, project_id: int, only_closed_stages: bool,
                        closed_stage_names: list[str] | None,
                        single_assignee_only: bool,
                        timezone_offset: int,
                        prefetched: tuple[list[dict], list[str], list[str]]
                        | None = None) -> dict:
    """prefetched, when given, is the (tasks, available, warnings) tuple
    fetch_subtasks would otherwise compute itself -- lets
    build_project_dashboard fetch sub-tasks once and hand the same result to
    both this section and build_delivery_monthly instead of two separate
    RPCs for the same unfiltered set."""
    if prefetched is not None:
        tasks, available, warnings = prefetched
    else:
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


def build_delivery_monthly(client, project_id: int,
                           only_closed_stages: bool,
                           closed_stage_names: list[str] | None,
                           single_assignee_only: bool,
                           periods: list[dict],
                           timezone_offset: int,
                           prefetched: tuple[list[dict], list[str], list[str]]
                           | None = None
                           ) -> tuple[list[dict], list[str]]:
    """periods are applied in Python via filter_subtasks_by_periods, not as
    a fetch_subtasks(periods=...) domain -- so this section can share the
    same unfiltered prefetch as build_hours_section instead of re-fetching
    with its own date_end domain (fetch_subtasks' own periods= kwarg stays
    as the server-side path for the public project_subtask_hours tool, which
    is not touched here)."""
    if prefetched is not None:
        tasks, available, warnings = prefetched
    else:
        tasks, available, warnings = fetch_subtasks(
            client, project_id, only_closed_stages=only_closed_stages,
            closed_stage_names=closed_stage_names,
            single_assignee_only=single_assignee_only,
            timezone_offset=timezone_offset)
    tasks = filter_subtasks_by_periods(tasks, periods, timezone_offset)
    by_month, _no_date_end = subtasks_by_month(tasks, available,
                                               timezone_offset)
    return ([{"month": r["month"], "delivery_hours": r["delivery_hours"]}
             for r in by_month], warnings)


SECTIONS = ("core", "hours", "budgets", "budget_detail",
            "delivery_monthly")


def build_project_dashboard(
    client, *, project_id, only_closed_stages=False,
    closed_stage_names=None, single_assignee_only=False,
    budget_ids=None, include=None, lookahead_days=7,
    timezone_offset=7,
) -> dict:
    """Everything the project-detail page needs, computed server-side.

    Sections run sequentially (never parallelized) so the FakeClient's
    per-model queues stay deterministic, and each fails soft into "errors"
    while the rest return.
    """
    today = today_in_tz(timezone_offset)
    wanted = list(SECTIONS) if include is None else list(include)
    unknown = [s for s in wanted if s not in SECTIONS]
    if unknown:
        raise OdooError(
            f"Unknown include section(s): {', '.join(unknown)}. "
            f"Valid: {', '.join(SECTIONS)}")

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
            errors[name] = error_message(exc)
            return None

    core = None
    if "core" in wanted:
        core = attempt("core", lambda: build_core_section(
            client, project_id, timezone_offset, lookahead_days))
        if core is not None:
            report["project"] = core["project"]
            report["milestones"] = core["milestones"]
            if "finance" in core:
                report["finance"] = core["finance"]
            if "weekly_logged" in core:
                report["weekly_logged"] = core["weekly_logged"]
            warnings += core["warnings"]
            errors.update(core.get("errors", {}))

    # hours and delivery_monthly both start from the SAME unfiltered
    # sub-task fetch (delivery_monthly applies its period filter in
    # Python — see build_delivery_monthly), so it's fetched once
    # here and handed to both instead of two identical RPCs. A fault
    # here is recorded under BOTH names since neither section can run
    # without it (mirrors attempt()'s soft-fail, just fanned out).
    shared_tasks = None
    if "hours" in wanted or "delivery_monthly" in wanted:
        try:
            shared_tasks = fetch_subtasks(
                client, project_id,
                only_closed_stages=only_closed_stages,
                closed_stage_names=closed_stage_names,
                single_assignee_only=single_assignee_only,
                timezone_offset=timezone_offset)
        except Exception as exc:
            msg = error_message(exc)
            if "hours" in wanted:
                errors["hours"] = msg
            if "delivery_monthly" in wanted:
                errors["delivery_monthly"] = msg

    if "hours" in wanted and shared_tasks is not None:
        hours = attempt("hours", lambda: build_hours_section(
            client, project_id, only_closed_stages,
            closed_stage_names, single_assignee_only,
            timezone_offset, prefetched=shared_tasks))
        if hours is not None:
            report["hours"] = hours["hours"]
            warnings += hours["warnings"]

    budget_sections = [s for s in
                       ("budgets", "budget_detail", "delivery_monthly")
                       if s in wanted]
    ctx = None
    if budget_sections:
        # Reuse core's already-fetched project.project row instead of
        # build_budget_context fetching it again (finding #8); None when
        # core wasn't requested or failed, so build_budget_context just
        # falls back to its own self-sufficient fetch.
        core_row = core.get("_raw_project_row") if core else None
        try:
            ctx = build_budget_context(client, project_id, core_row)
        except Exception as exc:
            # Every budget section needs this context, so a failure is
            # recorded under ALL requested ones — a requested section
            # must never vanish from both the report and errors (same
            # fan-out as the shared sub-task fetch above).
            msg = error_message(exc)
            for name in budget_sections:
                errors[name] = msg
    if ctx is not None:
        # Unknown budget_ids matter regardless of which budget section
        # was requested -- a stale/typo'd id should not silently look
        # like "select none" just because budget_detail wasn't in
        # `include` this call (finding #1's guarantee must hold for
        # every budget_ids-consuming section, not only budget_detail).
        _sel_ids, _sel_periods, unknown_ids = select_budgets(ctx, budget_ids)
        if unknown_ids:
            warnings.append(
                f"budget_ids {unknown_ids} match no budget of "
                f"project {project_id}")
        if "budgets" in wanted:
            report["budgets"] = ctx["budgets"]
        if "budget_detail" in wanted:
            detail = attempt("budget_detail",
                             lambda: build_budget_detail(
                                 client, project_id, ctx,
                                 budget_ids, timezone_offset))
            if detail is not None:
                report["budget_detail"] = detail
        if "delivery_monthly" in wanted and shared_tasks is not None:
            _ids, periods, _unknown = select_budgets(ctx, budget_ids)

            def deliver():
                rows, warns = build_delivery_monthly(
                    client, project_id, only_closed_stages,
                    closed_stage_names, single_assignee_only,
                    periods, timezone_offset, prefetched=shared_tasks)
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

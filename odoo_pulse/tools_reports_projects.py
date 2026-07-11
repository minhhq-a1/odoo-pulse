# odoo_pulse/tools_reports_projects.py
"""Project profitability report: delivery hours, money and budget burn.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based burn verdict. Read-only.

Caveats for callers:
- Analytic amounts are in each company's currency (mixed_companies risk).
- Two projects sharing one analytic account each get the full account's
  cost/revenue/budget (accepted double-count; splitting would be arbitrary).
- On Odoo 18+ the budget state filter is skipped (state lives on the parent
  budget.analytic and drifts across minor versions); revenue-type budgets
  ARE excluded via a dotted budget_type domain — when that field is missing
  on the instance the aggregate faults and budgets degrade to unavailable.
"""

from __future__ import annotations

from .odoo_client import OdooError
from .runtime import get_client, mcp, safe
from .workflow_helpers import (
    build_report,
    distinct_companies,
    ensure_field,
    fetch_with_truncation,
    gather_strict,
    optional_fields,
    parse_when,
    today_in_tz,
)

_TIMESHEET_HINT = ("Timesheets require the hr_timesheet app; install it to "
                   "report delivery hours.")

# (model, analytic-account field candidates, planned-amount field candidates,
#  extra domain). Order below fits Odoo 18+; it is reversed for <= 17.
_BUDGET_CANDIDATES = [
    ("budget.line",
     ["account_id", "analytic_account_id"],
     ["budget_amount", "planned_amount"],
     # != "revenue" keeps expense AND mixed ("both") budgets; a faulting
     # dotted field drops to the next candidate via the aggregate try/except.
     [("budget_analytic_id.budget_type", "!=", "revenue")]),
    ("crossovered.budget.lines",
     ["analytic_account_id"],
     ["planned_amount"],
     [("crossovered_budget_id.state", "in", ["confirm", "validate", "done"])]),
]


def _validate_date(value: str | None, param: str) -> str | None:
    """YYYY-MM-DD passthrough; garbage -> clean OdooError (parse_when raises
    ValueError, which safe() would render as an ugly 'internal error:')."""
    if not value:
        return None
    try:
        parse_when(value)
    except ValueError:
        raise OdooError(f"Invalid {param} {value!r}: expected YYYY-MM-DD")
    return str(value)[:10]


def _verdict(
    hours_burn: float | None,
    budget_burn: float | None,
    at_risk_pct: float,
    off_track_pct: float,
) -> tuple[str, float | None]:
    """(verdict, worst_burn). Nothing to burn against -> on_track, None
    (the no_allocation risk surfaces that case instead)."""
    burns = [b for b in (hours_burn, budget_burn) if b is not None]
    if not burns:
        return "on_track", None
    worst = max(burns)
    if worst >= off_track_pct:
        return "off_track", worst
    if worst >= at_risk_pct:
        return "at_risk", worst
    return "on_track", worst


def _budget_by_account(
    client, account_ids: list[int]
) -> tuple[dict[int, float], bool]:
    """Planned budget (absolute) per analytic account id + budgets_available.

    The FIRST call against each candidate model is a real RPC
    (search_count) inside try/except OdooError — fields_get is NOT a
    reliable absence probe (see the design doc: the FakeClient returns a
    default schema for unknown models, and the degradation path must be
    identical under test and in production). Model absent or candidate
    fields unresolvable -> next candidate; none usable -> ({}, False).
    """
    if not account_ids:
        return {}, False
    candidates = list(_BUDGET_CANDIDATES)
    major = client.major_version()
    if major is not None and major <= 17:
        candidates.reverse()
    for model, acct_candidates, amount_candidates, extra_domain in candidates:
        try:
            client.search_count(model, [])
        except OdooError:
            continue
        acct_fields = optional_fields(client, model, acct_candidates)
        amount_fields = optional_fields(client, model, amount_candidates)
        if not acct_fields or not amount_fields:
            continue
        acct_field, amount_field = acct_fields[0], amount_fields[0]
        try:
            agg = client.aggregate_records(
                model, group_by=[acct_field],
                measures=[(amount_field, "sum")],
                domain=[(acct_field, "in", account_ids), *extra_domain])
        except OdooError:
            continue
        budgets: dict[int, float] = {}
        for row in agg.get("rows", []):
            acct = row.get(acct_field)
            if acct:
                budgets[acct[0]] = abs(row.get(f"{amount_field}:sum") or 0.0)
        return budgets, True
    return {}, False


@mcp.tool()
def project_profitability(
    project: str | None = None,
    manager: str | None = None,
    customer: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    top_n: int = 5,
    burn_pct_at_risk: float = 80.0,
    burn_pct_off_track: float = 100.0,
    timezone_offset: int = 7,
) -> str:
    """Report delivery hours, money and budget burn per project in one call.

    Composes active project.project records (filtered by name / manager /
    customer) with timesheet hours (account.analytic.line grouped by
    project), analytic cost/revenue (grouped by analytic account) and the
    Budgets app when installed, into a per-project burn verdict
    (off_track / at_risk / on_track). When the filter matches exactly one
    project the report gains per-employee and per-task breakdowns.

    Args:
        project: Optional project-name filter (name ilike). Exactly one
            match switches on the drill-down breakdowns.
        manager: Optional project-manager filter (user_id.name ilike).
        customer: Optional customer filter (partner_id.name ilike).
        date_from: Optional YYYY-MM-DD lower bound on logged hours and
            analytic amounts. Allocated hours and budgets stay lifetime
            totals, so ANY date filter disables the burn verdicts
            (verdict "n/a", burn percentages null).
        date_to: Optional YYYY-MM-DD upper bound (same caveat).
        top_n: Rows in the drill-down breakdowns (default 5).
        burn_pct_at_risk: Worst burn %% >= this -> at_risk (default 80).
        burn_pct_off_track: Worst burn %% >= this -> off_track (default 100).
        timezone_offset: UTC offset for "today" (default 7).
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        d_from = _validate_date(date_from, "date_from")
        d_to = _validate_date(date_to, "date_to")
        burn_evaluated = not (d_from or d_to)

        domain: list = [("active", "=", True)]
        if project:
            domain.append(("name", "ilike", project))
        if manager:
            domain.append(("user_id.name", "ilike", manager))
        if customer:
            domain.append(("partner_id.name", "ilike", customer))

        extra_fields = optional_fields(
            client, "project.project",
            ["allocated_hours", "account_id", "analytic_account_id"])
        projects, truncation = fetch_with_truncation(
            client, "project.project", domain,
            fields=["id", "name", "user_id", "partner_id", "company_id",
                    *extra_fields],
            limit=200, order="name")

        # Analytic account moved analytic_account_id -> account_id in 18.
        acct_field = next(
            (f for f in ("account_id", "analytic_account_id")
             if f in extra_fields), None)
        has_alloc_field = "allocated_hours" in extra_fields

        ids = [p["id"] for p in projects]
        acct_by_project = {
            p["id"]: p[acct_field][0]
            for p in projects if acct_field and p.get(acct_field)}
        account_ids = sorted(set(acct_by_project.values()))
        drill_id = ids[0] if len(ids) == 1 else None

        date_dom: list = []
        if d_from:
            date_dom.append(("date", ">=", d_from))
        if d_to:
            date_dom.append(("date", "<=", d_to))

        hours_by_project: dict[int, float] = {}
        cost_by_account: dict[int, float] = {}
        revenue_by_account: dict[int, float] = {}
        by_employee: list[dict] = []
        by_task: list[dict] = []
        budgets: dict[int, float] = {}
        budgets_available = False

        if ids:
            ensure_field(client, "account.analytic.line", "project_id",
                         hint=_TIMESHEET_HINT)

            def analytic_calls():
                # Every call here hits account.analytic.line -> ONE thunk,
                # fixed order (hours, cost, revenue, by_employee, by_task)
                # so the FakeClient per-model queue stays deterministic
                # (documented constraint in workflow_helpers.gather).
                hours = client.aggregate_records(
                    "account.analytic.line", group_by=["project_id"],
                    measures=[("unit_amount", "sum")],
                    domain=[("project_id", "in", ids), *date_dom])
                cost = revenue = None
                if account_ids:
                    cost = client.aggregate_records(
                        "account.analytic.line", group_by=["account_id"],
                        measures=[("amount", "sum")],
                        domain=[("account_id", "in", account_ids),
                                ("amount", "<", 0), *date_dom])
                    revenue = client.aggregate_records(
                        "account.analytic.line", group_by=["account_id"],
                        measures=[("amount", "sum")],
                        domain=[("account_id", "in", account_ids),
                                ("amount", ">", 0), *date_dom])
                emp = task = None
                if drill_id is not None:
                    emp = client.aggregate_records(
                        "account.analytic.line", group_by=["employee_id"],
                        measures=[("unit_amount", "sum")],
                        domain=[("project_id", "=", drill_id), *date_dom],
                        limit=top_n, order="unit_amount:sum desc")
                    task = client.aggregate_records(
                        "account.analytic.line", group_by=["task_id"],
                        measures=[("unit_amount", "sum")],
                        domain=[("project_id", "=", drill_id), *date_dom],
                        limit=top_n, order="unit_amount:sum desc")
                return hours, cost, revenue, emp, task

            fetched = gather_strict({
                "analytic": analytic_calls,
                "budget": lambda: _budget_by_account(client, account_ids),
            })
            hours_agg, cost_agg, revenue_agg, emp_agg, task_agg = \
                fetched["analytic"]
            budgets, budgets_available = fetched["budget"]

            for row in hours_agg.get("rows", []):
                m2o = row.get("project_id")
                if m2o:
                    hours_by_project[m2o[0]] = (
                        row.get("unit_amount:sum") or 0.0)
            for agg, target in ((cost_agg, cost_by_account),
                                (revenue_agg, revenue_by_account)):
                for row in (agg.get("rows", []) if agg else []):
                    m2o = row.get("account_id")
                    if m2o:
                        target[m2o[0]] = row.get("amount:sum") or 0.0
            for agg, target, key, label in (
                    (emp_agg, by_employee, "employee_id", "employee"),
                    (task_agg, by_task, "task_id", "task")):
                for row in (agg.get("rows", []) if agg else []):
                    m2o = row.get(key)
                    target.append({
                        label: m2o[1] if m2o else "(none)",
                        "hours": round(row.get("unit_amount:sum") or 0.0, 2),
                    })

        rows_out: list[dict] = []
        off_track = at_risk = on_track = 0
        t_hours = t_alloc = t_cost = t_revenue = t_budget = 0.0
        no_alloc = no_acct = negative = 0
        for p in projects:
            pid = p["id"]
            hours = hours_by_project.get(pid, 0.0)
            alloc = ((p.get("allocated_hours") or 0.0)
                     if has_alloc_field else 0.0)
            acct_id = acct_by_project.get(pid)
            cost = (abs(cost_by_account.get(acct_id, 0.0))
                    if acct_id is not None else 0.0)
            revenue = (revenue_by_account.get(acct_id, 0.0)
                       if acct_id is not None else 0.0)
            margin = revenue - cost
            budget = (budgets.get(acct_id)
                      if budgets_available and acct_id is not None else None)

            hours_burn = (round(hours / alloc * 100, 1)
                          if burn_evaluated and alloc else None)
            budget_burn = (round(cost / budget * 100, 1)
                           if burn_evaluated and budget else None)
            if burn_evaluated:
                verdict, worst = _verdict(
                    hours_burn, budget_burn,
                    burn_pct_at_risk, burn_pct_off_track)
                if verdict == "off_track":
                    off_track += 1
                elif verdict == "at_risk":
                    at_risk += 1
                else:
                    on_track += 1
            else:
                verdict, worst = "n/a", None

            if hours and not alloc:
                no_alloc += 1
            if hours and acct_id is None:
                no_acct += 1
            if margin < 0:
                negative += 1
            t_hours += hours
            t_alloc += alloc
            t_cost += cost
            t_revenue += revenue
            if budget is not None:
                t_budget += budget

            rows_out.append({
                "project": p["name"],
                "manager": p["user_id"][1] if p.get("user_id") else None,
                "customer": p["partner_id"][1] if p.get("partner_id") else None,
                "hours_logged": round(hours, 2),
                "hours_allocated": round(alloc, 2),
                "hours_burn_pct": hours_burn,
                "cost": round(cost, 2),
                "revenue": round(revenue, 2),
                "margin": round(margin, 2),
                "budget": round(budget, 2) if budget is not None else None,
                "budget_burn_pct": budget_burn,
                "verdict": verdict,
                "_worst": worst,
            })

        rank = {"off_track": 0, "at_risk": 1, "on_track": 2}
        if burn_evaluated:
            rows_out.sort(key=lambda r: (
                rank[r["verdict"]],
                -(r["_worst"] if r["_worst"] is not None else -1.0),
                r["project"]))
        else:
            rows_out.sort(key=lambda r: (-r["cost"], r["project"]))
        worst_name = worst_val = None
        if rows_out and rows_out[0]["_worst"] is not None:
            worst_name = rows_out[0]["project"]
            worst_val = rows_out[0]["_worst"]
        for r in rows_out:
            r.pop("_worst")

        margin_total = round(t_revenue - t_cost, 2)
        summary: dict = {
            "projects": len(projects),
            "hours_logged": round(t_hours, 2),
            "hours_allocated": round(t_alloc, 2),
            "hours_burn_pct": (round(t_hours / t_alloc * 100, 1)
                               if burn_evaluated and t_alloc else None),
            "cost": round(t_cost, 2),
            "revenue": round(t_revenue, 2),
            "margin": margin_total,
            "margin_pct": (round(margin_total / t_revenue * 100, 1)
                           if t_revenue else None),
            "off_track": off_track,
            "at_risk": at_risk,
            "on_track": on_track,
        }
        if budgets_available:
            summary["budget"] = round(t_budget, 2)
            summary["budget_burn_pct"] = (
                round(t_cost / t_budget * 100, 1)
                if burn_evaluated and t_budget else None)
        companies = distinct_companies(projects)
        if len(companies) > 1:
            summary["companies"] = companies
        if truncation:
            summary["truncated"] = True
            summary["total_matching"] = truncation["total_matching"]

        highlights = [
            f"{summary['hours_logged']} h logged across {len(projects)} "
            f"project(s), cost {summary['cost']}, "
            f"margin {summary['margin']}"]
        if worst_name is not None:
            highlights.append(
                f"worst burn: {worst_name} at {worst_val}%")
        if drill_id is not None and by_employee:
            top = by_employee[0]
            highlights.append(
                f"top contributor: {top['employee']} ({top['hours']} h)")

        risks: list[dict] = []
        if truncation:
            risks.append({
                "code": "truncated_data", "count": truncation["missing"],
                "message": (
                    f"Report covers only {truncation['fetched']} of "
                    f"{truncation['total_matching']} matching projects."),
            })
        if off_track:
            risks.append({
                "code": "over_budget", "count": off_track,
                "message": (f"{off_track} project(s) burned past "
                            f"{burn_pct_off_track}% of hours or budget"),
            })
        if negative:
            risks.append({
                "code": "negative_margin", "count": negative,
                "message": (f"{negative} project(s) cost more than they "
                            "earned (revenue - cost < 0)"),
            })
        if no_alloc:
            risks.append({
                "code": "no_allocation", "count": no_alloc,
                "message": (f"{no_alloc} project(s) log hours but have no "
                            "allocated_hours — hours burn not computable"),
            })
        if no_acct:
            risks.append({
                "code": "no_analytic_account", "count": no_acct,
                "message": (f"{no_acct} project(s) log hours but have no "
                            "analytic account — cost/revenue blind"),
            })
        if len(companies) > 1:
            risks.append({
                "code": "mixed_companies", "count": len(companies),
                "message": (
                    "Analytic amounts are in company currency and scope "
                    f"spans {', '.join(companies)}; filter by manager/"
                    "customer/project to compare like with like."),
            })

        breakdown: dict = {"projects": rows_out}
        if drill_id is not None:
            breakdown["by_employee"] = by_employee
            breakdown["by_task"] = by_task

        return build_report(
            "project_profitability", today,
            summary=summary, breakdown=breakdown,
            highlights=highlights, risks=risks,
            extra={"filters": {"project": project, "manager": manager,
                               "customer": customer, "date_from": d_from,
                               "date_to": d_to},
                   "thresholds": {
                       "burn_pct_at_risk": burn_pct_at_risk,
                       "burn_pct_off_track": burn_pct_off_track},
                   "budgets_available": budgets_available,
                   "burn_evaluated": burn_evaluated})

    return safe(run)

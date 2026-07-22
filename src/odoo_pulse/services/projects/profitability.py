# odoo_pulse/services/projects/profitability.py
"""Project profitability report: delivery hours, money and budget burn.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based burn verdict. Read-only.

Caveats for callers:
- Analytic amounts are in each company's currency (mixed_companies risk).
- Two projects sharing one analytic account each get the full account's
  cost/revenue/budget (accepted double-count; splitting would be arbitrary).
- Budgets match by a line-level project_id m2o when the instance has one
  (authoritative), else by the project's own analytic account — budgets
  carried on a second analytic dimension without project_id stay invisible.
- On Odoo 18+ the budget state filter is skipped (state lives on the parent
  budget.analytic and drifts across minor versions); revenue-type budgets
  ARE excluded via a dotted budget_type domain — when that field is missing
  on the instance the aggregate faults and budgets degrade to unavailable.
"""

from __future__ import annotations

from ...common.concurrency import gather_strict
from ...common.dates import parse_period_date, today_in_tz
from ...common.paging import fetch_with_truncation
from ...common.reporting import build_report, distinct_companies
from ...common.schema import ensure_field, optional_fields
from .budget import budget_by_project, burn_verdict
from .finance import FALLBACK_WARNING, analytic_money
from .queries import account_ids_by_project, project_domain

_TIMESHEET_HINT = ("Timesheets require the hr_timesheet app; install it to "
                   "report delivery hours.")


def validate_project_date(value: str | None, param: str) -> str | None:
    """YYYY-MM-DD normalising validator; garbage -> clean OdooError.
    Delegates the actual parsing to common.dates.parse_period_date (same
    helper periods_domain uses) instead of a second, independently-maintained
    validator. Returns the PARSED date, not a slice of the raw input:
    parse_period_date tolerates surrounding whitespace, so slicing
    " 2026-07-01" would leak the garbage " 2026-07-0" into a domain."""
    if not value:
        return None
    return parse_period_date(value, param).isoformat()


def build_project_profitability_report(
    client, *, project=None, manager=None, customer=None,
    date_from=None, date_to=None, top_n=5,
    burn_pct_at_risk=80.0, burn_pct_off_track=100.0,
    timezone_offset=7,
) -> dict:
    today = today_in_tz(timezone_offset)
    d_from = validate_project_date(date_from, "date_from")
    d_to = validate_project_date(date_to, "date_to")
    burn_evaluated = not (d_from or d_to)

    domain = project_domain(project=project, manager=manager,
                            customer=customer)

    extra_fields = optional_fields(
        client, "project.project",
        ["allocated_hours", "account_id", "analytic_account_id"])
    projects, truncation = fetch_with_truncation(
        client, "project.project", domain,
        fields=["id", "name", "user_id", "partner_id", "company_id",
                *extra_fields],
        limit=200, order="name")

    has_alloc_field = "allocated_hours" in extra_fields

    ids = [p["id"] for p in projects]
    acct_by_project = account_ids_by_project(projects, extra_fields)
    account_ids = sorted(set(acct_by_project.values()))
    drill_id = ids[0] if len(ids) == 1 else None

    date_dom: list = []
    if d_from:
        date_dom.append(("date", ">=", d_from))
    if d_to:
        date_dom.append(("date", "<=", d_to))

    hours_by_project: dict[int, float] = {}
    money = analytic_money(client, [])
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
            # (documented constraint in common.concurrency.gather).
            hours = client.aggregate_records(
                "account.analytic.line", group_by=["project_id"],
                measures=[("unit_amount", "sum")],
                domain=[("project_id", "in", ids), *date_dom])
            money = analytic_money(
                client, account_ids, extra_domain=date_dom)
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
            return hours, money, emp, task

        fetched = gather_strict({
            "analytic": analytic_calls,
            "budget": lambda: budget_by_project(
                client, ids, acct_by_project),
        })
        hours_agg, money, emp_agg, task_agg = fetched["analytic"]
        budgets, budgets_available = fetched["budget"]

        for row in hours_agg.get("rows", []):
            m2o = row.get("project_id")
            if m2o:
                hours_by_project[m2o[0]] = (
                    row.get("unit_amount:sum") or 0.0)
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
        cost = (money.cost_by_account.get(acct_id, 0.0)
                if acct_id is not None else 0.0)
        revenue = (money.revenue_by_account.get(acct_id, 0.0)
                   if acct_id is not None else 0.0)
        margin = revenue - cost
        budget = budgets.get(pid) if budgets_available else None

        hours_burn = (round(hours / alloc * 100, 1)
                      if burn_evaluated and alloc else None)
        budget_burn = (round(cost / budget * 100, 1)
                       if burn_evaluated and budget else None)
        if burn_evaluated:
            verdict, worst = burn_verdict(
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
            "project_id": pid,
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
    if money.classification == "sign_fallback":
        risks.append({
            "code": "analytic_classification_fallback",
            "count": len(account_ids),
            "message": FALLBACK_WARNING,
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
               "burn_evaluated": burn_evaluated,
               "analytic_classification": money.classification})

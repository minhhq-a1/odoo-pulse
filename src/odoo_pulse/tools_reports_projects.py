# odoo_pulse/tools_reports_projects.py
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

from .odoo_client import OdooError
from .runtime import get_client, mcp, safe
from .workflow_helpers import (
    build_report,
    distinct_companies,
    ensure_field,
    fetch_with_truncation,
    gather_strict,
    optional_fields,
    today_in_tz,
)
from .project_shared import (  # noqa: F401  (re-export for tests/back-compat)
    _BUDGET_CANDIDATES,
    _PARENT_CANDIDATES,
    _PRACTICAL_CANDIDATES,
    _THEORETICAL_CANDIDATES,
    _budget_by_project,
    _budget_sources,
)
from .project_shared import _parse_ymd, account_ids_by_project, analytic_money

_TIMESHEET_HINT = ("Timesheets require the hr_timesheet app; install it to "
                   "report delivery hours.")


def _validate_date(value: str | None, param: str) -> str | None:
    """YYYY-MM-DD normalising validator; garbage -> clean OdooError.
    Delegates the actual parsing to project_shared._parse_ymd (same helper
    periods_domain uses) instead of a second, independently-maintained
    validator. Returns the PARSED date, not a slice of the raw input:
    _parse_ymd tolerates surrounding whitespace, so slicing " 2026-07-01"
    would leak the garbage " 2026-07-0" into a domain."""
    if not value:
        return None
    return _parse_ymd(value, param).isoformat()


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




@mcp.tool()
def project_budget(
    project: str | None = None,
    manager: str | None = None,
    customer: str | None = None,
    top_n: int = 10,
    burn_pct_at_risk: float = 80.0,
    burn_pct_off_track: float = 100.0,
    timezone_offset: int = 7,
) -> str:
    """Report planned vs actual budget per project, line by line.

    Reads the Budgets app (budget.line on Odoo 18+, else
    crossovered.budget.lines) and matches lines to active projects by a
    line-level project_id m2o when the instance has one, else through the
    project's analytic account. Amounts are absolute company-currency
    sums; server-computed practical/theoretical amounts are used as-is.
    Also compares each project's total analytic cost against the practical
    amounts booked on its budget lines, flagging spend the budget does not
    capture. When the filter matches exactly one project the report gains
    a per-line breakdown. No date filters: budget lines carry their own
    period.

    Args:
        project: Optional project-name filter (name ilike). Exactly one
            match switches on the per-line breakdown.
        manager: Optional project-manager filter (user_id.name ilike).
        customer: Optional customer filter (partner_id.name ilike).
        top_n: Rows in the per-line breakdown (default 10).
        burn_pct_at_risk: Burn %% >= this -> at_risk (default 80).
        burn_pct_off_track: Burn %% >= this -> off_track (default 100).
        timezone_offset: UTC offset for "today" (default 7).
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)

        domain: list = [("active", "=", True)]
        if project:
            domain.append(("name", "ilike", project))
        if manager:
            domain.append(("user_id.name", "ilike", manager))
        if customer:
            domain.append(("partner_id.name", "ilike", customer))

        acct_fields = optional_fields(
            client, "project.project",
            ["account_id", "analytic_account_id"])
        projects, truncation = fetch_with_truncation(
            client, "project.project", domain,
            fields=["id", "name", "user_id", "partner_id", "company_id",
                    *acct_fields],
            limit=200, order="name")

        ids = [p["id"] for p in projects]
        acct_by_project = account_ids_by_project(projects, acct_fields)
        account_ids = sorted(set(acct_by_project.values()))
        drill_id = ids[0] if len(ids) == 1 else None

        budgets_available = False
        line_rows: list[dict] = []
        line_truncation = None
        line_acct = practical_field = theoretical_field = None
        parent_field = amount_field = link_field = None
        line_opt: list[str] = []
        cost_by_account: dict[int, float] = {}

        if ids:
            def fetch_lines():
                # First usable candidate whose line fetch does not fault
                # (a faulting dotted extra-domain field drops to the next
                # candidate, mirroring _budget_by_project).
                for src in _budget_sources(client, account_ids):
                    model, link, acct, amount, extra_domain = src
                    opt = optional_fields(client, model, [
                        *_PRACTICAL_CANDIDATES, *_THEORETICAL_CANDIDATES,
                        *_PARENT_CANDIDATES, "general_budget_id",
                        "date_from", "date_to"])
                    fields = ["id", amount, *opt]
                    if link:
                        fields.append(link)
                        match = (link, "in", ids)
                    else:
                        match = (acct, "in", account_ids)
                    if acct and acct not in fields:
                        fields.append(acct)
                    try:
                        rows, trunc = fetch_with_truncation(
                            client, model, [match, *extra_domain],
                            fields=fields, limit=500)
                    except OdooError:
                        continue
                    return src, opt, rows, trunc
                return None

            def fetch_cost():
                if not account_ids:
                    return None
                return client.aggregate_records(
                    "account.analytic.line", group_by=["account_id"],
                    measures=[("amount", "sum")],
                    domain=[("account_id", "in", account_ids),
                            ("amount", "<", 0)])

            fetched = gather_strict(
                {"lines": fetch_lines, "cost": fetch_cost})
            if fetched["lines"] is not None:
                budgets_available = True
                src, line_opt, line_rows, line_truncation = fetched["lines"]
                _, link_field, line_acct, amount_field, _ = src
                def pick(candidates):
                    return next((field for field in candidates if field in line_opt), None)
                practical_field = pick(_PRACTICAL_CANDIDATES)
                theoretical_field = pick(_THEORETICAL_CANDIDATES)
                parent_field = pick(_PARENT_CANDIDATES)
            for row in ((fetched["cost"] or {}).get("rows", [])):
                m2o = row.get("account_id")
                if m2o:
                    cost_by_account[m2o[0]] = abs(row.get("amount:sum")
                                                  or 0.0)

        lines_by_project: dict[int, list[dict]] = {}
        if link_field:
            for row in line_rows:
                m2o = row.get(link_field)
                if m2o:
                    lines_by_project.setdefault(m2o[0], []).append(row)
        elif line_acct:
            pids_by_acct: dict[int, list[int]] = {}
            for pid, aid in acct_by_project.items():
                pids_by_acct.setdefault(aid, []).append(pid)
            for row in line_rows:
                m2o = row.get(line_acct)
                for pid in (pids_by_acct.get(m2o[0], []) if m2o else []):
                    lines_by_project.setdefault(pid, []).append(row)

        def line_stats(row: dict) -> tuple[float, float | None, bool]:
            planned = abs(row.get(amount_field) or 0.0)
            practical = (abs(row.get(practical_field) or 0.0)
                         if practical_field else None)
            over = (practical is not None
                    and ((planned > 0 and practical > planned)
                         or (planned == 0 and practical > 0)))
            return planned, practical, over

        rows_out: list[dict] = []
        off_track = at_risk = on_track = 0
        t_planned = t_practical = t_cost = t_uncaptured = 0.0
        over_plan_total = no_budget = outside = with_budget = 0
        budget_ids: set[int] = set()
        for p in projects:
            pid = p["id"]
            acct_id = acct_by_project.get(pid)
            cost = (cost_by_account.get(acct_id, 0.0)
                    if acct_id is not None else 0.0)
            plines = lines_by_project.get(pid, [])
            budget_names = sorted(
                {row[parent_field][1] for row in plines
                 if parent_field and row.get(parent_field)})
            for row in plines:
                if parent_field and row.get(parent_field):
                    budget_ids.add(row[parent_field][0])

            planned = practical = burn = uncaptured = None
            over_plan = 0
            if budgets_available and plines:
                with_budget += 1
                planned = practical = 0.0
                for row in plines:
                    pl, pr, over = line_stats(row)
                    planned += pl
                    practical += pr or 0.0
                    over_plan += 1 if over else 0
                if practical_field is None:
                    practical = None
                burn = (round(practical / planned * 100, 1)
                        if practical is not None and planned else None)
                verdict, _ = _verdict(None, burn, burn_pct_at_risk,
                                      burn_pct_off_track)
                if verdict == "off_track":
                    off_track += 1
                elif verdict == "at_risk":
                    at_risk += 1
                else:
                    on_track += 1
                if practical is not None:
                    uncaptured = round(max(cost - practical, 0.0), 2)
                    if cost > 0 and (cost - practical) > 0.01 * cost:
                        outside += 1
            else:
                verdict = "n/a"
                if budgets_available:
                    no_budget += 1

            over_plan_total += over_plan
            t_planned += planned or 0.0
            t_practical += practical or 0.0
            t_cost += cost
            t_uncaptured += uncaptured or 0.0

            rows_out.append({
                "project_id": pid,
                "project": p["name"],
                "manager": p["user_id"][1] if p.get("user_id") else None,
                "customer": (p["partner_id"][1]
                             if p.get("partner_id") else None),
                "budgets": budget_names,
                "lines": len(plines),
                "planned": round(planned, 2) if planned is not None else None,
                "practical": (round(practical, 2)
                              if practical is not None else None),
                "burn_pct": burn,
                "cost": round(cost, 2),
                "uncaptured_cost": uncaptured,
                "over_plan_lines": over_plan,
                "verdict": verdict,
                "_burn": burn,
            })

        rank = {"off_track": 0, "at_risk": 1, "on_track": 2, "n/a": 3}
        if budgets_available:
            rows_out.sort(key=lambda r: (
                rank[r["verdict"]],
                -(r["_burn"] if r["_burn"] is not None else -1.0),
                r["project"]))
        else:
            rows_out.sort(key=lambda r: (-r["cost"], r["project"]))
        worst_name = worst_val = None
        if rows_out and rows_out[0]["_burn"] is not None:
            worst_name = rows_out[0]["project"]
            worst_val = rows_out[0]["_burn"]
        for r in rows_out:
            r.pop("_burn")

        has_practical = budgets_available and practical_field is not None
        summary: dict = {
            "projects": len(projects),
            "with_budget": with_budget,
            "budgets": len(budget_ids),
            "planned": (round(t_planned, 2)
                        if budgets_available else None),
            "practical": (round(t_practical, 2)
                          if has_practical else None),
            "burn_pct": (round(t_practical / t_planned * 100, 1)
                         if has_practical and t_planned else None),
            "cost": round(t_cost, 2),
            "uncaptured_cost": (round(t_uncaptured, 2)
                                if has_practical else None),
            "off_track": off_track,
            "at_risk": at_risk,
            "on_track": on_track,
            "over_plan_lines": over_plan_total,
        }
        companies = distinct_companies(projects)
        if len(companies) > 1:
            summary["companies"] = companies
        if truncation:
            summary["truncated"] = True
            summary["total_matching"] = truncation["total_matching"]

        breakdown: dict = {"projects": rows_out}
        if drill_id is not None and budgets_available:
            dlines = []
            for row in lines_by_project.get(drill_id, []):
                pl, pr, over = line_stats(row)
                if line_acct and row.get(line_acct):
                    label = row[line_acct][1]
                elif row.get("general_budget_id"):
                    label = row["general_budget_id"][1]
                else:
                    label = f"(line {row.get('id')})"
                dlines.append({
                    "line": label,
                    "budget": (row[parent_field][1]
                               if parent_field and row.get(parent_field)
                               else None),
                    "planned": round(pl, 2),
                    "practical": round(pr, 2) if pr is not None else None,
                    "theoretical": (
                        round(abs(row.get(theoretical_field) or 0.0), 2)
                        if theoretical_field else None),
                    "burn_pct": (round(pr / pl * 100, 1)
                                 if pr is not None and pl else None),
                    "over_plan": over,
                    "date_from": row.get("date_from") or None,
                    "date_to": row.get("date_to") or None,
                })
            dlines.sort(key=lambda ln: -(ln["practical"] or 0.0))
            breakdown["lines"] = dlines[:top_n]

        highlights: list[str] = []
        if summary["practical"] is not None:
            highlights.append(
                f"{summary['practical']} spent of {summary['planned']} "
                f"planned across {len(projects)} project(s)")
        else:
            highlights.append(
                f"budget figures unavailable across {len(projects)} "
                "project(s)")
        if worst_name is not None:
            highlights.append(f"worst burn: {worst_name} at {worst_val}%")
        top_lines = breakdown.get("lines") or []
        if top_lines and top_lines[0]["practical"] is not None:
            top = top_lines[0]
            highlights.append(
                f"top line: {top['line']} ({top['practical']} spent of "
                f"{top['planned']} planned)")

        risks: list[dict] = []
        if truncation:
            risks.append({
                "code": "truncated_data", "count": truncation["missing"],
                "message": (
                    f"Report covers only {truncation['fetched']} of "
                    f"{truncation['total_matching']} matching projects."),
            })
        if line_truncation:
            risks.append({
                "code": "truncated_budget_lines",
                "count": line_truncation["missing"],
                "message": (
                    f"Only {line_truncation['fetched']} of "
                    f"{line_truncation['total_matching']} matching budget "
                    "lines were read; totals are incomplete."),
            })
        if ids and not budgets_available:
            risks.append({
                "code": "budgets_unavailable", "count": len(projects),
                "message": ("No usable budget model found (Budgets app "
                            "not installed?) — planned/practical figures "
                            "unavailable."),
            })
        if off_track:
            risks.append({
                "code": "over_budget", "count": off_track,
                "message": (f"{off_track} project(s) burned past "
                            f"{burn_pct_off_track}% of planned budget"),
            })
        if over_plan_total:
            risks.append({
                "code": "line_over_plan", "count": over_plan_total,
                "message": (f"{over_plan_total} budget line(s) spent more "
                            "than planned"),
            })
        if budgets_available and no_budget:
            risks.append({
                "code": "no_budget", "count": no_budget,
                "message": (f"{no_budget} project(s) have no budget lines "
                            "— nothing to burn against"),
            })
        if outside:
            risks.append({
                "code": "spend_outside_budget", "count": outside,
                "message": (
                    f"{outside} project(s) carry analytic cost above the "
                    "practical amounts booked on their budget lines — "
                    "spend is landing outside the budget's analytic "
                    "accounts"),
            })
        if len(companies) > 1:
            risks.append({
                "code": "mixed_companies", "count": len(companies),
                "message": (
                    "Amounts are in company currency and scope spans "
                    f"{', '.join(companies)}; filter by manager/customer/"
                    "project to compare like with like."),
            })

        return build_report(
            "project_budget", today,
            summary=summary, breakdown=breakdown,
            highlights=highlights, risks=risks,
            extra={"filters": {"project": project, "manager": manager,
                               "customer": customer},
                   "thresholds": {
                       "burn_pct_at_risk": burn_pct_at_risk,
                       "burn_pct_off_track": burn_pct_off_track},
                   "budgets_available": budgets_available})

    return safe(run)


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
                cost_by, revenue_by = analytic_money(
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
                return hours, cost_by, revenue_by, emp, task

            fetched = gather_strict({
                "analytic": analytic_calls,
                "budget": lambda: _budget_by_project(
                    client, ids, acct_by_project),
            })
            hours_agg, cost_by_account, revenue_by_account, emp_agg, task_agg = \
                fetched["analytic"]
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
            cost = (cost_by_account.get(acct_id, 0.0)
                    if acct_id is not None else 0.0)
            revenue = (revenue_by_account.get(acct_id, 0.0)
                       if acct_id is not None else 0.0)
            margin = revenue - cost
            budget = budgets.get(pid) if budgets_available else None

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

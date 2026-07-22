# odoo_pulse/services/projects/budget.py
"""Project budget primitives and the project_budget report builder.

Everything here is read-only and client-agnostic (real OdooClient or the
test FakeClient). Budget matching -- probing budget.line vs
crossovered.budget.lines, expense/revenue disambiguation, and
project/analytic-account precedence -- lives in ONE place so
project_budget, project_profitability, project_dashboard and
portfolio_health can never disagree on planned/practical figures (single
source of truth for planned/practical figures — spec rule #7).
"""

from __future__ import annotations

from ...common.concurrency import gather_strict
from ...common.dates import periods_domain, today_in_tz
from ...common.paging import fetch_with_truncation, paged_search_read
from ...common.reporting import build_report, distinct_companies
from ...common.schema import optional_fields
from ...core.errors import OdooError
from .finance import (
    FALLBACK_WARNING,
    analytic_bucket,
    analytic_classification,
    analytic_money,
)
from .queries import account_id_of, account_ids_by_project, project_domain

# (model, analytic-account field candidates, planned-amount field candidates,
#  extra domain). Order below fits Odoo 18+; it is reversed for <= 17.
BUDGET_CANDIDATES = [
    ("budget.line",
     ["account_id", "analytic_account_id"],
     ["budget_amount", "planned_amount"],
     # != "revenue" keeps expense AND mixed ("both") budgets; a faulting
     # dotted field drops to the next candidate via the aggregate try/except.
     [("budget_analytic_id.budget_type", "!=", "revenue")]),
    ("crossovered.budget.lines",
     ["analytic_account_id"],
     ["planned_amount"],
     # planned_amount <= 0 keeps Expense lines only. Unlike budget.line,
     # this model has no technical revenue/expense field on
     # general_budget_id (account.budget.post only has a translatable
     # name) -- the sign of planned_amount is the reliable signal, same
     # convention as analytic_money's account.analytic.line.amount.
     # Without this, a budget with a Revenue-category line (e.g. a
     # matching "Doanh thu" position) alongside its Expense lines gets
     # summed via abs() over both, silently doubling planned/practical.
     # <= (not <) so a "practical-only" Expense budget -- actuals booked
     # but planned_amount left at 0 -- still surfaces; a strict < 0 hid it
     # entirely, making project_dashboard report its id as "match no
     # budget". Positive Revenue lines stay excluded either way.
     [("crossovered_budget_id.state", "in", ["confirm", "validate", "done"]),
      ("planned_amount", "<=", 0)]),
]

PRACTICAL_CANDIDATES = ["practical_amount", "achieved_amount"]
# Odoo spells the crossovered-era field "theoritical" in some series.
THEORETICAL_CANDIDATES = ["theoretical_amount", "theoritical_amount"]

# parent m2o field on a budget line -> the parent budget model it points to
PARENT_MODEL = {
    "crossovered_budget_id": "crossovered.budget",
    "budget_analytic_id": "budget.analytic",
}
# Derived from PARENT_MODEL's keys (not hand-duplicated) so a new parent
# field only needs adding in one place.
PARENT_CANDIDATES = list(PARENT_MODEL)


def budget_sources(client, account_ids: list[int]):
    """Yield usable (model, link_field, acct_field, amount_field, extra_domain).

    The FIRST call against each candidate model is a real RPC
    (search_count) inside try/except OdooError — fields_get is NOT a
    reliable absence probe (see the design doc: the FakeClient returns a
    default schema for unknown models, and the degradation path must be
    identical under test and in production). A candidate is usable when an
    amount field resolves AND it can be matched to projects: either the
    line model carries a project_id m2o (custom field seen in the wild) or
    an analytic-account field resolves and there are account ids to match.
    """
    candidates = list(BUDGET_CANDIDATES)
    major = client.major_version()
    if major is not None and major <= 17:
        candidates.reverse()
    for model, acct_candidates, amount_candidates, extra_domain in candidates:
        try:
            client.search_count(model, [])
        except OdooError:
            continue
        link = (optional_fields(client, model, ["project_id"]) or [None])[0]
        acct = (optional_fields(client, model, acct_candidates) or [None])[0]
        amount = (optional_fields(client, model, amount_candidates)
                  or [None])[0]
        if not amount or not (link or (acct and account_ids)):
            continue
        yield model, link, acct, amount, extra_domain


def budget_match_domain(
    project_ids: list[int], account_ids: list[int],
    link_field: str | None, account_field: str | None,
) -> list:
    """Odoo prefix-notation domain matching budget lines to projects.

    A direct project link is authoritative; the account leaf only picks up
    UNLINKED lines ("|", project_leaf, "&", link=False, account_leaf) so a
    line linked to some OTHER project never gets double-counted onto an
    account it merely shares. An empty result means no usable match --
    callers must skip the source entirely, not query all budget lines.
    """
    project_leaf = (
        (link_field, "in", project_ids)
        if link_field and project_ids else None
    )
    account_leaf = (
        (account_field, "in", account_ids)
        if account_field and account_ids else None
    )
    if project_leaf and account_leaf:
        return [
            "|", project_leaf, "&",
            (link_field, "=", False), account_leaf,
        ]
    if project_leaf:
        return [project_leaf]
    if account_leaf:
        return [account_leaf]
    return []


def project_ids_for_budget_row(
    row: dict, *, requested_project_ids: set[int],
    project_ids_by_account: dict[int, list[int]],
    link_field: str | None, account_field: str | None,
) -> list[int]:
    """Which requested project id(s) a single budget-line row belongs to.

    A truthy project link is authoritative and final: in scope -> that one
    project; out of scope -> [] (must NOT fall through to the account --
    that would leak spend from a project outside the request onto an
    account it happens to share with an in-scope project). Only a falsy
    link falls through to the account, and a shared/unlinked account maps
    to every requested project on it (accepted double-count caveat, same
    as budget_by_project's account aggregate).
    """
    project = row.get(link_field) if link_field else None
    if project:
        project_id = project[0]
        return [project_id] if project_id in requested_project_ids else []
    account = row.get(account_field) if account_field else None
    if not account:
        return []
    return list(project_ids_by_account.get(account[0], []))


def budget_by_project(
    client, project_ids: list[int], acct_by_project: dict[int, int]
) -> tuple[dict[int, float], bool]:
    """Planned budget (absolute) per project id + budgets_available.

    Uses the first usable :func:`budget_sources` candidate. Line-level
    project_id matching is authoritative per project; analytic-account
    matching (the classic path) fills projects the project aggregate did
    not cover — two projects sharing one account each get the account's
    full amount (accepted double-count caveat). Fixed aggregate order
    (project first, then account) keeps the FakeClient queue deterministic.
    None usable -> ({}, False).
    """
    if not project_ids:
        return {}, False
    account_ids = sorted(set(acct_by_project.values()))
    for model, link, acct, amount, extra_domain in budget_sources(
            client, account_ids):
        by_project: dict[int, float] = {}
        by_account: dict[int, float] = {}
        try:
            if link:
                agg = client.aggregate_records(
                    model, group_by=[link],
                    measures=[(amount, "sum")],
                    domain=[(link, "in", project_ids), *extra_domain])
                for row in agg.get("rows", []):
                    m2o = row.get(link)
                    if m2o:
                        by_project[m2o[0]] = abs(
                            row.get(f"{amount}:sum") or 0.0)
            if acct and account_ids:
                agg = client.aggregate_records(
                    model, group_by=[acct],
                    measures=[(amount, "sum")],
                    domain=[(acct, "in", account_ids), *extra_domain])
                for row in agg.get("rows", []):
                    m2o = row.get(acct)
                    if m2o:
                        by_account[m2o[0]] = abs(
                            row.get(f"{amount}:sum") or 0.0)
        except OdooError:
            continue
        budgets = {pid: by_account[aid]
                   for pid, aid in acct_by_project.items()
                   if aid in by_account}
        budgets.update(by_project)
        return budgets, True
    return {}, False


def burn_verdict(
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


def build_budget_context(client, project_id: int,
                         project_row: dict | None = None) -> dict:
    """One shared fetch of budget lines + parent budgets for a project.

    Abstracts crossovered.budget.lines vs budget.line exactly like
    build_project_budget_report does (same budget_sources helper — spec
    rule #7).

    project_row, when given, is a project.project row the caller already
    fetched (e.g. build_core_section's) — must carry "id" and whichever of
    account_id/analytic_account_id exists on this instance. None means
    fetch it here (self-sufficient default). A resolved account id can
    legitimately be None (no account set), so it can't double as the
    "already fetched" sentinel — the row itself is.
    """
    opt = optional_fields(client, "project.project",
                          ["account_id", "analytic_account_id"])
    if project_row is None:
        rows = client.search_read(
            "project.project", domain=[("id", "=", project_id)],
            fields=["id", *opt], limit=1)
        if not rows:
            raise OdooError(f"No project.project with id {project_id}")
        project_row = rows[0]
    acct_id = account_id_of(project_row, opt)
    account_ids = [acct_id] if acct_id is not None else []

    for model, link, acct, amount, extra_domain in budget_sources(
            client, account_ids):
        line_opt = optional_fields(client, model, [
            *PRACTICAL_CANDIDATES, *PARENT_CANDIDATES,
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
            (f for f in PRACTICAL_CANDIDATES if f in line_opt), None)
        parent_field = next(
            (f for f in PARENT_CANDIDATES if f in line_opt), None)
        budgets: list[dict] = []
        if parent_field and parent_field in PARENT_MODEL:
            parent_model = PARENT_MODEL[parent_field]
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


def select_budgets(ctx: dict, budget_ids: list[int] | None
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


def build_budget_detail(client, project_id: int, ctx: dict,
                        budget_ids: list[int] | None,
                        timezone_offset: int) -> dict:
    selected, periods, unknown_budget_ids = select_budgets(ctx, budget_ids)
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

    # classification decides cost vs revenue on the raw rows below (same
    # canonical primitive as project_profitability/portfolio_health/
    # dashboard-core's finance -- spec rule #7); resolved BEFORE the read
    # so the fields requested reflect which columns are actually needed.
    classification = analytic_classification(client)
    analytic_fields = [
        "date", "amount", "unit_amount", "employee_id", "task_id"
    ]
    if classification == "odoo_profitability":
        analytic_fields.append("analytic_profitability")

    # valid_cost rule: ONLY task-linked timesheet lines, inside the OR'd
    # budget periods (account.analytic.line.date is a plain date field).
    domain = [("project_id", "=", project_id), ("task_id", "!=", False),
              *periods_domain("date", periods, timezone_offset,
                              as_datetime=False)]
    rows = paged_search_read(
        client, "account.analytic.line", domain, fields=analytic_fields)

    def bucket(rows_subset, key_fn):
        out: dict = {}
        for row in rows_subset:
            key = key_fn(row)
            cost_hours = out.setdefault(key, [0.0, 0.0])
            if analytic_bucket(row, classification) == "cost":
                cost_hours[0] -= row.get("amount") or 0.0
            cost_hours[1] += row.get("unit_amount") or 0.0
        return out

    # Cost-classified rows only feed valid_cost -- a revenue-classified
    # credit note must never reduce cost (that would silently understate
    # spend), though its hours still count via bucket()'s unconditional
    # hours addition below (population unchanged).
    cost_rows = [r for r in rows if analytic_bucket(r, classification) == "cost"]

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
        "valid_cost": round(
            -sum(r.get("amount") or 0.0 for r in cost_rows), 2),
        "valid_hours": round(sum(r.get("unit_amount") or 0.0
                                 for r in rows), 2),
        "analytic_classification": classification,
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


def build_project_budget_report(
    client, *, project=None, manager=None, customer=None, top_n=10,
    burn_pct_at_risk=80.0, burn_pct_off_track=100.0,
    timezone_offset=7,
) -> dict:
    today = today_in_tz(timezone_offset)

    domain = project_domain(project=project, manager=manager,
                            customer=customer)

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
    classification = "not_evaluated"

    if ids:
        def fetch_lines():
            # First usable candidate whose line fetch does not fault
            # (a faulting dotted extra-domain field drops to the next
            # candidate, mirroring budget_by_project).
            for src in budget_sources(client, account_ids):
                model, link, acct, amount, extra_domain = src
                opt = optional_fields(client, model, [
                    *PRACTICAL_CANDIDATES, *THEORETICAL_CANDIDATES,
                    *PARENT_CANDIDATES, "general_budget_id",
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

        def fetch_money():
            return analytic_money(client, account_ids)

        fetched = gather_strict(
            {"lines": fetch_lines, "money": fetch_money})
        if fetched["lines"] is not None:
            budgets_available = True
            src, line_opt, line_rows, line_truncation = fetched["lines"]
            _, link_field, line_acct, amount_field, _ = src
            def pick(candidates):
                return next((field for field in candidates if field in line_opt), None)
            practical_field = pick(PRACTICAL_CANDIDATES)
            theoretical_field = pick(THEORETICAL_CANDIDATES)
            parent_field = pick(PARENT_CANDIDATES)
        money = fetched["money"]
        cost_by_account = money.cost_by_account
        classification = money.classification

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
        # cost_by_account values are already positive (analytic_money
        # normalizes cost as -amount for the loss/negative bucket) --
        # no abs() needed here, unlike planned/practical below.
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
            verdict, _ = burn_verdict(None, burn, burn_pct_at_risk,
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
    if classification == "sign_fallback":
        risks.append({
            "code": "analytic_classification_fallback",
            "count": len(account_ids),
            "message": FALLBACK_WARNING,
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
               "budgets_available": budgets_available,
               "analytic_classification": classification})

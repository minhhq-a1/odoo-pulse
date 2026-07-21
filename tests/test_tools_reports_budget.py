# tests/test_tools_reports_budget.py
import datetime as dt
import json

from odoo_pulse import tools_reports_projects
from odoo_pulse.core.errors import OdooError
from odoo_pulse.services.projects import budget

# -- fixtures ------------------------------------------------------------------

PROJECT_FIELDS = {"name": {}, "account_id": {}}
PROJECTS = [
    {"id": 1, "name": "Alpha", "user_id": [3, "Mai"],
     "partner_id": [9, "Acme"], "company_id": [1, "Main Co"],
     "account_id": [11, "AA Alpha"]},
    {"id": 2, "name": "Beta", "user_id": [4, "Nam"],
     "partner_id": [10, "Globex"], "company_id": [1, "Main Co"],
     "account_id": [12, "AA Beta"]},
]
# Mirrors the live shape that motivated the tool: expense lines are negative,
# each line carries a cost-category analytic account (a second analytic
# dimension) plus a custom project_id m2o.
LINE_SCHEMA = {
    "project_id": {}, "analytic_account_id": {}, "planned_amount": {},
    "practical_amount": {}, "theoretical_amount": {},
    "crossovered_budget_id": {}, "general_budget_id": {},
    "date_from": {}, "date_to": {}}
LINES = [
    {"id": 19, "project_id": [1, "Alpha"],
     "analytic_account_id": [90, "CP nhân công"],
     "crossovered_budget_id": [8, "PASX A"],
     "general_budget_id": [1, "Expense"],
     "planned_amount": -1000.0, "practical_amount": -1300.0,
     "theoretical_amount": -950.0,
     "date_from": "2025-03-01", "date_to": "2026-07-31"},
    {"id": 20, "project_id": [1, "Alpha"],
     "analytic_account_id": [91, "CP bảo hành"],
     "crossovered_budget_id": [8, "PASX A"],
     "general_budget_id": [1, "Expense"],
     "planned_amount": -500.0, "practical_amount": 0.0,
     "theoretical_amount": -480.0,
     "date_from": "2025-03-01", "date_to": "2026-07-31"},
    {"id": 21, "project_id": [2, "Beta"],
     "analytic_account_id": [92, "CP nhân công"],
     "crossovered_budget_id": [9, "PASX B"],
     "general_budget_id": [1, "Expense"],
     "planned_amount": -400.0, "practical_amount": -100.0,
     "theoretical_amount": -380.0,
     "date_from": "2025-01-01", "date_to": "2025-12-31"},
]
AGG_COST = [{"account_id": [11, "AA Alpha"], "amount:sum": -8000.0},
            {"account_id": [12, "AA Beta"], "amount:sum": -100.0}]


def _seed(fake, projects=PROJECTS, lines=LINES, cost=AGG_COST):
    """budget.line stays unusable (default schema resolves no amount field),
    so the walk lands on crossovered.budget.lines with our schema."""
    fake.fields_responses["project.project"] = PROJECT_FIELDS
    fake.search_responses["project.project"] = projects
    fake.fields_responses["crossovered.budget.lines"] = dict(LINE_SCHEMA)
    fake.search_responses["crossovered.budget.lines"] = lines
    fake.aggregate_responses_seq["account.analytic.line"] = [list(cost)]


# -- domains -------------------------------------------------------------------

def test_filters_land_in_project_domain(fake_client):
    _seed(fake_client)
    tools_reports_projects.project_budget(
        project="alp", manager="mai", customer="acme")
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read"
                and c["model"] == "project.project")
    for cond in [("active", "=", True), ("name", "ilike", "alp"),
                 ("user_id.name", "ilike", "mai"),
                 ("partner_id.name", "ilike", "acme")]:
        assert cond in call["domain"]
    assert call["limit"] == 200 and call["order"] == "name"


def test_line_and_cost_domains(fake_client):
    _seed(fake_client)
    tools_reports_projects.project_budget()
    lines = next(c for c in fake_client.calls
                 if c["method"] == "search_read"
                 and c["model"] == "crossovered.budget.lines")
    assert ("project_id", "in", [1, 2]) in lines["domain"]
    assert ("crossovered_budget_id.state", "in",
            ["confirm", "validate", "done"]) in lines["domain"]
    # Revenue-category lines (general_budget_id="Revenue") must never enter
    # planned/practical sums alongside Expense lines -- a budget with equal
    # Expense and Revenue totals would otherwise report double the real
    # planned amount (bug: project 127 "RTH - CR 0126" showed 479,600,000
    # instead of the correct 239,800,000).
    assert ("planned_amount", "<=", 0) in lines["domain"]
    assert lines["limit"] == 500
    cost = next(c for c in fake_client.calls
                if c["method"] == "aggregate_records"
                and c["model"] == "account.analytic.line")
    assert cost["group_by"] == ["account_id"]
    assert cost["measures"] == [("amount", "sum")]
    assert ("account_id", "in", [11, 12]) in cost["domain"]
    assert ("amount", "<", 0) in cost["domain"]


def test_account_fallback_assigns_lines_via_account(fake_client):
    # No project_id on the line model -> lines match through the project's
    # own analytic account.
    _seed(fake_client, lines=[
        {"id": 30, "analytic_account_id": [11, "AA Alpha"],
         "crossovered_budget_id": [8, "PASX A"],
         "general_budget_id": [1, "Expense"],
         "planned_amount": -1000.0, "practical_amount": -250.0,
         "theoretical_amount": -900.0,
         "date_from": "2025-01-01", "date_to": "2025-12-31"}])
    fake_client.fields_responses["crossovered.budget.lines"] = {
        k: v for k, v in LINE_SCHEMA.items() if k != "project_id"}
    out = json.loads(tools_reports_projects.project_budget())
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read"
                and c["model"] == "crossovered.budget.lines")
    assert ("analytic_account_id", "in", [11, 12]) in call["domain"]
    rows = {r["project"]: r for r in out["breakdown"]["projects"]}
    assert rows["Alpha"]["planned"] == 1000.0
    assert rows["Alpha"]["practical"] == 250.0
    assert rows["Beta"]["planned"] is None  # no lines matched Beta


# -- math & rows ---------------------------------------------------------------

def test_summary_math(fake_client):
    _seed(fake_client)
    out = json.loads(tools_reports_projects.project_budget())
    s = out["summary"]
    assert out["budgets_available"] is True
    assert s["projects"] == 2
    assert s["with_budget"] == 2
    assert s["budgets"] == 2  # PASX A + PASX B
    assert s["planned"] == 1900.0
    assert s["practical"] == 1400.0
    assert s["burn_pct"] == 73.7
    assert s["cost"] == 8100.0
    assert s["uncaptured_cost"] == 6700.0  # Alpha: 8000 cost vs 1300 booked
    assert s["off_track"] == 0 and s["at_risk"] == 1 and s["on_track"] == 1
    assert s["over_plan_lines"] == 1


def test_rows_sorted_and_shaped(fake_client):
    _seed(fake_client)
    out = json.loads(tools_reports_projects.project_budget())
    rows = out["breakdown"]["projects"]
    assert [r["project"] for r in rows] == ["Alpha", "Beta"]  # at_risk first
    assert rows[0] == {
        "project_id": 1,
        "project": "Alpha", "manager": "Mai", "customer": "Acme",
        "budgets": ["PASX A"], "lines": 2,
        "planned": 1500.0, "practical": 1300.0, "burn_pct": 86.7,
        "cost": 8000.0, "uncaptured_cost": 6700.0,
        "over_plan_lines": 1, "verdict": "at_risk",
    }
    assert rows[1]["verdict"] == "on_track"
    assert rows[1]["burn_pct"] == 25.0
    assert rows[1]["uncaptured_cost"] == 0.0


def test_drill_lines_single_project(fake_client):
    _seed(fake_client, projects=[PROJECTS[0]], lines=LINES[:2],
          cost=AGG_COST[:1])
    out = json.loads(tools_reports_projects.project_budget(project="Alpha"))
    lines = out["breakdown"]["lines"]
    assert [ln["line"] for ln in lines] == ["CP nhân công", "CP bảo hành"]
    top = lines[0]
    assert top == {
        "line": "CP nhân công", "budget": "PASX A",
        "planned": 1000.0, "practical": 1300.0, "theoretical": 950.0,
        "burn_pct": 130.0, "over_plan": True,
        "date_from": "2025-03-01", "date_to": "2026-07-31",
    }
    assert lines[1]["over_plan"] is False
    assert any(h.startswith("top line: CP nhân công")
               for h in out["highlights"])


def test_drill_respects_top_n(fake_client):
    _seed(fake_client, projects=[PROJECTS[0]], lines=LINES[:2],
          cost=AGG_COST[:1])
    out = json.loads(tools_reports_projects.project_budget(
        project="Alpha", top_n=1))
    assert len(out["breakdown"]["lines"]) == 1
    assert out["breakdown"]["lines"][0]["line"] == "CP nhân công"


# -- risks & degradation ---------------------------------------------------------

def test_risk_emission(fake_client):
    _seed(fake_client)
    out = json.loads(tools_reports_projects.project_budget())
    by_code = {r["code"]: r for r in out["risks"]}
    assert by_code["line_over_plan"]["count"] == 1
    assert by_code["spend_outside_budget"]["count"] == 1  # Alpha only
    assert "over_budget" not in by_code  # nothing off_track
    assert all(r["message"] for r in out["risks"])


def test_off_track_project_emits_over_budget(fake_client):
    _seed(fake_client, projects=[PROJECTS[0]], lines=[LINES[0]],
          cost=AGG_COST[:1])
    out = json.loads(tools_reports_projects.project_budget())
    # Alpha: 1300 practical / 1000 planned = 130% -> off_track
    assert out["summary"]["off_track"] == 1
    risk = next(r for r in out["risks"] if r["code"] == "over_budget")
    assert risk["count"] == 1


def test_no_budget_risk(fake_client):
    _seed(fake_client, lines=LINES[:2])  # Beta has no budget lines
    out = json.loads(tools_reports_projects.project_budget())
    risk = next(r for r in out["risks"] if r["code"] == "no_budget")
    assert risk["count"] == 1
    rows = {r["project"]: r for r in out["breakdown"]["projects"]}
    assert rows["Beta"]["planned"] is None
    assert rows["Beta"]["verdict"] == "n/a"
    assert out["summary"]["with_budget"] == 1


def test_fetch_lines_recovers_from_faulting_first_candidate(fake_client, monkeypatch):
    # budget.line becomes usable (schema resolves an amount field, the
    # search_count existence probe succeeds) but its actual line read still
    # faults on a real server (e.g. a dotted extra-domain field the instance
    # doesn't support) -- fetch_lines() must catch that OdooError and fall
    # through to the next candidate (mirroring budget_by_project), not crash.
    fake_client.fields_responses["budget.line"] = {
        "project_id": {}, "account_id": {}, "planned_amount": {}}
    _seed(fake_client)  # crossovered.budget.lines is the working fallback

    real_search_read = fake_client.search_read

    def faulting_search_read(model, *args, **kwargs):
        if model == "budget.line":
            raise OdooError("Invalid field budget_analytic_id.budget_type")
        return real_search_read(model, *args, **kwargs)

    monkeypatch.setattr(fake_client, "search_read", faulting_search_read)

    out = json.loads(tools_reports_projects.project_budget())
    assert out["budgets_available"] is True
    lines_call = next(c for c in fake_client.calls
                       if c["method"] == "search_read"
                       and c["model"] == "crossovered.budget.lines")
    assert lines_call is not None


def test_budgets_unavailable_degrades(fake_client):
    _seed(fake_client)
    fake_client.error_models = {"budget.line", "crossovered.budget.lines"}
    out = json.loads(tools_reports_projects.project_budget())
    assert out["budgets_available"] is False
    assert any(r["code"] == "budgets_unavailable" for r in out["risks"])
    s = out["summary"]
    assert s["planned"] is None and s["practical"] is None
    assert s["burn_pct"] is None
    assert s["cost"] == 8100.0  # analytic cost still reported
    rows = out["breakdown"]["projects"]
    assert all(r["verdict"] == "n/a" for r in rows)
    assert [r["project"] for r in rows] == ["Alpha", "Beta"]  # cost desc


def test_mixed_companies_risk(fake_client):
    projects = [dict(PROJECTS[0]),
                dict(PROJECTS[1], company_id=[2, "Second Co"])]
    _seed(fake_client, projects=projects)
    out = json.loads(tools_reports_projects.project_budget())
    risk = next(r for r in out["risks"] if r["code"] == "mixed_companies")
    assert risk["count"] == 2
    assert out["summary"]["companies"] == ["Main Co", "Second Co"]


def test_no_projects_short_circuits(fake_client):
    _seed(fake_client, projects=[])
    out = json.loads(tools_reports_projects.project_budget())
    assert out["summary"]["projects"] == 0
    assert out["breakdown"]["projects"] == []
    assert out["risks"] == []
    assert not any(c["model"] == "crossovered.budget.lines"
                   for c in fake_client.calls if c["method"] == "search_read")
    assert not any(c["method"] == "aggregate_records"
                   for c in fake_client.calls)


# -- envelope ---------------------------------------------------------------------

def test_envelope_shape(fake_client, monkeypatch):
    monkeypatch.setattr(budget, "today_in_tz",
                        lambda offset: dt.date(2026, 7, 13))
    _seed(fake_client)
    out = json.loads(tools_reports_projects.project_budget())
    assert out["tool"] == "project_budget"
    assert out["as_of"] == "2026-07-13"
    assert list(out) == ["tool", "as_of", "filters", "thresholds",
                         "budgets_available", "summary", "breakdown",
                         "highlights", "risks"]
    assert out["filters"] == {"project": None, "manager": None,
                              "customer": None}
    assert out["thresholds"] == {"burn_pct_at_risk": 80.0,
                                 "burn_pct_off_track": 100.0}
    assert out["highlights"][0] == (
        "1400.0 spent of 1900.0 planned across 2 project(s)")
    assert "worst burn: Alpha at 86.7%" in out["highlights"]


def test_budget_rows_carry_project_id(fake_client):
    _seed(fake_client)
    out = json.loads(tools_reports_projects.project_budget())
    first = out["breakdown"]["projects"][0]
    assert isinstance(first["project_id"], int)
    seeded = {p["id"] for p in
              fake_client.search_responses["project.project"]}
    assert first["project_id"] in seeded

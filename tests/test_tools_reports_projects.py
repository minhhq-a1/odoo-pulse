# tests/test_tools_reports_projects.py
import datetime as dt
import json

import pytest

from odoo_pulse import tools_reports_projects
from odoo_pulse.odoo_client import OdooError
from odoo_pulse.tools_reports_projects import (
    _budget_by_project,
    _validate_date,
    _verdict,
)


# -- helpers -----------------------------------------------------------------

def test_validate_date_passthrough_and_error():
    assert _validate_date(None, "date_from") is None
    assert _validate_date("", "date_from") is None
    assert _validate_date("2026-07-01", "date_from") == "2026-07-01"
    with pytest.raises(OdooError, match="Invalid date_from"):
        _validate_date("notadate", "date_from")


def test_verdict_boundaries_and_worst_of_two():
    assert _verdict(None, None, 80.0, 100.0) == ("on_track", None)
    assert _verdict(79.9, None, 80.0, 100.0) == ("on_track", 79.9)
    assert _verdict(80.0, None, 80.0, 100.0) == ("at_risk", 80.0)
    assert _verdict(99.9, None, 80.0, 100.0) == ("at_risk", 99.9)
    assert _verdict(100.0, None, 80.0, 100.0) == ("off_track", 100.0)
    assert _verdict(50.0, 120.0, 80.0, 100.0) == ("off_track", 120.0)
    assert _verdict(None, 85.0, 80.0, 100.0) == ("at_risk", 85.0)


# -- _budget_by_project --------------------------------------------------------

def test_budget_no_projects_short_circuits(fake_client):
    assert _budget_by_project(fake_client, [], {}) == ({}, False)
    assert fake_client.calls == []


def test_budget_probe_uses_rpc_not_fields_get(fake_client):
    # Both models "absent": search_count raises. fields_get would NOT raise
    # (the fake returns a default schema for any model) — this test pins
    # the probe order the spec requires.
    fake_client.error_models = {"budget.line", "crossovered.budget.lines"}
    budgets, available = _budget_by_project(fake_client, [1, 2], {1: 11, 2: 12})
    assert budgets == {} and available is False
    probed = [c["model"] for c in fake_client.calls
              if c["method"] == "search_count"]
    assert probed == ["budget.line", "crossovered.budget.lines"]  # major=18


def test_budget_probe_order_flips_on_17(fake_client):
    fake_client.major = 17
    fake_client.error_models = {"budget.line", "crossovered.budget.lines"}
    _budget_by_project(fake_client, [1], {1: 11})
    probed = [c["model"] for c in fake_client.calls
              if c["method"] == "search_count"]
    assert probed == ["crossovered.budget.lines", "budget.line"]


def test_budget_unresolvable_fields_degrade(fake_client):
    # Models "exist" (search_count returns the default 7) and the default
    # schema even has project_id — but no amount field resolves, so the
    # candidate is unusable -> ({}, False), no aggregate.
    budgets, available = _budget_by_project(fake_client, [1], {1: 11})
    assert budgets == {} and available is False
    assert not any(c["method"] == "aggregate_records"
                   for c in fake_client.calls)


def test_budget_matches_by_line_project_id(fake_client):
    # Line model carries project_id (custom field seen in the wild on
    # crossovered.budget.lines): match directly, no analytic-account hop.
    fake_client.fields_responses["budget.line"] = {
        "project_id": {}, "budget_amount": {}}
    fake_client.aggregate_responses_seq["budget.line"] = [[
        {"project_id": [1, "Alpha"], "budget_amount:sum": -10000.0},
        {"project_id": [2, "Beta"], "budget_amount:sum": 4000.0},
    ]]
    budgets, available = _budget_by_project(fake_client, [1, 2], {1: 11})
    assert available is True
    assert budgets == {1: 10000.0, 2: 4000.0}
    agg = fake_client.last("aggregate_records")
    assert agg["model"] == "budget.line"
    assert agg["group_by"] == ["project_id"]
    assert agg["measures"] == [("budget_amount", "sum")]
    assert ("project_id", "in", [1, 2]) in agg["domain"]
    # Revenue-type budgets must not count toward the expense budget.
    assert ("budget_analytic_id.budget_type", "!=", "revenue") in agg["domain"]


def test_budget_account_fallback_maps_shared_account(fake_client):
    # No project_id on the line model -> classic analytic-account matching;
    # two projects sharing one account each get the full amount (accepted
    # double-count caveat).
    fake_client.fields_responses["budget.line"] = {
        "account_id": {}, "budget_amount": {}}
    fake_client.aggregate_responses_seq["budget.line"] = [[
        {"account_id": [11, "AA Shared"], "budget_amount:sum": -10000.0}]]
    budgets, available = _budget_by_project(
        fake_client, [1, 2], {1: 11, 2: 11})
    assert available is True
    assert budgets == {1: 10000.0, 2: 10000.0}
    agg = fake_client.last("aggregate_records")
    assert agg["group_by"] == ["account_id"]
    assert ("account_id", "in", [11]) in agg["domain"]


def test_budget_project_id_wins_over_account_match(fake_client):
    # Both link styles resolve: the project aggregate runs first and its
    # value is authoritative per project; account matching fills the rest.
    fake_client.fields_responses["budget.line"] = {
        "project_id": {}, "account_id": {}, "budget_amount": {}}
    fake_client.aggregate_responses_seq["budget.line"] = [
        [{"project_id": [1, "Alpha"], "budget_amount:sum": -8000.0}],
        [{"account_id": [11, "AA Alpha"], "budget_amount:sum": -5000.0},
         {"account_id": [12, "AA Beta"], "budget_amount:sum": -3000.0}],
    ]
    budgets, available = _budget_by_project(
        fake_client, [1, 2], {1: 11, 2: 12})
    assert available is True
    assert budgets == {1: 8000.0, 2: 3000.0}
    aggs = [c for c in fake_client.calls
            if c["method"] == "aggregate_records"]
    assert [a["group_by"] for a in aggs] == [["project_id"], ["account_id"]]


def test_budget_crossovered_filters_confirmed(fake_client):
    fake_client.major = 17
    fake_client.fields_responses["crossovered.budget.lines"] = {
        "analytic_account_id": {}, "planned_amount": {}}
    fake_client.aggregate_responses_seq["crossovered.budget.lines"] = [[
        {"analytic_account_id": [11, "AA"], "planned_amount:sum": -5000.0}]]
    budgets, available = _budget_by_project(fake_client, [1], {1: 11})
    assert budgets == {1: 5000.0} and available is True
    agg = fake_client.last("aggregate_records")
    assert agg["model"] == "crossovered.budget.lines"
    assert ("crossovered_budget_id.state", "in",
            ["confirm", "validate", "done"]) in agg["domain"]


# -- portfolio fixtures --------------------------------------------------------

PROJECT_FIELDS = {"name": {}, "allocated_hours": {}, "account_id": {}}
PROJECTS = [
    {"id": 1, "name": "Alpha", "user_id": [3, "Mai"],
     "partner_id": [9, "Acme"], "company_id": [1, "Main Co"],
     "allocated_hours": 100.0, "account_id": [11, "AA Alpha"]},
    {"id": 2, "name": "Beta", "user_id": [4, "Nam"],
     "partner_id": [10, "Globex"], "company_id": [1, "Main Co"],
     "allocated_hours": 50.0, "account_id": [12, "AA Beta"]},
]
AGG_HOURS = [{"project_id": [1, "Alpha"], "unit_amount:sum": 90.0},
             {"project_id": [2, "Beta"], "unit_amount:sum": 10.0}]
AGG_COST = [{"account_id": [11, "AA Alpha"], "amount:sum": -8000.0},
            {"account_id": [12, "AA Beta"], "amount:sum": -1000.0}]
AGG_REVENUE = [{"account_id": [11, "AA Alpha"], "amount:sum": 12000.0}]


def _seed_portfolio(fake):
    """Two projects; queue order is the in-thunk order: hours, cost, revenue.
    Budgets stay unavailable: the probe search_count 'succeeds' (default 7)
    but the default schema resolves no amount field -> ({}, False)."""
    fake.fields_responses["project.project"] = PROJECT_FIELDS
    fake.search_responses["project.project"] = PROJECTS
    fake.aggregate_responses_seq["account.analytic.line"] = [
        list(AGG_HOURS), list(AGG_COST), list(AGG_REVENUE)]


# -- portfolio happy path ------------------------------------------------------

def test_portfolio_filters_land_in_project_domain(fake_client):
    _seed_portfolio(fake_client)
    tools_reports_projects.project_profitability(
        project="alp", manager="mai", customer="acme")
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read"
                and c["model"] == "project.project")
    for cond in [("active", "=", True), ("name", "ilike", "alp"),
                 ("user_id.name", "ilike", "mai"),
                 ("partner_id.name", "ilike", "acme")]:
        assert cond in call["domain"]
    assert call["limit"] == 200 and call["order"] == "name"


def test_analytic_domains(fake_client):
    _seed_portfolio(fake_client)
    tools_reports_projects.project_profitability()
    aggs = [c for c in fake_client.calls
            if c["method"] == "aggregate_records"
            and c["model"] == "account.analytic.line"]
    assert len(aggs) == 3  # hours, cost, revenue — no drill for 2 projects
    hours, cost, revenue = aggs
    assert hours["group_by"] == ["project_id"]
    assert hours["measures"] == [("unit_amount", "sum")]
    assert ("project_id", "in", [1, 2]) in hours["domain"]
    for agg in (cost, revenue):
        assert agg["group_by"] == ["account_id"]
        assert agg["measures"] == [("amount", "sum")]
        assert ("account_id", "in", [11, 12]) in agg["domain"]
    assert ("amount", "<", 0) in cost["domain"]
    assert ("amount", ">", 0) in revenue["domain"]


def test_summary_and_margin_math(fake_client):
    _seed_portfolio(fake_client)
    out = json.loads(tools_reports_projects.project_profitability())
    s = out["summary"]
    assert s["projects"] == 2
    assert s["hours_logged"] == 100.0
    assert s["hours_allocated"] == 150.0
    assert s["hours_burn_pct"] == 66.7
    assert s["cost"] == 9000.0
    assert s["revenue"] == 12000.0
    assert s["margin"] == 3000.0
    assert s["margin_pct"] == 25.0
    assert s["off_track"] == 0 and s["at_risk"] == 1 and s["on_track"] == 1
    assert "budget" not in s and "budget_burn_pct" not in s
    assert "companies" not in s
    assert out["budgets_available"] is False
    assert out["burn_evaluated"] is True


def test_rows_sorted_by_verdict_then_burn(fake_client):
    _seed_portfolio(fake_client)
    out = json.loads(tools_reports_projects.project_profitability())
    rows = out["breakdown"]["projects"]
    assert [r["project"] for r in rows] == ["Alpha", "Beta"]
    alpha = rows[0]
    assert alpha == {
        "project_id": 1,
        "project": "Alpha", "manager": "Mai", "customer": "Acme",
        "hours_logged": 90.0, "hours_allocated": 100.0,
        "hours_burn_pct": 90.0, "cost": 8000.0, "revenue": 12000.0,
        "margin": 4000.0, "budget": None, "budget_burn_pct": None,
        "verdict": "at_risk",
    }
    assert rows[1]["verdict"] == "on_track"
    assert rows[1]["revenue"] == 0.0 and rows[1]["margin"] == -1000.0


def test_budget_burn_feeds_verdict(fake_client):
    _seed_portfolio(fake_client)
    fake_client.fields_responses["budget.line"] = {
        "account_id": {}, "budget_amount": {}}
    fake_client.aggregate_responses_seq["budget.line"] = [[
        {"account_id": [11, "AA Alpha"], "budget_amount:sum": 8000.0},
        {"account_id": [12, "AA Beta"], "budget_amount:sum": 10000.0}]]
    out = json.loads(tools_reports_projects.project_profitability())
    s = out["summary"]
    assert out["budgets_available"] is True
    assert s["budget"] == 18000.0
    assert s["budget_burn_pct"] == 50.0
    rows = {r["project"]: r for r in out["breakdown"]["projects"]}
    # Alpha: cost 8000 / budget 8000 = 100% -> off_track beats 90% hours burn
    assert rows["Alpha"]["budget_burn_pct"] == 100.0
    assert rows["Alpha"]["verdict"] == "off_track"
    assert rows["Beta"]["budget_burn_pct"] == 10.0
    assert s["off_track"] == 1


def test_envelope_shape(fake_client, monkeypatch):
    monkeypatch.setattr(tools_reports_projects, "today_in_tz",
                        lambda offset: dt.date(2026, 7, 11))
    _seed_portfolio(fake_client)
    out = json.loads(tools_reports_projects.project_profitability())
    assert out["tool"] == "project_profitability"
    assert out["as_of"] == "2026-07-11"
    assert list(out) == ["tool", "as_of", "filters", "thresholds",
                         "budgets_available", "burn_evaluated",
                         "summary", "breakdown", "highlights", "risks"]
    assert out["filters"] == {"project": None, "manager": None,
                              "customer": None, "date_from": None,
                              "date_to": None}
    assert out["thresholds"] == {"burn_pct_at_risk": 80.0,
                                 "burn_pct_off_track": 100.0}
    assert out["highlights"][0] == (
        "100.0 h logged across 2 project(s), cost 9000.0, margin 3000.0")


# -- date filters ---------------------------------------------------------------

def test_date_filter_disables_burn(fake_client):
    _seed_portfolio(fake_client)
    out = json.loads(tools_reports_projects.project_profitability(
        date_from="2026-07-01", date_to="2026-07-31"))
    assert out["burn_evaluated"] is False
    s = out["summary"]
    assert s["hours_burn_pct"] is None
    assert s["off_track"] == 0 and s["at_risk"] == 0 and s["on_track"] == 0
    rows = out["breakdown"]["projects"]
    assert all(r["verdict"] == "n/a" for r in rows)
    assert all(r["hours_burn_pct"] is None for r in rows)
    assert all(r["budget_burn_pct"] is None for r in rows)
    assert [r["project"] for r in rows] == ["Alpha", "Beta"]  # cost desc
    assert out["filters"]["date_from"] == "2026-07-01"


def test_date_bounds_hit_analytic_domains_only(fake_client):
    _seed_portfolio(fake_client)
    tools_reports_projects.project_profitability(
        date_from="2026-07-01", date_to="2026-07-31")
    aggs = [c for c in fake_client.calls
            if c["method"] == "aggregate_records"
            and c["model"] == "account.analytic.line"]
    assert aggs
    for agg in aggs:
        assert ("date", ">=", "2026-07-01") in agg["domain"]
        assert ("date", "<=", "2026-07-31") in agg["domain"]
    proj = next(c for c in fake_client.calls
                if c["method"] == "search_read"
                and c["model"] == "project.project")
    assert not any(cond[0] == "date" for cond in proj["domain"])


def test_invalid_date_is_clean_error(fake_client):
    _seed_portfolio(fake_client)
    out = json.loads(tools_reports_projects.project_profitability(
        date_from="notadate"))
    assert out["error"] == "Invalid date_from 'notadate': expected YYYY-MM-DD"
    # validated BEFORE any domain was built -> no RPC happened
    assert not any(c["method"] == "search_read" for c in fake_client.calls)


# -- drill mode ------------------------------------------------------------------

def test_drill_mode_single_match(fake_client):
    fake_client.fields_responses["project.project"] = PROJECT_FIELDS
    fake_client.search_responses["project.project"] = [PROJECTS[0]]
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [dict(AGG_HOURS[0])], [dict(AGG_COST[0])], [dict(AGG_REVENUE[0])],
        [{"employee_id": [21, "Chi"], "unit_amount:sum": 60.0},
         {"employee_id": [22, "Duy"], "unit_amount:sum": 30.0}],
        [{"task_id": [31, "Build API"], "unit_amount:sum": 55.0}],
    ]
    out = json.loads(tools_reports_projects.project_profitability(
        project="Alpha", top_n=2))
    assert out["breakdown"]["by_employee"] == [
        {"employee": "Chi", "hours": 60.0},
        {"employee": "Duy", "hours": 30.0}]
    assert out["breakdown"]["by_task"] == [
        {"task": "Build API", "hours": 55.0}]
    drill = [c for c in fake_client.calls
             if c["method"] == "aggregate_records"
             and c["group_by"] in (["employee_id"], ["task_id"])]
    assert len(drill) == 2
    for c in drill:
        assert c["limit"] == 2
        assert c["order"] == "unit_amount:sum desc"
        assert ("project_id", "=", 1) in c["domain"]
    assert "top contributor: Chi (60.0 h)" in out["highlights"]


def test_multi_match_has_no_drill(fake_client):
    _seed_portfolio(fake_client)
    out = json.loads(tools_reports_projects.project_profitability(project="a"))
    assert "by_employee" not in out["breakdown"]
    assert "by_task" not in out["breakdown"]
    aggs = [c for c in fake_client.calls
            if c["method"] == "aggregate_records"
            and c["model"] == "account.analytic.line"]
    assert len(aggs) == 3  # no drill aggregates were issued


# -- risks & edges ----------------------------------------------------------------

def test_risk_emission(fake_client):
    projects = [
        dict(PROJECTS[0]),
        # Hours logged but no allocation and no analytic account,
        # in a second company.
        {"id": 3, "name": "Gamma", "user_id": None, "partner_id": None,
         "company_id": [2, "Second Co"], "allocated_hours": 0.0,
         "account_id": None},
    ]
    fake_client.fields_responses["project.project"] = PROJECT_FIELDS
    fake_client.search_responses["project.project"] = projects
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"project_id": [1, "Alpha"], "unit_amount:sum": 120.0},
         {"project_id": [3, "Gamma"], "unit_amount:sum": 5.0}],
        [{"account_id": [11, "AA Alpha"], "amount:sum": -8000.0}],
        [],  # no revenue -> Alpha margin is -8000
    ]
    out = json.loads(tools_reports_projects.project_profitability())
    by_code = {r["code"]: r for r in out["risks"]}
    # Alpha: 120/100 = 120% -> off_track -> over_budget risk
    assert by_code["over_budget"]["count"] == 1
    assert by_code["negative_margin"]["count"] == 1
    assert by_code["no_allocation"]["count"] == 1
    assert by_code["no_analytic_account"]["count"] == 1
    assert by_code["mixed_companies"]["count"] == 2
    assert out["summary"]["companies"] == ["Main Co", "Second Co"]
    assert out["summary"]["margin_pct"] is None  # revenue == 0
    assert all(r["message"] for r in out["risks"])


def test_truncation_risk(fake_client):
    rows = [dict(PROJECTS[0], id=i, name=f"P{i:03d}") for i in range(1, 201)]
    fake_client.fields_responses["project.project"] = PROJECT_FIELDS
    fake_client.search_responses["project.project"] = rows
    fake_client.search_count_responses["project.project"] = 250
    fake_client.aggregate_responses_seq["account.analytic.line"] = [[], [], []]
    out = json.loads(tools_reports_projects.project_profitability())
    assert out["summary"]["truncated"] is True
    assert out["summary"]["total_matching"] == 250
    risk = next(r for r in out["risks"] if r["code"] == "truncated_data")
    assert risk["count"] == 50


def test_no_projects_short_circuits(fake_client):
    fake_client.fields_responses["project.project"] = PROJECT_FIELDS
    fake_client.search_responses["project.project"] = []
    out = json.loads(tools_reports_projects.project_profitability())
    assert out["summary"]["projects"] == 0
    assert out["summary"]["hours_logged"] == 0.0
    assert out["summary"]["margin_pct"] is None
    assert out["breakdown"]["projects"] == []
    assert out["risks"] == []
    assert not any(c["method"] == "aggregate_records"
                   for c in fake_client.calls)


def test_timesheet_module_absent(fake_client):
    fake_client.fields_responses["project.project"] = PROJECT_FIELDS
    fake_client.search_responses["project.project"] = PROJECTS
    fake_client.fields_responses["account.analytic.line"] = {"name": {}}
    out = json.loads(tools_reports_projects.project_profitability())
    assert "hr_timesheet" in out["error"]


def test_allocated_hours_field_absent(fake_client):
    # Very old / stripped install: no allocated_hours on project.project.
    fake_client.fields_responses["project.project"] = {
        "name": {}, "account_id": {}}
    fake_client.search_responses["project.project"] = [
        {k: v for k, v in PROJECTS[0].items() if k != "allocated_hours"}]
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"project_id": [1, "Alpha"], "unit_amount:sum": 30.0}],
        [{"account_id": [11, "AA Alpha"], "amount:sum": -100.0}],
        [], [], []]  # single match -> drill aggregates run too
    out = json.loads(tools_reports_projects.project_profitability())
    row = out["breakdown"]["projects"][0]
    assert row["hours_allocated"] == 0.0
    assert row["hours_burn_pct"] is None
    assert row["verdict"] == "on_track"  # nothing to burn against
    assert "no_allocation" in {r["code"] for r in out["risks"]}


def test_profitability_rows_carry_project_id(fake_client):
    _seed_portfolio(fake_client)
    out = json.loads(tools_reports_projects.project_profitability())
    first = out["breakdown"]["projects"][0]
    assert isinstance(first["project_id"], int)
    seeded = {p["id"] for p in
              fake_client.search_responses["project.project"]}
    assert first["project_id"] in seeded

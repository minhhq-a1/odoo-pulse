# tests/test_tools_reports_projects.py
import datetime as dt
import json

import pytest

from odoo_pulse import tools_reports_projects
from odoo_pulse.odoo_client import OdooError
from odoo_pulse.tools_reports_projects import (
    _budget_by_account,
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


# -- _budget_by_account ------------------------------------------------------

def test_budget_no_accounts_short_circuits(fake_client):
    assert _budget_by_account(fake_client, []) == ({}, False)
    assert fake_client.calls == []


def test_budget_probe_uses_rpc_not_fields_get(fake_client):
    # Both models "absent": search_count raises. fields_get would NOT raise
    # (the fake returns a default schema for any model) — this test pins
    # the probe order the spec requires.
    fake_client.error_models = {"budget.line", "crossovered.budget.lines"}
    budgets, available = _budget_by_account(fake_client, [11, 12])
    assert budgets == {} and available is False
    probed = [c["model"] for c in fake_client.calls
              if c["method"] == "search_count"]
    assert probed == ["budget.line", "crossovered.budget.lines"]  # major=18


def test_budget_probe_order_flips_on_17(fake_client):
    fake_client.major = 17
    fake_client.error_models = {"budget.line", "crossovered.budget.lines"}
    _budget_by_account(fake_client, [11])
    probed = [c["model"] for c in fake_client.calls
              if c["method"] == "search_count"]
    assert probed == ["crossovered.budget.lines", "budget.line"]


def test_budget_unresolvable_fields_degrade(fake_client):
    # Models "exist" (search_count returns the default 7) but the default
    # schema has none of the candidate fields -> ({}, False), no aggregate.
    budgets, available = _budget_by_account(fake_client, [11])
    assert budgets == {} and available is False
    assert not any(c["method"] == "aggregate_records"
                   for c in fake_client.calls)


def test_budget_sums_absolute_per_account(fake_client):
    fake_client.fields_responses["budget.line"] = {
        "account_id": {}, "budget_amount": {}}
    fake_client.aggregate_responses_seq["budget.line"] = [[
        {"account_id": [11, "AA Alpha"], "budget_amount:sum": -10000.0},
        {"account_id": [12, "AA Beta"], "budget_amount:sum": 4000.0},
    ]]
    budgets, available = _budget_by_account(fake_client, [11, 12])
    assert available is True
    assert budgets == {11: 10000.0, 12: 4000.0}
    agg = fake_client.last("aggregate_records")
    assert agg["model"] == "budget.line"
    assert agg["group_by"] == ["account_id"]
    assert agg["measures"] == [("budget_amount", "sum")]
    assert ("account_id", "in", [11, 12]) in agg["domain"]
    # Revenue-type budgets must not count toward the expense budget.
    assert ("budget_analytic_id.budget_type", "!=", "revenue") in agg["domain"]


def test_budget_crossovered_filters_confirmed(fake_client):
    fake_client.major = 17
    fake_client.fields_responses["crossovered.budget.lines"] = {
        "analytic_account_id": {}, "planned_amount": {}}
    fake_client.aggregate_responses_seq["crossovered.budget.lines"] = [[
        {"analytic_account_id": [11, "AA"], "planned_amount:sum": -5000.0}]]
    budgets, available = _budget_by_account(fake_client, [11])
    assert budgets == {11: 5000.0} and available is True
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
    but the default schema has no candidate fields -> ({}, False)."""
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

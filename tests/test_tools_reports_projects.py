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

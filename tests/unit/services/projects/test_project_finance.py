# tests/test_project_finance.py
"""Direct tests for the canonical analytic cost/revenue classifier.

profitability.py, health.py (portfolio_health) and dashboard.py (core
section) all delegate to this module so the three surfaces can never
disagree on what counts as cost vs revenue for the same analytic lines.
"""

import pytest

from odoo_pulse.core.errors import OdooError
from odoo_pulse.services.projects.finance import (
    AnalyticMoneyResult,
    analytic_bucket,
    analytic_money,
)


# -- analytic_money: empty scope ----------------------------------------------

def test_empty_accounts_return_not_evaluated_without_rpc(fake_client):
    result = analytic_money(fake_client, [])
    assert result == AnalyticMoneyResult({}, {}, "not_evaluated")
    assert fake_client.calls == []


# -- analytic_money: odoo classifier ------------------------------------------

def test_odoo_classifier_uses_loss_then_revenue_domains_and_nets_amounts(
    fake_client,
):
    fake_client.fields_responses["account.analytic.line"] = {
        "analytic_profitability": {},
    }
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"account_id": [5, "AA"], "amount:sum": -80.0}],
        [{"account_id": [5, "AA"], "amount:sum": 80.0}],
    ]

    result = analytic_money(fake_client, [5])

    assert result == AnalyticMoneyResult(
        cost_by_account={5: 80.0},
        revenue_by_account={5: 80.0},
        classification="odoo_profitability",
    )
    calls = [
        call for call in fake_client.calls
        if call["method"] == "aggregate_records"
    ]
    assert ("analytic_profitability", "=", "loss") in calls[0]["domain"]
    assert ("analytic_profitability", "=", "revenue") in calls[1]["domain"]
    assert not any(
        leaf[:2] == ("amount", "<") or leaf[:2] == ("amount", ">")
        for call in calls for leaf in call["domain"]
        if isinstance(leaf, tuple)
    )


def test_odoo_classifier_does_not_abs_or_clamp_reversals(fake_client):
    # A reversed cost line (positive) and a reversed revenue line (negative)
    # -- the classifier domain, not the amount's sign, decides the bucket,
    # so the net can legitimately come out negative in either bucket.
    fake_client.fields_responses["account.analytic.line"] = {
        "analytic_profitability": {},
    }
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"account_id": [5, "AA"], "amount:sum": 20.0}],
        [{"account_id": [5, "AA"], "amount:sum": -20.0}],
    ]

    result = analytic_money(fake_client, [5])

    assert result == AnalyticMoneyResult(
        cost_by_account={5: -20.0},
        revenue_by_account={5: -20.0},
        classification="odoo_profitability",
    )


def test_extra_domain_is_appended_to_both_classifier_aggregates(fake_client):
    fake_client.fields_responses["account.analytic.line"] = {
        "analytic_profitability": {},
    }
    fake_client.aggregate_responses_seq["account.analytic.line"] = [[], []]

    analytic_money(fake_client, [5], extra_domain=[("company_id", "=", 1)])

    calls = [
        call for call in fake_client.calls
        if call["method"] == "aggregate_records"
    ]
    assert len(calls) == 2
    for call in calls:
        assert ("company_id", "=", 1) in call["domain"]


# -- analytic_money: sign fallback --------------------------------------------

def test_missing_classifier_uses_sign_fallback_and_reports_it(fake_client):
    # account.analytic.line has no analytic_profitability field on this
    # instance -- the fake's default schema already omits it.
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"account_id": [5, "AA"], "amount:sum": -40.0}],
        [{"account_id": [5, "AA"], "amount:sum": 100.0}],
    ]

    result = analytic_money(fake_client, [5])

    assert result == AnalyticMoneyResult(
        cost_by_account={5: 40.0},
        revenue_by_account={5: 100.0},
        classification="sign_fallback",
    )
    calls = [
        call for call in fake_client.calls
        if call["method"] == "aggregate_records"
    ]
    assert ("amount", "<", 0) in calls[0]["domain"]
    assert ("amount", ">", 0) in calls[1]["domain"]


# -- analytic_bucket -----------------------------------------------------------

def test_analytic_bucket_uses_odoo_classifier_not_amount_sign():
    # The amount's sign disagrees with the classifier on both rows --
    # analytic_bucket must follow analytic_profitability, not amount.
    loss_row = {"analytic_profitability": "loss", "amount": 500.0}
    revenue_row = {"analytic_profitability": "revenue", "amount": -500.0}
    other_row = {"analytic_profitability": "other", "amount": 500.0}

    assert analytic_bucket(loss_row, "odoo_profitability") == "cost"
    assert analytic_bucket(revenue_row, "odoo_profitability") == "revenue"
    assert analytic_bucket(other_row, "odoo_profitability") is None


def test_analytic_bucket_fallback_uses_amount_sign_and_ignores_zero():
    assert analytic_bucket({"amount": -5.0}, "sign_fallback") == "cost"
    assert analytic_bucket({"amount": 5.0}, "sign_fallback") == "revenue"
    assert analytic_bucket({"amount": 0.0}, "sign_fallback") is None
    assert analytic_bucket({}, "sign_fallback") is None


# -- fault propagation ----------------------------------------------------------

def test_present_classifier_aggregate_fault_propagates(fake_client):
    # analytic_profitability IS present (fields_get resolves clean, so
    # classification is odoo_profitability) but the aggregate call itself
    # faults -- must reach the caller as OdooError, never fall back.
    fake_client.fields_responses["account.analytic.line"] = {
        "analytic_profitability": {},
    }
    fake_client.error_models.add("account.analytic.line")

    with pytest.raises(OdooError):
        analytic_money(fake_client, [5])

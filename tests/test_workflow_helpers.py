# tests/test_workflow_helpers.py
from __future__ import annotations

import datetime as dt

import pytest

from odoo_pulse.odoo_client import OdooError
from odoo_pulse.workflow_helpers import (
    build_report,
    distinct_companies,
    parse_deadline,
    resolve_company_id,
    resolve_user_names,
    today_in_tz,
    totals_by_currency,
    trend_direction,
)


def test_today_in_tz_returns_a_date():
    assert isinstance(today_in_tz(7), dt.date)


def test_parse_deadline_parses_date_prefix():
    assert parse_deadline("2026-06-30 14:00:00") == dt.date(2026, 6, 30)


def test_parse_deadline_none_on_falsy():
    assert parse_deadline(False) is None
    assert parse_deadline("") is None
    assert parse_deadline(None) is None


def test_resolve_user_names_empty_ids_makes_no_call(fake_client):
    assert resolve_user_names(fake_client, []) == {}
    assert fake_client.calls == []


def test_resolve_user_names_maps_ids_to_names_archived_aware(fake_client):
    fake_client.execute_kw_responses[("res.users", "search_read")] = [
        {"id": 10, "name": "Alice"},
        {"id": 11, "name": "Bob"},
    ]
    out = resolve_user_names(fake_client, [10, 11, 10])
    assert out == {10: "Alice", 11: "Bob"}
    call = fake_client.last("search_read")
    assert call["model"] == "res.users"
    assert call["kwargs"]["context"] == {"active_test": False}


def test_build_report_has_stable_envelope():
    report = build_report(
        "sprint_health",
        dt.date(2026, 6, 30),
        summary={"total": 3},
        breakdown={"by_stage": []},
        highlights=["x"],
        risks=[{"code": "c", "count": 1, "message": "m"}],
        extra={"sprint_id": 12},
    )
    assert list(report.keys()) == [
        "tool", "as_of", "sprint_id", "summary", "breakdown", "highlights", "risks",
    ]
    assert report["tool"] == "sprint_health"
    assert report["as_of"] == "2026-06-30"
    assert report["sprint_id"] == 12


def test_build_report_defaults_empty_collections():
    report = build_report("t", "2026-01-01", summary={})
    assert report["breakdown"] == {}
    assert report["highlights"] == []
    assert report["risks"] == []


def test_resolve_company_id_passthrough_and_none(fake_client):
    assert resolve_company_id(fake_client, None) is None
    assert resolve_company_id(fake_client, "") is None
    assert resolve_company_id(fake_client, 3) == 3
    assert fake_client.calls == []  # no RPC for id/None


def test_resolve_company_id_by_name(fake_client):
    fake_client.search_responses["res.company"] = [{"id": 5, "name": "Acme VN"}]
    assert resolve_company_id(fake_client, "acme") == 5
    call = fake_client.last("search_read")
    assert call["model"] == "res.company"
    assert ("name", "ilike", "acme") in call["domain"]


def test_resolve_company_id_not_found_and_ambiguous(fake_client):
    fake_client.search_responses["res.company"] = []
    with pytest.raises(OdooError, match="No company matching"):
        resolve_company_id(fake_client, "nope")
    fake_client.search_responses["res.company"] = [
        {"id": 1, "name": "Acme VN"}, {"id": 2, "name": "Acme US"}]
    with pytest.raises(OdooError, match="Ambiguous company"):
        resolve_company_id(fake_client, "acme")


def test_distinct_companies():
    rows = [
        {"company_id": [1, "Acme VN"]},
        {"company_id": [2, "Acme US"]},
        {"company_id": [1, "Acme VN"]},
        {"company_id": False},
        {},
    ]
    assert distinct_companies(rows) == ["Acme US", "Acme VN"]


def test_totals_by_currency():
    rows = [
        {"amount_total": 100.0, "currency_id": [1, "USD"]},
        {"amount_total": 50.5, "currency_id": [1, "USD"]},
        {"amount_total": 2000.0, "currency_id": [2, "VND"]},
        {"amount_total": 7.0, "currency_id": False},
    ]
    assert totals_by_currency(rows, "amount_total") == {
        "USD": 150.5, "VND": 2000.0, "(unknown)": 7.0}


def test_trend_direction():
    assert trend_direction([1, 1, 1, 1]) == "flat"
    assert trend_direction([10, 10, 20, 20]) == "improving"
    assert trend_direction([20, 20, 10, 10]) == "declining"
    assert trend_direction([10, 11]) == "flat"          # too short
    assert trend_direction([0, 0, 5, 5]) == "improving"  # zero baseline
    assert trend_direction([0, 0, 0, 0]) == "flat"
    # custom threshold: +15% counts as improving only at threshold<=15
    assert trend_direction([100, 100, 115, 115], threshold_pct=20) == "flat"

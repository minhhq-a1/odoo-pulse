# tests/test_workflow_helpers.py
from __future__ import annotations

import datetime as dt

from odoo_pulse.workflow_helpers import (
    build_report,
    parse_deadline,
    resolve_user_names,
    today_in_tz,
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

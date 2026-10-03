# tests/test_workflow_helpers.py
from __future__ import annotations

import datetime as dt
import threading

import pytest

from odoo_pulse.odoo_client import OdooConfigError, OdooError
from odoo_pulse.workflow_helpers import (
    apply_truncation,
    build_report,
    default_tz_offset,
    distinct_companies,
    ensure_field,
    m2o_id,
    m2o_name,
    optional_fields,
    parse_when,
    resolve_company_id,
    resolve_user_names,
    today_in_tz,
    totals_by_currency,
    trend_direction,
    truncation_risk,
    utc_bound,
)


def test_today_in_tz_returns_a_date():
    assert isinstance(today_in_tz(7), dt.date)


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
        "project_status_report",
        dt.date(2026, 6, 30),
        summary={"total": 3},
        breakdown={"by_stage": []},
        highlights=["x"],
        risks=[{"code": "c", "count": 1, "message": "m"}],
        extra={"project": "Acme"},
    )
    assert list(report.keys()) == [
        "tool", "as_of", "project", "summary", "breakdown", "highlights", "risks",
    ]
    assert report["tool"] == "project_status_report"
    assert report["as_of"] == "2026-06-30"
    assert report["project"] == "Acme"


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


def test_parse_when_shifts_utc_datetime_into_local_date():
    # 20:00 UTC on the 5th is already the 6th at UTC+7
    assert parse_when("2026-07-05 20:00:00", 7) == dt.date(2026, 7, 6)
    assert parse_when("2026-07-05 16:59:59", 7) == dt.date(2026, 7, 5)


def test_parse_when_passes_plain_dates_through_unshifted():
    assert parse_when("2026-07-05", 7) == dt.date(2026, 7, 5)


def test_parse_when_handles_falsy():
    assert parse_when(False, 7) is None
    assert parse_when(None, 7) is None


def test_utc_bound_is_local_midnight_expressed_in_utc():
    assert utc_bound(dt.date(2026, 7, 6), 7) == "2026-07-05 17:00:00"
    assert utc_bound(dt.date(2026, 7, 6), 0) == "2026-07-06 00:00:00"
    assert utc_bound(dt.date(2026, 7, 6), -5) == "2026-07-06 05:00:00"



class _SchemaClient:
    def fields_get(self, model, attributes=None):
        return {"name": {"type": "char"}}


def test_ensure_field_raises_with_hint_when_missing():
    with pytest.raises(OdooError, match="x_priority_score.*custom"):
        ensure_field(_SchemaClient(), "project.task", "x_priority_score",
                     hint="x_priority_score is a custom field; this instance "
                          "does not have it.")


def test_ensure_field_passes_when_present():
    class _C:
        def fields_get(self, model, attributes=None):
            return {"x_priority_score": {"type": "integer"}}

    ensure_field(_C(), "project.task", "x_priority_score")  # no raise



class _RichSchemaClient:
    def __init__(self, field_names):
        self._names = field_names

    def fields_get(self, model, attributes=None):
        return {name: {"type": "char"} for name in self._names}


def test_optional_fields_keeps_present_candidates_in_order():
    client = _RichSchemaClient(["name", "mobile", "phone"])
    assert optional_fields(client, "res.partner", ["mobile", "vat"]) == ["mobile"]


def test_optional_fields_empty_when_none_present():
    client = _RichSchemaClient(["name"])
    assert optional_fields(client, "project.task", ["x_priority_score"]) == []


def test_optional_fields_all_present_preserves_order():
    client = _RichSchemaClient(["b", "a", "c"])
    assert optional_fields(client, "x", ["a", "b"]) == ["a", "b"]


def test_gather_returns_values_in_key_order():
    from odoo_pulse.workflow_helpers import gather
    out = gather({"a": lambda: 1, "b": lambda: 2, "c": lambda: 3})
    assert out == {"a": 1, "b": 2, "c": 3}
    assert list(out) == ["a", "b", "c"]


def test_gather_captures_exceptions_as_values():
    from odoo_pulse.workflow_helpers import gather
    boom = ValueError("boom")

    def raiser():
        raise boom

    out = gather({"ok": lambda: 42, "bad": raiser})
    assert out["ok"] == 42
    assert out["bad"] is boom


def test_gather_single_thunk_runs_inline():
    from odoo_pulse.workflow_helpers import gather
    ident = gather({"only": threading.get_ident})
    assert ident["only"] == threading.get_ident()


def test_gather_runs_thunks_concurrently():
    from odoo_pulse.workflow_helpers import gather
    # Both thunks must be inside barrier.wait() at the same time; if gather
    # ran them sequentially the barrier would time out and raise.
    barrier = threading.Barrier(2, timeout=2)

    def thunk():
        barrier.wait()
        return "ok"

    out = gather({"a": thunk, "b": thunk})
    assert out == {"a": "ok", "b": "ok"}




def test_gather_strict_returns_values_in_key_order():
    from odoo_pulse.workflow_helpers import gather_strict
    out = gather_strict({"a": lambda: 1, "b": lambda: 2})
    assert out == {"a": 1, "b": 2}
    assert list(out) == ["a", "b"]


def test_gather_strict_reraises_first_exception_in_key_order():
    from odoo_pulse.workflow_helpers import gather_strict
    first, second = ValueError("first"), TypeError("second")

    def raise_first():
        raise first

    def raise_second():
        raise second

    with pytest.raises(ValueError) as exc:
        gather_strict({"a": raise_first, "b": raise_second, "c": lambda: 3})
    assert exc.value is first


def test_m2o_id_and_name():
    row = {"user_id": [7, "Ann"], "partner_id": False, "stage_id": None}
    assert m2o_id(row, "user_id") == 7
    assert m2o_id(row, "partner_id") is None
    assert m2o_id(row, "stage_id") is None
    assert m2o_id(row, "missing") is None
    assert m2o_name(row, "user_id") == "Ann"
    assert m2o_name(row, "partner_id") is None
    assert m2o_name(row, "partner_id", "(none)") == "(none)"
    assert m2o_name(row, "missing", "(unknown)") == "(unknown)"


_TRUNC = {"total_matching": 250, "fetched": 200, "missing": 50}


def test_truncation_risk_standard_wording():
    assert truncation_risk(_TRUNC, "invoices") == {
        "code": "truncated_data",
        "count": 50,
        "message": "Report covers only 200 of 250 matching invoices.",
    }


def test_truncation_risk_detail_code_and_message_override():
    risk = truncation_risk(_TRUNC, "task(s)", detail="Figures may be partial.")
    assert risk["message"] == (
        "Report covers only 200 of 250 matching task(s). Figures may be partial."
    )
    custom = truncation_risk(_TRUNC, "x", message="custom", code="truncated_trend")
    assert custom == {"code": "truncated_trend", "count": 50, "message": "custom"}


def test_apply_truncation_flags_summary():
    summary: dict = {}
    apply_truncation(summary, None)
    assert summary == {}
    apply_truncation(summary, _TRUNC)
    assert summary == {"truncated": True, "total_matching": 250}


def test_apply_truncation_with_prefix():
    summary: dict = {}
    apply_truncation(summary, _TRUNC, prefix="milestones")
    assert summary == {"milestones_truncated": True, "total_milestones_matching": 250}


def test_default_tz_offset_builtin_and_env(monkeypatch):
    monkeypatch.delenv("ODOO_DEFAULT_TZ_OFFSET", raising=False)
    assert default_tz_offset() == 7.0
    monkeypatch.setenv("ODOO_DEFAULT_TZ_OFFSET", "5.5")
    assert default_tz_offset() == 5.5
    monkeypatch.setenv("ODOO_DEFAULT_TZ_OFFSET", "banana")
    with pytest.raises(OdooConfigError, match="ODOO_DEFAULT_TZ_OFFSET"):
        default_tz_offset()


def test_utc_bound_supports_half_hour_offsets():
    from datetime import date

    assert utc_bound(date(2026, 3, 10), 5.5) == "2026-03-09 18:30:00"
    assert utc_bound(date(2026, 3, 10), 7) == "2026-03-09 17:00:00"


def test_none_offset_uses_configured_default_but_zero_means_utc(monkeypatch):
    from datetime import date

    monkeypatch.setenv("ODOO_DEFAULT_TZ_OFFSET", "5.5")
    d = date(2026, 3, 10)
    assert utc_bound(d, None) == utc_bound(d, 5.5)
    assert utc_bound(d, 0) == "2026-03-10 00:00:00"
    # 20:00 UTC is already the next local day at +5.5, still the same at UTC.
    assert parse_when("2026-03-10 20:00:00", None) == date(2026, 3, 11)
    assert parse_when("2026-03-10 20:00:00", 0) == date(2026, 3, 10)
    # Plain dates never shift, and the bare default stays UTC.
    assert parse_when("2026-03-10", None) == date(2026, 3, 10)
    assert parse_when("2026-03-10 20:00:00") == date(2026, 3, 10)


def test_today_in_tz_defaults_follow_env(monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("ODOO_DEFAULT_TZ_OFFSET", "-11")
    expected = datetime.now(timezone(timedelta(hours=-11))).date()
    assert today_in_tz() == expected
    assert today_in_tz(None) == expected

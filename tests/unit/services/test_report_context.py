import datetime as dt

import pytest

from odoo_pulse.core.errors import OdooError
from odoo_pulse.services import report_context


def fix_today(monkeypatch):
    monkeypatch.setattr(
        report_context, "today_in_tz", lambda offset: dt.date(2026, 6, 30)
    )


def test_context_without_company_performs_no_rpc(fake_client, monkeypatch):
    fix_today(monkeypatch)
    ctx = report_context.build_report_context(
        fake_client, timezone_offset=7, company=None
    )
    assert ctx.client is fake_client
    assert ctx.today == dt.date(2026, 6, 30)
    assert ctx.timezone_offset == 7
    assert ctx.company_id is None
    assert ctx.company_domain == ()
    assert fake_client.calls == []


def test_integer_company_needs_no_lookup(fake_client, monkeypatch):
    fix_today(monkeypatch)
    ctx = report_context.build_report_context(
        fake_client, timezone_offset=0, company=5
    )
    assert ctx.company_id == 5
    assert ctx.company_domain == (("company_id", "=", 5),)
    assert fake_client.calls == []


def test_named_company_is_resolved_once(fake_client, monkeypatch):
    fix_today(monkeypatch)
    fake_client.search_responses["res.company"] = [{"id": 8, "name": "Acme"}]
    ctx = report_context.build_report_context(
        fake_client, timezone_offset=7, company="acme"
    )
    assert ctx.company_id == 8
    lookups = [c for c in fake_client.calls if c["model"] == "res.company"]
    assert len(lookups) == 1


def test_company_filters_are_immutable_and_field_specific(fake_client, monkeypatch):
    fix_today(monkeypatch)
    ctx = report_context.build_report_context(
        fake_client, timezone_offset=7, company=9
    )
    assert ctx.company_domain == (("company_id", "=", 9),)
    assert ctx.company_filter("order_id.company_id") == (
        ("order_id.company_id", "=", 9),
    )
    with pytest.raises(TypeError):
        ctx.company_domain[0][0] = "other"


def test_named_company_errors_remain_strict(fake_client, monkeypatch):
    fix_today(monkeypatch)
    with pytest.raises(OdooError, match="No company"):
        report_context.build_report_context(
            fake_client, timezone_offset=7, company="missing"
        )
    fake_client.search_responses["res.company"] = [
        {"id": 1, "name": "Acme VN"},
        {"id": 2, "name": "Acme US"},
    ]
    with pytest.raises(OdooError, match="Ambiguous company"):
        report_context.build_report_context(
            fake_client, timezone_offset=7, company="acme"
        )

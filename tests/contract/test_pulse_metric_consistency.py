import datetime as dt

import pytest

from odoo_pulse.core.errors import OdooError
from odoo_pulse.services import pulse, report_context
from odoo_pulse.services.report_context import ReportContext
from odoo_pulse.services.sales import snapshot


PAYLOADS = {
    "sales": {"orders": 2, "revenue": 100.0, "currency": "USD"},
    "crm": {"new_leads": 3},
    "receivables": {
        "overdue_invoices": 1, "overdue_amount": 50.0, "currency": "USD",
    },
    "projects": {"overdue_tasks": 4},
    "hr": {"off_today": 1},
}

METRIC_NAMES = {
    "sales": "confirmed_sales",
    "crm": "new_leads",
    "receivables": "overdue_receivables",
    "projects": "overdue_open_tasks",
    "hr": "employees_off",
}


def install_metrics(monkeypatch, seen, failures=None):
    failures = failures or {}
    for section, attribute in METRIC_NAMES.items():
        def metric(context, _section=section, **kwargs):
            seen.append((_section, context, kwargs))
            failure = failures.get(_section)
            if failure is not None:
                raise failure
            return dict(PAYLOADS[_section])

        monkeypatch.setattr(pulse, attribute, metric)


def fixed_context(fake_client):
    return ReportContext(fake_client, dt.date(2026, 6, 30), 7, 5)


def test_pulse_composes_five_metrics_with_one_context(fake_client, monkeypatch):
    context = fixed_context(fake_client)
    monkeypatch.setattr(
        pulse, "build_report_context", lambda *args, **kwargs: context
    )
    seen = []
    install_metrics(monkeypatch, seen)

    result = pulse.build_business_pulse(fake_client)
    sections = result["breakdown"]["sections"]

    assert {name: {"available": True, **payload}
            for name, payload in PAYLOADS.items()} == sections
    assert {name for name, _, _ in seen} == set(PAYLOADS)
    assert all(received is context for _, received, _ in seen)


def test_pulse_degrades_only_one_odoo_error(fake_client, monkeypatch):
    context = fixed_context(fake_client)
    monkeypatch.setattr(
        pulse, "build_report_context", lambda *args, **kwargs: context
    )
    seen = []
    install_metrics(
        monkeypatch, seen,
        failures={"receivables": OdooError("missing accounting")},
    )

    sections = pulse.build_business_pulse(fake_client)["breakdown"]["sections"]
    assert sections["receivables"] == {
        "available": False, "reason": "missing accounting",
    }
    assert all(sections[name]["available"] for name in sections
               if name != "receivables")


def test_pulse_reraises_unexpected_metric_error(fake_client, monkeypatch):
    context = fixed_context(fake_client)
    monkeypatch.setattr(
        pulse, "build_report_context", lambda *args, **kwargs: context
    )
    seen = []
    install_metrics(
        monkeypatch, seen, failures={"crm": KeyError("bad shape")}
    )

    with pytest.raises(KeyError, match="bad shape"):
        pulse.build_business_pulse(fake_client)


def test_pulse_resolves_named_company_once(fake_client, monkeypatch):
    monkeypatch.setattr(
        report_context, "today_in_tz", lambda offset: dt.date(2026, 6, 30)
    )
    fake_client.search_responses["res.company"] = [{"id": 5, "name": "Acme"}]
    seen = []
    install_metrics(monkeypatch, seen)

    pulse.build_business_pulse(fake_client, company="acme")

    lookups = [
        call for call in fake_client.calls
        if call["method"] == "search_read" and call["model"] == "res.company"
    ]
    assert len(lookups) == 1
    assert len(seen) == 5
    assert all(context.company_id == 5 for _, context, _ in seen)


def test_sales_snapshot_uses_confirmed_sales_for_both_periods(
    fake_client, monkeypatch
):
    monkeypatch.setattr(
        report_context, "today_in_tz", lambda offset: dt.date(2026, 6, 30)
    )
    responses = [
        {"orders": 2, "revenue": 100.0, "currency": "USD"},
        {"orders": 1, "revenue": 50.0, "currency": "USD"},
    ]
    calls = []

    def confirmed_spy(context, **kwargs):
        calls.append(kwargs)
        return responses[len(calls) - 1]

    monkeypatch.setattr(snapshot, "confirmed_sales", confirmed_spy)
    fake_client.aggregate_responses_seq["sale.order"] = [[{
        "partner_id": [7, "Customer"],
        "amount_total:sum": 100.0,
        "__count": 2,
    }]]
    fake_client.aggregate_responses_seq["sale.order.line"] = [[]]
    fake_client.search_count_responses["sale.order"] = 0

    result = snapshot.build_sales_snapshot(fake_client, trend_weeks=0)

    assert [call["group_limit"] for call in calls] == [200, 200]
    assert result["summary"]["orders"] == 2
    assert result["summary"]["revenue"] == 100.0
    assert result["summary"]["prev_orders"] == 1
    assert result["summary"]["prev_revenue"] == 50.0

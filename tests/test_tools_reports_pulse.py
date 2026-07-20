# tests/test_tools_reports_pulse.py
import datetime as dt
import json

import pytest

from odoo_pulse import tools_reports_pulse

# today fixed at 2026-06-30 -> "yesterday" is 2026-06-29.
SALE_AGG = [
    {"currency_id": [1, "USD"], "amount_total:sum": 1500.0, "__count": 2}
]
INVOICE_AGG = [
    {"currency_id": [1, "USD"], "amount_residual:sum": 700.0, "__count": 1}
]


def _fix_today(monkeypatch):
    monkeypatch.setattr(tools_reports_pulse, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


def _setup(fake_client):
    fake_client.aggregate_responses_seq["sale.order"] = [list(SALE_AGG)]
    fake_client.aggregate_responses_seq["account.move"] = [list(INVOICE_AGG)]
    fake_client.search_count_responses["crm.lead"] = 4
    fake_client.search_count_responses["project.task"] = 2
    fake_client.search_responses["hr.leave"] = [{"employee_id": [10, "Alice"]}]
    fake_client.search_count_responses["res.company"] = 1
    fake_client.fields_responses["project.task"] = {
        "date_deadline": {"type": "datetime"}}


def test_business_pulse_sections_and_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_reports_pulse.business_pulse())
    sections = out["breakdown"]["sections"]
    assert sections["sales"] == {"available": True, "orders": 2, "revenue": 1500.0,
                                 "currency": "USD"}
    assert sections["crm"] == {"available": True, "new_leads": 4}
    assert sections["receivables"] == {"available": True,
                                       "overdue_invoices": 1,
                                       "overdue_amount": 700.0,
                                       "currency": "USD"}
    assert sections["projects"] == {"available": True, "overdue_tasks": 2}
    assert sections["hr"] == {"available": True, "off_today": 1}
    assert out["summary"]["verdict"] == "attention"   # overdue invoices + tasks
    codes = {r["code"] for r in out["risks"]}
    assert codes == {"overdue_invoices", "overdue_tasks"}


def test_business_pulse_domains_use_yesterday(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    tools_reports_pulse.business_pulse(timezone_offset=7)
    sales = next(c for c in fake_client.calls
                 if c["method"] == "aggregate_records" and c["model"] == "sale.order")
    assert ("date_order", ">=", "2026-06-28 17:00:00") in sales["domain"]
    assert ("date_order", "<", "2026-06-29 17:00:00") in sales["domain"]
    leads = next(c for c in fake_client.calls
                 if c["method"] == "search_count" and c["model"] == "crm.lead")
    assert ("create_date", ">=", "2026-06-28 17:00:00") in leads["domain"]


def test_business_pulse_all_clear(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    fake_client.aggregate_responses_seq["account.move"] = [[]]
    fake_client.search_count_responses["project.task"] = 0
    out = json.loads(tools_reports_pulse.business_pulse())
    assert out["summary"]["verdict"] == "all_clear"
    assert out["risks"] == []


def test_business_pulse_survives_missing_apps(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    fake_client.error_models = {"sale.order", "crm.lead"}
    out = json.loads(tools_reports_pulse.business_pulse())
    sections = out["breakdown"]["sections"]
    assert sections["sales"]["available"] is False
    assert sections["crm"]["available"] is False
    assert sections["hr"]["available"] is True
    assert out["summary"]["sections_unavailable"] == ["sales", "crm"]
    assert out["summary"]["verdict"] == "attention"  # receivables still overdue
    unavailable_risks = [r for r in out["risks"] if r["code"] == "section_unavailable"]
    assert len(unavailable_risks) == 2


def test_business_pulse_company_filter(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.fields_responses["project.task"] = {
        "date_deadline": {"type": "datetime"}}
    fake_client.search_responses["res.company"] = [{"id": 5, "name": "Acme VN"}]
    fake_client.search_count_responses["res.company"] = 2
    tools_reports_pulse.business_pulse(company="acme")
    for model in ("sale.order", "account.move"):
        call = next(c for c in fake_client.calls
                    if c["method"] == "aggregate_records" and c["model"] == model)
        assert ("company_id", "=", 5) in call["domain"], model
    for model in ("crm.lead", "project.task"):
        call = next(c for c in fake_client.calls
                    if c["method"] == "search_count" and c["model"] == model)
        assert ("company_id", "=", 5) in call["domain"], model
    leave_call = next(c for c in fake_client.calls
                       if c["method"] == "search_read" and c["model"] == "hr.leave")
    assert ("company_id", "=", 5) in leave_call["domain"], "hr.leave"


def test_business_pulse_multi_company_caveat(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.fields_responses["project.task"] = {
        "date_deadline": {"type": "datetime"}}
    fake_client.search_count_responses["res.company"] = 3
    out = json.loads(tools_reports_pulse.business_pulse())
    risk = next(r for r in out["risks"] if r["code"] == "multi_company_totals")
    assert risk["count"] == 3


def test_business_pulse_single_company_no_caveat(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.fields_responses["project.task"] = {
        "date_deadline": {"type": "datetime"}}
    fake_client.search_count_responses["res.company"] = 1
    out = json.loads(tools_reports_pulse.business_pulse())
    assert "multi_company_totals" not in [r["code"] for r in out["risks"]]


def test_business_pulse_day_windows_are_utc_shifted(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_reports_pulse.business_pulse(timezone_offset=7))
    assert out["tool"] == "business_pulse"

    sale_call = next(c for c in fake_client.calls
                     if c["method"] == "aggregate_records"
                     and c["model"] == "sale.order")
    domain = sale_call["domain"]
    lo = next(t for t in domain if t[0] == "date_order" and t[1] == ">=")
    hi = next(t for t in domain if t[0] == "date_order" and t[1] == "<")
    # local midnight at +7 == 17:00 UTC the previous day
    assert lo[2].endswith("17:00:00")
    assert hi[2].endswith("17:00:00")

    leave_call = next(c for c in fake_client.calls
                      if c["method"] == "search_read"
                      and c["model"] == "hr.leave")
    lv = leave_call["domain"]
    assert any(t[0] == "date_from" and t[1] == "<" and t[2].endswith("17:00:00")
               for t in lv)
    assert any(t[0] == "date_to" and t[1] == ">=" and t[2].endswith("17:00:00")
               for t in lv)


def test_business_pulse_runs_sections_concurrently(fake_client, monkeypatch):
    import threading

    _fix_today(monkeypatch)
    _setup(fake_client)
    # The first two counting sections (each its own thunk) must be in flight
    # AT THE SAME TIME; sequential execution would break the barrier, error
    # the report and fail the verdict assertion. Thread-ident spying would
    # be flaky: the pool reuses one worker when a thunk finishes before the
    # next submit. Only the first two waiters block -- the third counting
    # section and the later res.company count must pass through, or the
    # (cyclic) barrier would trap them.
    barrier = threading.Barrier(2, timeout=2)
    seen = {"n": 0}
    orig = fake_client.search_count

    def spying_count(model, domain=None):
        seen["n"] += 1
        if seen["n"] <= 2:
            barrier.wait()
        return orig(model, domain)

    monkeypatch.setattr(fake_client, "search_count", spying_count)
    out = json.loads(tools_reports_pulse.business_pulse())
    assert out["summary"]["verdict"] == "attention"


def test_business_pulse_mixed_currencies_are_split(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    fake_client.aggregate_responses_seq["sale.order"] = [[
        {"currency_id": [1, "USD"], "amount_total:sum": 100.0, "__count": 1},
        {"currency_id": [2, "VND"], "amount_total:sum": 2500000.0, "__count": 250},
    ]]
    out = json.loads(tools_reports_pulse.business_pulse())
    sales = out["breakdown"]["sections"]["sales"]
    assert sales["orders"] == 251
    assert sales["revenue"] == 2500100.0
    assert sales["by_currency"] == {"USD": 100.0, "VND": 2500000.0}
    assert sales["mixed_currencies"] is True
    assert sales["totals_comparable"] is False
    assert any(r["code"] == "mixed_currencies" for r in out["risks"])


def test_business_pulse_invoice_aggregate_exceeds_row_cap(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    fake_client.aggregate_responses_seq["account.move"] = [[
        {"currency_id": [1, "USD"],
         "amount_residual:sum": 99000.0, "__count": 305},
    ]]
    out = json.loads(tools_reports_pulse.business_pulse())
    receivables = out["breakdown"]["sections"]["receivables"]
    assert receivables["overdue_invoices"] == 305
    assert receivables["overdue_amount"] == 99000.0


def test_business_pulse_currency_aggregates_are_not_group_capped(
    fake_client, monkeypatch
):
    _fix_today(monkeypatch)
    _setup(fake_client)
    tools_reports_pulse.business_pulse()
    calls = [
        call for call in fake_client.calls
        if call["method"] == "aggregate_records"
        and call["model"] in {"sale.order", "account.move"}
    ]
    assert len(calls) == 2
    assert all(call["limit"] is None for call in calls)


def test_business_pulse_off_today_counts_unique_employees(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    fake_client.search_responses["hr.leave"] = [
        {"employee_id": [10, "Alice"]},
        {"employee_id": [10, "Alice"]},
        {"employee_id": [11, "Bob"]},
    ]
    out = json.loads(tools_reports_pulse.business_pulse())
    assert out["breakdown"]["sections"]["hr"]["off_today"] == 2


@pytest.mark.parametrize(
    "field_type,expected",
    [
        ("datetime", ("date_deadline", "<", "2026-06-29 17:00:00")),
        ("date", ("date_deadline", "<", "2026-06-30")),
    ],
)
def test_business_pulse_deadline_bound_follows_schema(
    fake_client, monkeypatch, field_type, expected
):
    _fix_today(monkeypatch)
    _setup(fake_client)
    fake_client.fields_responses["project.task"] = {
        "date_deadline": {"type": field_type}}
    tools_reports_pulse.business_pulse(timezone_offset=7)
    call = next(c for c in fake_client.calls
                if c["method"] == "search_count"
                and c["model"] == "project.task")
    assert expected in call["domain"]

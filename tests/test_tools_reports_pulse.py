# tests/test_tools_reports_pulse.py
import datetime as dt
import json

from odoo_pulse import tools_reports_pulse

# today fixed at 2026-06-30 -> "yesterday" is 2026-06-29.
YESTERDAY_ORDERS = [
    {"id": 1, "amount_total": 1000.0},
    {"id": 2, "amount_total": 500.0},
]
OVERDUE_INVOICES = [{"id": 9, "amount_residual": 700.0}]


def _fix_today(monkeypatch):
    monkeypatch.setattr(tools_reports_pulse, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


def _setup(fake_client):
    fake_client.search_responses["sale.order"] = YESTERDAY_ORDERS
    fake_client.search_responses["account.move"] = OVERDUE_INVOICES
    fake_client.search_count_responses["crm.lead"] = 4
    fake_client.search_count_responses["project.task"] = 2
    fake_client.search_count_responses["hr.leave"] = 1
    fake_client.search_count_responses["res.company"] = 1


def test_business_pulse_sections_and_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_reports_pulse.business_pulse())
    sections = out["breakdown"]["sections"]
    assert sections["sales"] == {"available": True, "orders": 2, "revenue": 1500.0}
    assert sections["crm"] == {"available": True, "new_leads": 4}
    assert sections["receivables"] == {"available": True,
                                       "overdue_invoices": 1,
                                       "overdue_amount": 700.0}
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
                 if c["method"] == "search_read" and c["model"] == "sale.order")
    assert ("date_order", ">=", "2026-06-28 17:00:00") in sales["domain"]
    assert ("date_order", "<", "2026-06-29 17:00:00") in sales["domain"]
    leads = next(c for c in fake_client.calls
                 if c["method"] == "search_count" and c["model"] == "crm.lead")
    assert ("create_date", ">=", "2026-06-28 17:00:00") in leads["domain"]


def test_business_pulse_all_clear(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    fake_client.search_responses["account.move"] = []
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
    fake_client.search_responses["res.company"] = [{"id": 5, "name": "Acme VN"}]
    fake_client.search_count_responses["res.company"] = 2
    tools_reports_pulse.business_pulse(company="acme")
    for model in ("sale.order", "account.move"):
        call = next(c for c in fake_client.calls
                    if c["method"] == "search_read" and c["model"] == model)
        assert ("company_id", "=", 5) in call["domain"], model
    for model in ("crm.lead", "project.task", "hr.leave"):
        call = next(c for c in fake_client.calls
                    if c["method"] == "search_count" and c["model"] == model)
        assert ("company_id", "=", 5) in call["domain"], model


def test_business_pulse_multi_company_caveat(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_count_responses["res.company"] = 3
    out = json.loads(tools_reports_pulse.business_pulse())
    risk = next(r for r in out["risks"] if r["code"] == "multi_company_totals")
    assert risk["count"] == 3


def test_business_pulse_single_company_no_caveat(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_count_responses["res.company"] = 1
    out = json.loads(tools_reports_pulse.business_pulse())
    assert "multi_company_totals" not in [r["code"] for r in out["risks"]]


def test_business_pulse_day_windows_are_utc_shifted(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_reports_pulse.business_pulse(timezone_offset=7))
    assert out["tool"] == "business_pulse"

    sale_call = next(c for c in fake_client.calls
                     if c["method"] == "search_read"
                     and c["model"] == "sale.order")
    domain = sale_call["domain"]
    lo = next(t for t in domain if t[0] == "date_order" and t[1] == ">=")
    hi = next(t for t in domain if t[0] == "date_order" and t[1] == "<")
    # local midnight at +7 == 17:00 UTC the previous day
    assert lo[2].endswith("17:00:00")
    assert hi[2].endswith("17:00:00")

    leave_call = next(c for c in fake_client.calls
                      if c["method"] == "search_count"
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

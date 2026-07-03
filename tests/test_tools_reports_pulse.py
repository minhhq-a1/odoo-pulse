# tests/test_tools_reports_pulse.py
import datetime as dt
import json

from odoo_pulse import tools_reports

# today fixed at 2026-06-30 -> "yesterday" is 2026-06-29.
YESTERDAY_ORDERS = [
    {"id": 1, "amount_total": 1000.0},
    {"id": 2, "amount_total": 500.0},
]
OVERDUE_INVOICES = [{"id": 9, "amount_residual": 700.0}]


def _fix_today(monkeypatch):
    monkeypatch.setattr(tools_reports, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


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
    out = json.loads(tools_reports.business_pulse())
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
    tools_reports.business_pulse()
    sales = next(c for c in fake_client.calls
                 if c["method"] == "search_read" and c["model"] == "sale.order")
    assert ("date_order", ">=", "2026-06-29") in sales["domain"]
    assert ("date_order", "<", "2026-06-30") in sales["domain"]
    leads = next(c for c in fake_client.calls
                 if c["method"] == "search_count" and c["model"] == "crm.lead")
    assert ("create_date", ">=", "2026-06-29") in leads["domain"]


def test_business_pulse_all_clear(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    fake_client.search_responses["account.move"] = []
    fake_client.search_count_responses["project.task"] = 0
    out = json.loads(tools_reports.business_pulse())
    assert out["summary"]["verdict"] == "all_clear"
    assert out["risks"] == []


def test_business_pulse_survives_missing_apps(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    fake_client.error_models = {"sale.order", "crm.lead"}
    out = json.loads(tools_reports.business_pulse())
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
    tools_reports.business_pulse(company="acme")
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
    out = json.loads(tools_reports.business_pulse())
    risk = next(r for r in out["risks"] if r["code"] == "multi_company_totals")
    assert risk["count"] == 3


def test_business_pulse_single_company_no_caveat(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_count_responses["res.company"] = 1
    out = json.loads(tools_reports.business_pulse())
    assert "multi_company_totals" not in [r["code"] for r in out["risks"]]

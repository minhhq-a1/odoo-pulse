# tests/test_tools_reports_receivables.py
import datetime as dt
import json

from odoo_pulse import tools_reports

# today fixed at 2026-06-30.
INVOICES = [
    {"id": 1, "name": "INV/1", "partner_id": [5, "Acme"], "move_type": "out_invoice",
     "amount_residual": 1000.0, "invoice_date_due": "2026-07-15"},   # not due
    {"id": 2, "name": "INV/2", "partner_id": [5, "Acme"], "move_type": "out_invoice",
     "amount_residual": 2000.0, "invoice_date_due": "2026-06-10"},   # 20d -> 1-30
    {"id": 3, "name": "INV/3", "partner_id": [6, "Beta"], "move_type": "out_invoice",
     "amount_residual": 3000.0, "invoice_date_due": "2026-02-01"},   # 149d -> 90+
    {"id": 4, "name": "BILL/1", "partner_id": [7, "Supplier"], "move_type": "in_invoice",
     "amount_residual": 4000.0, "invoice_date_due": "2026-06-25"},   # 5d -> 1-30 (AP)
]


def _fix_today(monkeypatch):
    monkeypatch.setattr(tools_reports, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


def test_receivables_health_builds_domain(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["account.move"] = INVOICES
    tools_reports.receivables_health()
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == "account.move")
    assert ("move_type", "in", ["out_invoice", "in_invoice"]) in call["domain"]
    assert ("state", "=", "posted") in call["domain"]
    assert ("payment_state", "in", ["not_paid", "partial"]) in call["domain"]


def test_receivables_health_aging_buckets(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["account.move"] = INVOICES
    out = json.loads(tools_reports.receivables_health())
    ar = out["breakdown"]["aging"]["receivable"]
    assert ar["not_due"] == 1000.0
    assert ar["1-30"] == 2000.0
    assert ar["90+"] == 3000.0
    ap = out["breakdown"]["aging"]["payable"]
    assert ap["1-30"] == 4000.0


def test_receivables_health_summary_and_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["account.move"] = INVOICES
    out = json.loads(tools_reports.receivables_health())
    s = out["summary"]
    assert s["receivable_open"] == 3
    assert s["receivable_total"] == 6000.0
    assert s["receivable_overdue"] == 5000.0
    assert s["pct_overdue"] == 83.3
    assert s["payable_open"] == 1
    assert s["payable_total"] == 4000.0
    assert s["verdict"] == "off_track"       # 83.3% >= 50
    codes = {r["code"] for r in out["risks"]}
    assert "overdue_receivables" in codes
    assert "aged_over_90" in codes


def test_receivables_health_top_debtors(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["account.move"] = INVOICES
    out = json.loads(tools_reports.receivables_health())
    top = out["breakdown"]["top_overdue_customers"]
    assert top[0] == {"customer": "Beta", "overdue_amount": 3000.0}
    assert top[1] == {"customer": "Acme", "overdue_amount": 2000.0}


def test_receivables_health_on_track_when_nothing_overdue(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["account.move"] = [INVOICES[0]]
    out = json.loads(tools_reports.receivables_health())
    assert out["summary"]["verdict"] == "on_track"
    assert out["risks"] == []


def test_receivables_custom_thresholds(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["account.move"] = INVOICES
    out_default = json.loads(tools_reports.receivables_health())
    # loosen both cut-offs so the same data reads on_track... except 90+
    out_loose = json.loads(tools_reports.receivables_health(
        overdue_pct_at_risk=99.0, overdue_pct_off_track=100.0))
    assert out_loose["thresholds"] == {
        "overdue_pct_at_risk": 99.0, "overdue_pct_off_track": 100.0}
    # 83.3% < 99 so pct no longer trips off_track, but the 90+ invoice
    # still forces at_risk; defaults read the same data as off_track.
    assert out_loose["summary"]["verdict"] == "at_risk"
    assert out_default["summary"]["verdict"] == "off_track"


def test_receivables_company_filter(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["res.company"] = [{"id": 5, "name": "Acme VN"}]
    fake_client.search_responses["account.move"] = []
    tools_reports.receivables_health(company="acme")
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == "account.move")
    assert ("company_id", "=", 5) in call["domain"]


def test_receivables_mixed_currencies_flagged(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["account.move"] = [
        {"id": 1, "name": "INV/1", "partner_id": [1, "Acme"],
         "amount_residual": 100.0, "invoice_date_due": "2026-06-01",
         "move_type": "out_invoice", "currency_id": [1, "USD"]},
        {"id": 2, "name": "INV/2", "partner_id": [2, "Beta"],
         "amount_residual": 5000.0, "invoice_date_due": "2026-06-01",
         "move_type": "out_invoice", "currency_id": [2, "VND"]},
    ]
    out = json.loads(tools_reports.receivables_health())
    assert out["summary"]["by_currency"] == {"USD": 100.0, "VND": 5000.0}
    assert "mixed_currencies" in [r["code"] for r in out["risks"]]

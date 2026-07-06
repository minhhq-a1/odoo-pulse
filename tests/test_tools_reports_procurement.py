# tests/test_tools_reports_procurement.py
import datetime as dt
import json

from odoo_pulse import tools_reports_ops

# today fixed at 2026-06-30
POS = [
    {"id": 1, "name": "PO1", "partner_id": [7, "VendorA"],
     "date_planned": "2026-06-20 00:00:00", "amount_total": 500.0,
     "state": "purchase", "currency_id": [1, "USD"]},   # 10 days late
    {"id": 2, "name": "PO2", "partner_id": [8, "VendorB"],
     "date_planned": "2026-07-15 00:00:00", "amount_total": 900.0,
     "state": "purchase", "currency_id": [1, "USD"]},   # on time
]


def _fix_today(monkeypatch):
    monkeypatch.setattr(
        tools_reports_ops, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


def test_procurement_watch_domain(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["purchase.order"] = POS
    tools_reports_ops.procurement_watch()
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == "purchase.order")
    assert ("state", "=", "purchase") in call["domain"]
    rfq_call = next(c for c in fake_client.calls
                    if c["method"] == "search_count" and c["model"] == "purchase.order")
    assert ("state", "in", ["draft", "sent"]) in rfq_call["domain"]
    # 2026-06-23 local midnight at +7 (default offset), expressed in UTC
    assert ("create_date", "<", "2026-06-22 17:00:00") in rfq_call["domain"]


def test_procurement_watch_late_and_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["purchase.order"] = POS
    fake_client.search_count_responses["purchase.order"] = 0
    out = json.loads(tools_reports_ops.procurement_watch())
    s = out["summary"]
    assert s["open_pos"] == 2
    assert s["late_receipts"] == 1
    assert s["open_value"] == 1400.0
    assert s["currency"] == "USD"
    assert s["verdict"] == "action_needed"
    late = out["breakdown"]["late_receipts"]
    assert late[0] == {"po": "PO1", "vendor": "VendorA",
                       "expected": "2026-06-20 00:00:00",
                       "days_late": 10, "amount": 500.0}
    assert "late_receipts" in [r["code"] for r in out["risks"]]


def test_procurement_watch_stale_rfqs_watch_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["purchase.order"] = [POS[1]]  # nothing late
    fake_client.search_count_responses["purchase.order"] = 4   # stale RFQs
    out = json.loads(tools_reports_ops.procurement_watch())
    assert out["summary"]["stale_rfqs"] == 4
    assert out["summary"]["verdict"] == "watch"


def test_procurement_watch_healthy(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["purchase.order"] = [POS[1]]
    fake_client.search_count_responses["purchase.order"] = 0
    out = json.loads(tools_reports_ops.procurement_watch())
    assert out["summary"]["verdict"] == "healthy"


def test_procurement_watch_top_vendors(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["purchase.order"] = POS
    fake_client.search_count_responses["purchase.order"] = 0
    out = json.loads(tools_reports_ops.procurement_watch())
    vendors = out["breakdown"]["top_vendors"]
    assert vendors[0] == {"vendor": "VendorB", "orders": 1, "open_value": 900.0}


def test_procurement_watch_mixed_currencies(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    pos = [dict(POS[0], currency_id=[1, "USD"]), dict(POS[1], currency_id=[2, "VND"])]
    fake_client.search_responses["purchase.order"] = pos
    fake_client.search_count_responses["purchase.order"] = 0
    out = json.loads(tools_reports_ops.procurement_watch())
    assert out["summary"]["by_currency"] == {"USD": 500.0, "VND": 900.0}
    assert "currency" not in out["summary"]
    assert "mixed_currencies" in [r["code"] for r in out["risks"]]


def test_procurement_watch_company_filter(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["res.company"] = [{"id": 5, "name": "Acme VN"}]
    fake_client.search_responses["purchase.order"] = []
    fake_client.search_count_responses["purchase.order"] = 0
    tools_reports_ops.procurement_watch(company="acme")
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == "purchase.order")
    assert ("company_id", "=", 5) in call["domain"]


def test_late_receipt_uses_local_date_of_date_planned(fake_client):
    import json
    from datetime import timedelta
    from odoo_pulse import tools_reports_ops
    from odoo_pulse.workflow_helpers import today_in_tz

    today = today_in_tz(7)
    # 20:00 UTC "yesterday by UTC date" is already today at +7 -> not late
    planned = (today - timedelta(days=1)).strftime("%Y-%m-%d") + " 20:00:00"
    fake_client.search_responses["purchase.order"] = [{
        "id": 1, "name": "PO1", "partner_id": [1, "Vendor"],
        "date_planned": planned, "amount_total": 100.0,
        "state": "purchase", "currency_id": [1, "USD"],
    }]
    fake_client.search_count_responses["purchase.order"] = 0
    out = json.loads(tools_reports_ops.procurement_watch(timezone_offset=7))
    assert out["summary"]["late_receipts"] == 0

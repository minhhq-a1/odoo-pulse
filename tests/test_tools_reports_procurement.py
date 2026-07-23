# tests/test_tools_reports_procurement.py
import datetime as dt
import json

from odoo_pulse import tools_reports_ops
from odoo_pulse.services import report_context

# today fixed at 2026-06-30
POS = [
    {"id": 1, "name": "PO1", "partner_id": [7, "VendorA"],
     "date_planned": "2026-06-20 00:00:00", "amount_total": 500.0,
     "state": "purchase", "currency_id": [1, "USD"]},   # 10 days late
    {"id": 2, "name": "PO2", "partner_id": [8, "VendorB"],
     "date_planned": "2026-07-15 00:00:00", "amount_total": 900.0,
     "state": "purchase", "currency_id": [1, "USD"]},   # on time
]

LINE_SCHEMA = {
    "order_id": {"type": "many2one"},
    "product_qty": {"type": "float"},
    "qty_received": {"type": "float"},
    "price_total": {"type": "monetary"},
}


def _fix_today(monkeypatch):
    monkeypatch.setattr(
        report_context, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


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
    from odoo_pulse.common.dates import today_in_tz

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


def test_procurement_watch_fetches_concurrently(fake_client, monkeypatch):
    import threading

    _fix_today(monkeypatch)
    fake_client.search_responses["purchase.order"] = POS
    fake_client.search_count_responses["purchase.order"] = 3
    # The PO fetch (orders thunk) and the stale-RFQ count (rfqs thunk) must
    # be in flight AT THE SAME TIME; sequential execution would break the
    # barrier, error the report and fail the summary assertion.
    barrier = threading.Barrier(2, timeout=2)
    orig_read = fake_client.search_read
    orig_count = fake_client.search_count

    def spying_read(*args, **kwargs):
        barrier.wait()
        return orig_read(*args, **kwargs)

    def spying_count(*args, **kwargs):
        barrier.wait()
        return orig_count(*args, **kwargs)

    monkeypatch.setattr(fake_client, "search_read", spying_read)
    monkeypatch.setattr(fake_client, "search_count", spying_count)
    out = json.loads(tools_reports_ops.procurement_watch())
    assert out["summary"]["open_pos"] == 2
    assert out["summary"]["stale_rfqs"] == 3


def test_procurement_watch_uses_paginated_remaining_line_value(
    fake_client, monkeypatch
):
    _fix_today(monkeypatch)
    fake_client.fields_responses["purchase.order"] = {
        "receipt_status": {"type": "selection"}}
    fake_client.fields_responses["purchase.order.line"] = dict(LINE_SCHEMA)
    fake_client.search_responses["purchase.order"] = [
        dict(POS[0], receipt_status="partial"),
        dict(POS[1], receipt_status="full"),
    ]
    fake_client.search_responses["purchase.order.line"] = [
        {"order_id": [1, "PO1"], "product_qty": 10.0,
         "qty_received": 6.0, "price_total": 500.0},
        {"order_id": [2, "PO2"], "product_qty": 5.0,
         "qty_received": 5.0, "price_total": 900.0},
    ]
    fake_client.search_count_responses["purchase.order"] = 0
    out = json.loads(tools_reports_ops.procurement_watch())
    assert out["summary"]["open_pos"] == 1
    assert out["summary"]["open_value"] == 200.0
    assert out["summary"]["receipt_tracking_available"] is True
    assert out["summary"]["remaining_value_available"] is True
    line_call = next(c for c in fake_client.calls
                     if c["method"] == "search_read"
                     and c["model"] == "purchase.order.line")
    assert ("order_id", "in", [1, 2]) in line_call["domain"]
    assert line_call["order"] == "id"


def test_procurement_watch_receipt_status_only_marks_value_estimated(
    fake_client, monkeypatch
):
    _fix_today(monkeypatch)
    fake_client.fields_responses["purchase.order"] = {
        "receipt_status": {"type": "selection"}}
    fake_client.fields_responses["purchase.order.line"] = {"name": {"type": "char"}}
    fake_client.search_responses["purchase.order"] = [
        dict(POS[0], receipt_status="partial")]
    fake_client.search_count_responses["purchase.order"] = 0
    out = json.loads(tools_reports_ops.procurement_watch())
    assert out["summary"]["open_value"] == 500.0
    assert out["summary"]["remaining_value_available"] is False
    assert any(r["code"] == "partial_receipt_value_estimated"
               for r in out["risks"])


def test_procurement_watch_without_receipt_schema_keeps_late_fallback(
    fake_client, monkeypatch
):
    _fix_today(monkeypatch)
    fake_client.fields_responses["purchase.order"] = {"name": {"type": "char"}}
    fake_client.fields_responses["purchase.order.line"] = {"name": {"type": "char"}}
    fake_client.search_responses["purchase.order"] = [POS[0]]
    fake_client.search_count_responses["purchase.order"] = 0
    out = json.loads(tools_reports_ops.procurement_watch())
    assert out["summary"]["late_receipts"] == 1
    assert out["summary"]["receipt_tracking_available"] is False
    assert any(r["code"] == "receipt_tracking_unavailable" for r in out["risks"])

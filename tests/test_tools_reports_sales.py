# tests/test_tools_reports_sales.py
import datetime as dt
import json

from odoo_pulse import tools_reports

# today fixed at 2026-06-30; period_days=7 -> current period starts
# 2026-06-23, previous period starts 2026-06-16.
ORDERS = [
    {"id": 1, "name": "S1", "amount_total": 1000.0,
     "partner_id": [5, "Acme"], "date_order": "2026-06-28 10:00:00"},
    {"id": 2, "name": "S2", "amount_total": 500.0,
     "partner_id": [6, "Beta"], "date_order": "2026-06-24 10:00:00"},
    {"id": 3, "name": "S3", "amount_total": 2000.0,
     "partner_id": [5, "Acme"], "date_order": "2026-06-20 10:00:00"},
]

LINES_AGG = [
    {"product_id": [1, "Widget"], "price_subtotal:sum": 800.0},
    {"product_id": [2, "Gadget"], "price_subtotal:sum": 700.0},
]


def _fix_today(monkeypatch):
    monkeypatch.setattr(tools_reports, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


def _setup(fake_client):
    fake_client.search_responses["sale.order"] = ORDERS
    fake_client.search_responses["sale.order.line"] = LINES_AGG


def test_sales_snapshot_builds_domain(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    tools_reports.sales_snapshot()
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == "sale.order")
    assert ("state", "in", ["sale", "done"]) in call["domain"]
    assert ("date_order", ">=", "2026-06-16") in call["domain"]


def test_sales_snapshot_summary_and_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    fake_client.search_count_responses["sale.order"] = 3
    out = json.loads(tools_reports.sales_snapshot())
    s = out["summary"]
    assert s["orders"] == 2                # S1, S2 in current period
    assert s["revenue"] == 1500.0
    assert s["prev_orders"] == 1           # S3
    assert s["prev_revenue"] == 2000.0
    assert s["delta_pct"] == -25.0
    assert s["stale_quotations"] == 3
    assert s["verdict"] == "declining"     # delta <= -10
    assert out["tool"] == "sales_snapshot"


def test_sales_snapshot_top_products_via_aggregate(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_reports.sales_snapshot())
    agg_call = next(c for c in fake_client.calls
                    if c["method"] == "aggregate_records")
    assert agg_call["model"] == "sale.order.line"
    assert agg_call["group_by"] == ["product_id"]
    assert agg_call["measures"] == [("price_subtotal", "sum")]
    assert agg_call["order"] == "price_subtotal:sum desc"
    assert ("order_id.date_order", ">=", "2026-06-23") in agg_call["domain"]
    top = out["breakdown"]["top_products"]
    assert top[0] == {"product": "Widget", "revenue": 800.0}


def test_sales_snapshot_top_customers(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_reports.sales_snapshot())
    top = out["breakdown"]["top_customers"]
    assert top[0] == {"customer": "Acme", "orders": 1, "revenue": 1000.0}


def test_sales_snapshot_growing_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    grow = [dict(ORDERS[0]), dict(ORDERS[2])]
    grow[1]["amount_total"] = 100.0  # prev period much smaller
    fake_client.search_responses["sale.order"] = grow
    fake_client.search_responses["sale.order.line"] = []
    out = json.loads(tools_reports.sales_snapshot())
    assert out["summary"]["verdict"] == "growing"


def test_sales_snapshot_steady_when_no_previous(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["sale.order"] = [ORDERS[0]]
    fake_client.search_responses["sale.order.line"] = []
    out = json.loads(tools_reports.sales_snapshot())
    assert out["summary"]["delta_pct"] is None
    assert out["summary"]["verdict"] == "steady"

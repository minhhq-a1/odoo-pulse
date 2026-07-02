# tests/test_tools_reports_inventory.py
import datetime as dt
import json

from odoo_pulse import tools_reports

# today fixed at 2026-06-30; dead_stock_days=90 -> moves since 2026-04-01.
SHORTAGE_ROWS = [
    {"id": 1, "name": "Bolt M8", "default_code": "B8",
     "qty_available": 2.0, "virtual_available": -30.0},
]
STOCKED_ROWS = [
    {"id": 7, "name": "Widget", "default_code": "W1",
     "qty_available": 50.0, "standard_price": 4.0},    # moved recently
    {"id": 8, "name": "Old Gadget", "default_code": "OG",
     "qty_available": 10.0, "standard_price": 25.0},   # dead
]
MOVED_AGG = [{"product_id": [7, "Widget"], "__count": 3}]


def _fix_today(monkeypatch):
    monkeypatch.setattr(tools_reports, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


def _setup(fake_client):
    fake_client.search_responses_seq["product.product"] = [
        list(SHORTAGE_ROWS), list(STOCKED_ROWS),
    ]
    fake_client.search_responses["stock.move"] = MOVED_AGG


def test_inventory_risk_builds_domains(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    tools_reports.inventory_risk()
    product_calls = [c for c in fake_client.calls
                     if c["method"] == "search_read" and c["model"] == "product.product"]
    assert ("virtual_available", "<", 0) in product_calls[0]["domain"]
    assert ("qty_available", ">", 0) in product_calls[1]["domain"]
    agg = next(c for c in fake_client.calls if c["method"] == "aggregate_records")
    assert agg["model"] == "stock.move"
    assert ("date", ">=", "2026-04-01") in agg["domain"]
    assert ("state", "=", "done") in agg["domain"]


def test_inventory_risk_summary_and_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_reports.inventory_risk())
    s = out["summary"]
    assert s["shortages"] == 1
    assert s["dead_stock_items"] == 1          # Old Gadget (id 8, not moved)
    assert s["dead_stock_value"] == 250.0      # 10 * 25.0
    assert s["verdict"] == "action_needed"     # shortage present
    codes = {r["code"] for r in out["risks"]}
    assert "negative_forecast" in codes
    assert "dead_stock" in codes


def test_inventory_risk_breakdown(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_reports.inventory_risk())
    assert out["breakdown"]["shortages"][0]["product"] == "Bolt M8"
    assert out["breakdown"]["shortages"][0]["forecasted"] == -30.0
    dead = out["breakdown"]["dead_stock"]
    assert dead == [{"product": "Old Gadget", "code": "OG",
                     "on_hand": 10.0, "value": 250.0}]


def test_inventory_risk_watch_when_only_dead_stock(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses_seq["product.product"] = [[], list(STOCKED_ROWS)]
    fake_client.search_responses["stock.move"] = MOVED_AGG
    out = json.loads(tools_reports.inventory_risk())
    assert out["summary"]["verdict"] == "watch"


def test_inventory_risk_healthy_when_clean(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses_seq["product.product"] = [[], [STOCKED_ROWS[0]]]
    fake_client.search_responses["stock.move"] = MOVED_AGG
    out = json.loads(tools_reports.inventory_risk())
    assert out["summary"]["verdict"] == "healthy"
    assert out["risks"] == []

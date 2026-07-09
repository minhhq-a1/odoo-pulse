# tests/test_tools_reports_sales.py
import datetime as dt
import json

from odoo_pulse import tools_reports

# today fixed at 2026-06-30; period_days=7 -> current period starts
# 2026-06-23, previous period starts 2026-06-16.
CUR_AGG = [{"currency_id": [1, "USD"], "amount_total:sum": 3000.0, "__count": 2}]
PREV_AGG = [{"currency_id": [1, "USD"], "amount_total:sum": 500.0, "__count": 1}]
CUST_AGG = [
    {"partner_id": [7, "Acme"], "amount_total:sum": 2500.0, "__count": 1},
    {"partner_id": [8, "Globex"], "amount_total:sum": 500.0, "__count": 1},
]
LINE_AGG = [
    {"product_id": [1, "Widget"], "price_subtotal:sum": 800.0},
    {"product_id": [2, "Gadget"], "price_subtotal:sum": 700.0},
]


def _fix_today(monkeypatch):
    monkeypatch.setattr(tools_reports, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


def _prime(fake_client):
    fake_client.aggregate_responses_seq["sale.order"] = [
        list(CUR_AGG), list(PREV_AGG), list(CUST_AGG)]
    fake_client.search_responses["sale.order.line"] = list(LINE_AGG)
    fake_client.search_responses["sale.order"] = []   # trend rows
    fake_client.search_count_responses["sale.order"] = 0  # stale quotes


def test_sales_snapshot_periods_from_aggregates(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _prime(fake_client)
    out = json.loads(tools_reports.sales_snapshot(period_days=7,
                                                    timezone_offset=7))
    s = out["summary"]
    assert s["orders"] == 2 and s["revenue"] == 3000.0
    assert s["prev_orders"] == 1 and s["prev_revenue"] == 500.0
    assert s["delta_pct"] == 500.0
    assert s["currency"] == "USD"
    assert out["summary"]["verdict"] == "growing"
    assert out["tool"] == "sales_snapshot"
    assert "truncated" not in s
    assert "total_matching" not in s


def test_sales_snapshot_period_domains_are_utc_bounded(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _prime(fake_client)
    json.loads(tools_reports.sales_snapshot(period_days=7, timezone_offset=7))
    aggs = [c for c in fake_client.calls
            if c["method"] == "aggregate_records" and c["model"] == "sale.order"]
    cur_domain = aggs[0]["domain"]
    lo = next(t for t in cur_domain if t[0] == "date_order" and t[1] == ">=")
    assert lo[2].endswith("17:00:00")


def test_sales_snapshot_top_products_via_aggregate(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _prime(fake_client)
    out = json.loads(tools_reports.sales_snapshot(timezone_offset=7))
    agg_call = next(c for c in fake_client.calls
                     if c["method"] == "aggregate_records"
                     and c["model"] == "sale.order.line")
    assert agg_call["group_by"] == ["product_id"]
    assert agg_call["measures"] == [("price_subtotal", "sum")]
    assert agg_call["order"] == "price_subtotal:sum desc"
    assert any(t[0] == "order_id.date_order" and t[1] == ">="
               for t in agg_call["domain"])
    top = out["breakdown"]["top_products"]
    assert top[0] == {"product": "Widget", "revenue": 800.0}


def test_sales_snapshot_top_customers_via_aggregate(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _prime(fake_client)
    out = json.loads(tools_reports.sales_snapshot(timezone_offset=7))
    top = out["breakdown"]["top_customers"]
    assert top[0] == {"customer": "Acme", "orders": 1, "revenue": 2500.0}
    assert top[1] == {"customer": "Globex", "orders": 1, "revenue": 500.0}
    cust_call = next(c for c in fake_client.calls
                      if c["method"] == "aggregate_records"
                      and c["model"] == "sale.order"
                      and c["group_by"] == ["partner_id"])
    assert cust_call["order"] == "amount_total:sum desc"


def test_sales_snapshot_declining_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.aggregate_responses_seq["sale.order"] = [
        [{"currency_id": [1, "USD"], "amount_total:sum": 750.0, "__count": 1}],
        [{"currency_id": [1, "USD"], "amount_total:sum": 2000.0, "__count": 2}],
        [],
    ]
    fake_client.search_responses["sale.order.line"] = []
    fake_client.search_responses["sale.order"] = []
    fake_client.search_count_responses["sale.order"] = 0
    out = json.loads(tools_reports.sales_snapshot(timezone_offset=7))
    s = out["summary"]
    assert s["orders"] == 1 and s["revenue"] == 750.0
    assert s["prev_orders"] == 2 and s["prev_revenue"] == 2000.0
    assert s["delta_pct"] == -62.5
    assert s["verdict"] == "declining"
    codes = [r["code"] for r in out["risks"]]
    assert "revenue_drop" in codes


def test_sales_snapshot_steady_when_no_previous(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.aggregate_responses_seq["sale.order"] = [
        [{"currency_id": [1, "USD"], "amount_total:sum": 1000.0, "__count": 1}],
        [],
        [],
    ]
    fake_client.search_responses["sale.order.line"] = []
    fake_client.search_responses["sale.order"] = []
    fake_client.search_count_responses["sale.order"] = 0
    out = json.loads(tools_reports.sales_snapshot(timezone_offset=7))
    assert out["summary"]["delta_pct"] is None
    assert out["summary"]["verdict"] == "steady"


def test_sales_snapshot_growth_threshold_param(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.aggregate_responses_seq["sale.order"] = [
        [{"currency_id": [1, "USD"], "amount_total:sum": 750.0, "__count": 1}],
        [{"currency_id": [1, "USD"], "amount_total:sum": 1000.0, "__count": 1}],
        [],
    ]
    fake_client.search_responses["sale.order.line"] = []
    fake_client.search_responses["sale.order"] = []
    fake_client.search_count_responses["sale.order"] = 0
    # delta_pct = -25 with this canned data
    out = json.loads(tools_reports.sales_snapshot(growth_threshold_pct=30.0,
                                                    timezone_offset=7))
    assert out["summary"]["verdict"] == "steady"   # -25 within +/-30


def test_sales_snapshot_company_filter(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _prime(fake_client)
    fake_client.search_responses["res.company"] = [{"id": 5, "name": "Acme VN"}]
    tools_reports.sales_snapshot(company="acme", timezone_offset=7)
    order_aggs = [c for c in fake_client.calls
                  if c["method"] == "aggregate_records" and c["model"] == "sale.order"]
    for agg_call in order_aggs:
        assert ("company_id", "=", 5) in agg_call["domain"]
    line_agg = next(c for c in fake_client.calls
                     if c["method"] == "aggregate_records"
                     and c["model"] == "sale.order.line")
    assert ("order_id.company_id", "=", 5) in line_agg["domain"]
    quote_call = next(c for c in fake_client.calls
                       if c["method"] == "search_count" and c["model"] == "sale.order")
    assert ("company_id", "=", 5) in quote_call["domain"]


def test_sales_snapshot_single_currency_labelled(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _prime(fake_client)
    out = json.loads(tools_reports.sales_snapshot(timezone_offset=7))
    assert out["summary"]["currency"] == "USD"
    assert "by_currency" not in out["summary"]


def test_sales_snapshot_mixed_currencies_flagged(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    cur_mixed = [
        {"currency_id": [1, "USD"], "amount_total:sum": 1000.0, "__count": 1},
        {"currency_id": [2, "VND"], "amount_total:sum": 500.0, "__count": 1},
    ]
    fake_client.aggregate_responses_seq["sale.order"] = [
        cur_mixed, list(PREV_AGG), list(CUST_AGG)]
    fake_client.search_responses["sale.order.line"] = []
    fake_client.search_responses["sale.order"] = []
    fake_client.search_count_responses["sale.order"] = 0
    out = json.loads(tools_reports.sales_snapshot(timezone_offset=7))
    assert out["summary"]["by_currency"] == {"USD": 1000.0, "VND": 500.0}
    codes = [r["code"] for r in out["risks"]]
    assert "mixed_currencies" in codes


def test_sales_snapshot_stale_quotations_risk(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _prime(fake_client)
    fake_client.search_count_responses["sale.order"] = 3
    out = json.loads(tools_reports.sales_snapshot(timezone_offset=7))
    assert out["summary"]["stale_quotations"] == 3
    codes = [r["code"] for r in out["risks"]]
    assert "stale_quotations" in codes
    quote_call = next(c for c in fake_client.calls
                       if c["method"] == "search_count" and c["model"] == "sale.order")
    lo = next(t for t in quote_call["domain"]
              if t[0] == "create_date" and t[1] == "<")
    assert lo[2].endswith("17:00:00")


def test_sales_snapshot_weekly_trend(fake_client, monkeypatch):
    _fix_today(monkeypatch)  # today = 2026-06-30
    _prime(fake_client)
    recent = [  # weeks 6-7 of an 8-week window, big revenue
        {"id": 10, "amount_total": 900.0, "date_order": "2026-06-25 09:00:00"},
        {"id": 11, "amount_total": 900.0, "date_order": "2026-06-18 09:00:00"},
    ]
    old = [    # weeks 0-1, small revenue
        {"id": 12, "amount_total": 10.0, "date_order": "2026-05-07 09:00:00"},
    ]
    fake_client.search_responses_seq["sale.order"] = [old + recent]
    out = json.loads(tools_reports.sales_snapshot(timezone_offset=7))
    assert out["summary"]["trend"] == "improving"
    weeks = out["breakdown"]["weekly_revenue"]
    assert len(weeks) == 8
    assert weeks[0]["week_start"] == "2026-05-05"   # today - 8*7 days
    assert sum(w["revenue"] for w in weeks) == 1810.0


def test_sales_snapshot_trend_disabled(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _prime(fake_client)
    out = json.loads(tools_reports.sales_snapshot(trend_weeks=0, timezone_offset=7))
    assert out["summary"]["trend"] is None
    assert out["breakdown"]["weekly_revenue"] == []
    # no trend fetch happened
    reads = [c for c in fake_client.calls
             if c["method"] == "search_read" and c["model"] == "sale.order"]
    assert len(reads) == 0


def test_sales_snapshot_trend_truncated_reports_no_direction(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _prime(fake_client)
    truncated_trend_rows = [
        {"id": 1000 + i, "amount_total": 10.0, "date_order": "2026-06-25 09:00:00"}
        for i in range(200)
    ]
    fake_client.search_responses_seq["sale.order"] = [truncated_trend_rows]
    fake_client.search_count_responses["sale.order"] = 500
    out = json.loads(tools_reports.sales_snapshot(timezone_offset=7))
    assert out["summary"]["trend"] is None
    assert "truncated_trend" in [r["code"] for r in out["risks"]]


def test_sales_snapshot_fetches_concurrently(fake_client, monkeypatch):
    import threading

    _fix_today(monkeypatch)
    _prime(fake_client)
    # The first sale.order aggregate (sales thunk) and the stale-quote count
    # (quotes thunk) must be in flight AT THE SAME TIME; if the report ran
    # sequentially the barrier would time out, error the report and fail the
    # summary assertion. Thread-ident spying would be flaky here: the pool
    # reuses one worker when a thunk finishes before the next submit.
    barrier = threading.Barrier(2, timeout=2)
    agg_seen = {"n": 0}
    orig_agg = fake_client.aggregate_records
    orig_count = fake_client.search_count

    def spying_aggregate(*args, **kwargs):
        agg_seen["n"] += 1
        if agg_seen["n"] == 1:
            barrier.wait()
        return orig_agg(*args, **kwargs)

    def spying_count(*args, **kwargs):
        barrier.wait()
        return orig_count(*args, **kwargs)

    monkeypatch.setattr(fake_client, "aggregate_records", spying_aggregate)
    monkeypatch.setattr(fake_client, "search_count", spying_count)
    out = json.loads(tools_reports.sales_snapshot())
    assert out["summary"]["revenue"] == 3000.0

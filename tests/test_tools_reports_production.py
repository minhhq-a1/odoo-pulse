# tests/test_tools_reports_production.py
import datetime as dt
import json

from odoo_pulse import tools_reports_ops

# today fixed at 2026-06-30
MOS = [
    {"id": 1, "name": "MO1", "product_id": [1, "Widget"], "product_qty": 10.0,
     "state": "confirmed", "date_start": "2026-06-20 08:00:00",
     "date_finished": False},                       # should have started: late
    {"id": 2, "name": "MO2", "product_id": [2, "Gadget"], "product_qty": 5.0,
     "state": "progress", "date_start": "2026-06-01 08:00:00",
     "date_finished": False},                       # running 29 days: stuck
    {"id": 3, "name": "MO3", "product_id": [3, "Sprocket"], "product_qty": 2.0,
     "state": "to_close", "date_start": "2026-06-28 08:00:00",
     "date_finished": False},                       # fine
]


def _fix_today(monkeypatch):
    monkeypatch.setattr(
        tools_reports_ops, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


def test_production_health_domain(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["mrp.production"] = MOS
    tools_reports_ops.production_health()
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == "mrp.production")
    assert ("state", "in", ["confirmed", "progress", "to_close"]) in call["domain"]


def test_production_health_summary_and_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["mrp.production"] = MOS
    out = json.loads(tools_reports_ops.production_health())
    s = out["summary"]
    assert s["open_orders"] == 3
    assert s["behind_start"] == 1
    assert s["stuck_in_progress"] == 1
    assert s["verdict"] == "action_needed"
    assert out["breakdown"]["by_state"] == {
        "confirmed": 1, "progress": 1, "to_close": 1}
    behind = out["breakdown"]["behind_start"]
    assert behind[0]["mo"] == "MO1" and behind[0]["days_behind"] == 10
    stuck = out["breakdown"]["stuck_in_progress"]
    assert stuck[0]["mo"] == "MO2" and stuck[0]["running_days"] == 29
    codes = [r["code"] for r in out["risks"]]
    assert "behind_start" in codes and "stuck_in_progress" in codes


def test_production_health_watch_when_only_stuck(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["mrp.production"] = [MOS[1], MOS[2]]
    out = json.loads(tools_reports_ops.production_health())
    assert out["summary"]["verdict"] == "watch"


def test_production_health_healthy(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["mrp.production"] = [MOS[2]]
    out = json.loads(tools_reports_ops.production_health())
    assert out["summary"]["verdict"] == "healthy"


def test_production_health_stuck_days_param(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["mrp.production"] = [MOS[1], MOS[2]]
    out = json.loads(tools_reports_ops.production_health(stuck_days=60))
    assert out["summary"]["stuck_in_progress"] == 0
    assert out["summary"]["verdict"] == "healthy"


def test_production_health_company_filter(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["res.company"] = [{"id": 5, "name": "Acme VN"}]
    fake_client.search_responses["mrp.production"] = []
    tools_reports_ops.production_health(company="acme")
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == "mrp.production")
    assert ("company_id", "=", 5) in call["domain"]


def test_behind_start_uses_local_date_of_date_start(fake_client):
    import json
    from datetime import timedelta
    from odoo_pulse import tools_reports_ops
    from odoo_pulse.common.dates import today_in_tz

    today = today_in_tz(7)
    start = (today - timedelta(days=1)).strftime("%Y-%m-%d") + " 20:00:00"
    fake_client.search_responses["mrp.production"] = [{
        "id": 1, "name": "MO1", "product_id": [1, "Widget"],
        "product_qty": 5.0, "state": "confirmed",
        "date_start": start, "date_finished": False,
    }]
    out = json.loads(tools_reports_ops.production_health(timezone_offset=7))
    # planned start is "today" at +7, not in the past -> not behind
    assert out["summary"]["behind_start"] == 0

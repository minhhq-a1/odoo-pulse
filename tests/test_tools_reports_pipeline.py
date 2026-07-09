# tests/test_tools_reports_pipeline.py
import datetime as dt
import json

from odoo_pulse import tools_reports_sales

# today is fixed at 2026-06-30; stalled_days=14 -> stalled if last stage
# change is before 2026-06-16.
LEADS = [
    {"id": 1, "name": "Deal A", "stage_id": [1, "New"], "user_id": [10, "Alice"],
     "expected_revenue": 10000.0, "probability": 20.0,
     "date_deadline": "2026-07-10", "date_last_stage_update": "2026-06-28 09:00:00"},
    {"id": 2, "name": "Deal B", "stage_id": [2, "Proposition"], "user_id": [10, "Alice"],
     "expected_revenue": 50000.0, "probability": 60.0,
     "date_deadline": "2026-06-20", "date_last_stage_update": "2026-06-01 09:00:00"},
    {"id": 3, "name": "Deal C", "stage_id": [1, "New"], "user_id": [11, "Bob"],
     "expected_revenue": 20000.0, "probability": 10.0,
     "date_deadline": False, "date_last_stage_update": "2026-06-29 09:00:00"},
]


def _fix_today(monkeypatch):
    monkeypatch.setattr(tools_reports_sales, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


def test_pipeline_review_builds_domain(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = LEADS
    tools_reports_sales.pipeline_review(salesperson="Alice", team="Direct")
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == "crm.lead")
    assert ("type", "=", "opportunity") in call["domain"]
    assert ("user_id.name", "ilike", "Alice") in call["domain"]
    assert ("team_id.name", "ilike", "Direct") in call["domain"]


def test_pipeline_review_summary_and_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = LEADS
    fake_client.search_count_responses["crm.lead"] = 6
    out = json.loads(tools_reports_sales.pipeline_review())
    s = out["summary"]
    assert s["open_opportunities"] == 3
    assert s["expected_revenue"] == 80000.0
    assert s["weighted_revenue"] == 34000.0   # 10000*.2 + 50000*.6 + 20000*.1
    assert s["stalled"] == 1                  # Deal B, idle since 2026-06-01
    assert s["overdue_close_date"] == 1       # Deal B, due 2026-06-20
    assert s["closing_soon"] == 1             # Deal A, due 2026-07-10 (<=30d)
    assert s["no_close_date"] == 1            # Deal C
    assert s["win_rate_pct"] == 50.0          # fake counts: 6 won / 6 lost
    assert s["verdict"] == "at_risk"          # stalled 33.3% >= 25
    assert out["tool"] == "pipeline_review"
    assert out["as_of"] == "2026-06-30"


def _win_lost_calls(fake_client):
    counts = [c for c in fake_client.calls
              if c["method"] == "search_count" and c["model"] == "crm.lead"]
    won = next(c for c in counts if ("probability", "=", 100) in c["domain"])
    lost = next(c for c in counts if ("active", "=", False) in c["domain"])
    return won, lost


def test_pipeline_review_win_rate_count_domains(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = LEADS
    tools_reports_sales.pipeline_review()
    won, lost = _win_lost_calls(fake_client)
    # today - 90d = 2026-04-01, expressed as a UTC bound at +7 (default offset)
    assert ("date_closed", ">=", "2026-03-31 17:00:00") in won["domain"]
    assert ("probability", "=", 0) in lost["domain"]
    assert ("date_closed", ">=", "2026-03-31 17:00:00") in lost["domain"]


def test_pipeline_review_win_rate_respects_owner_filter(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = LEADS
    tools_reports_sales.pipeline_review(salesperson="Alice", team="Direct")
    won, lost = _win_lost_calls(fake_client)
    # A filtered report must scope the win/lost counts to the same owner,
    # not report a company-wide rate against one person's pipeline.
    for call in (won, lost):
        assert ("user_id.name", "ilike", "Alice") in call["domain"]
        assert ("team_id.name", "ilike", "Direct") in call["domain"]


def test_pipeline_review_breakdown_and_risks(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = LEADS
    out = json.loads(tools_reports_sales.pipeline_review())
    stages = {r["stage"]: r for r in out["breakdown"]["by_stage"]}
    assert stages["New"]["count"] == 2
    assert stages["New"]["expected_revenue"] == 30000.0
    reps = {r["salesperson"]: r for r in out["breakdown"]["by_salesperson"]}
    assert reps["Alice"]["expected_revenue"] == 60000.0
    stalled = out["breakdown"]["stalled_deals"]
    assert stalled[0]["name"] == "Deal B"
    assert stalled[0]["idle_days"] == 29
    codes = {r["code"] for r in out["risks"]}
    assert codes == {"stalled_deals", "overdue_close_dates"}


def test_pipeline_review_off_track_when_half_stalled(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    stale = [dict(LEADS[0]), dict(LEADS[1]), dict(LEADS[2])]
    stale[2]["date_last_stage_update"] = "2026-05-01 09:00:00"  # 2 of 3 stalled
    fake_client.search_responses["crm.lead"] = stale
    out = json.loads(tools_reports_sales.pipeline_review())
    assert out["summary"]["verdict"] == "off_track"


def test_pipeline_review_empty_pipeline_is_at_risk(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = []
    out = json.loads(tools_reports_sales.pipeline_review())
    assert out["summary"]["verdict"] == "at_risk"
    assert any(r["code"] == "empty_pipeline" for r in out["risks"])


def test_pipeline_review_custom_thresholds(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    # 1 of 3 deals stalled = 33.3% -> at_risk under defaults,
    # off_track when the off_track cut-off is lowered to 30.
    fake_client.search_responses["crm.lead"] = LEADS  # existing canned rows
    fake_client.search_count_responses["crm.lead"] = 0
    out = json.loads(tools_reports_sales.pipeline_review(
        stalled_pct_off_track=30.0, stalled_pct_at_risk=10.0))
    assert out["summary"]["verdict"] == "off_track"
    assert out["thresholds"] == {
        "stalled_pct_at_risk": 10.0, "stalled_pct_off_track": 30.0}


def test_pipeline_review_company_filter(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["res.company"] = [{"id": 5, "name": "Acme VN"}]
    fake_client.search_responses["crm.lead"] = []
    fake_client.search_count_responses["crm.lead"] = 0
    tools_reports_sales.pipeline_review(company="acme")
    lead_call = next(c for c in fake_client.calls
                     if c["method"] == "search_read" and c["model"] == "crm.lead")
    assert ("company_id", "=", 5) in lead_call["domain"]
    # win-rate counts share the company scope
    count_call = next(c for c in fake_client.calls
                      if c["method"] == "search_count" and c["model"] == "crm.lead")
    assert ("company_id", "=", 5) in count_call["domain"]


def test_pipeline_review_flags_mixed_companies(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    leads = [dict(l) for l in LEADS]
    leads[0]["company_id"] = [1, "Acme VN"]
    leads[1]["company_id"] = [2, "Acme US"]
    fake_client.search_responses["crm.lead"] = leads
    fake_client.search_count_responses["crm.lead"] = 0
    out = json.loads(tools_reports_sales.pipeline_review())
    codes = [r["code"] for r in out["risks"]]
    assert "mixed_companies" in codes


def test_stalled_uses_local_date_of_stage_update(fake_client):
    import json
    from datetime import date, timedelta
    from odoo_pulse import tools_reports_sales
    from odoo_pulse.workflow_helpers import today_in_tz

    today = today_in_tz(7)
    # stage moved 20:00 UTC "15 days ago by UTC date" == 14 days ago at +7
    moved = (today - timedelta(days=15)).strftime("%Y-%m-%d") + " 20:00:00"
    fake_client.search_responses["crm.lead"] = [{
        "id": 1, "name": "Deal", "stage_id": [1, "New"],
        "user_id": [1, "Rep"], "expected_revenue": 100.0,
        "probability": 10.0, "date_deadline": False,
        "date_last_stage_update": moved, "company_id": False,
    }]
    fake_client.search_count_responses["crm.lead"] = 0
    out = json.loads(tools_reports_sales.pipeline_review(stalled_days=14,
                                                   timezone_offset=7))
    # at +7 the move happened 14 days ago -> NOT yet stalled (cutoff is <)
    assert out["summary"]["stalled"] == 0


def test_pipeline_review_splits_revenue_by_currency(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    leads = [dict(l) for l in LEADS]
    leads[0]["company_currency"] = [1, "VND"]   # 10000 @ 20%
    leads[1]["company_currency"] = [2, "USD"]   # 50000 @ 60%
    leads[2]["company_currency"] = [1, "VND"]   # 20000 @ 10%
    fake_client.search_responses["crm.lead"] = leads
    fake_client.search_count_responses["crm.lead"] = 0
    out = json.loads(tools_reports_sales.pipeline_review())
    s = out["summary"]
    assert s["expected_revenue_by_currency"] == {"VND": 30000.0, "USD": 50000.0}
    assert s["weighted_revenue_by_currency"] == {"VND": 4000.0, "USD": 30000.0}
    assert any(r["code"] == "mixed_currencies" for r in out["risks"])


def test_pipeline_review_single_currency_no_mixed_risk(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    leads = [dict(l) for l in LEADS]
    for l in leads:
        l["company_currency"] = [1, "VND"]
    fake_client.search_responses["crm.lead"] = leads
    fake_client.search_count_responses["crm.lead"] = 0
    out = json.loads(tools_reports_sales.pipeline_review())
    assert out["summary"]["expected_revenue_by_currency"] == {"VND": 80000.0}
    assert not any(r["code"] == "mixed_currencies" for r in out["risks"])


def test_pipeline_review_requests_company_currency_field(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = LEADS
    tools_reports_sales.pipeline_review()
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == "crm.lead")
    assert "company_currency" in call["fields"]


def _many_leads(n=200):
    return [{"id": i, "name": f"Deal {i}", "stage_id": [1, "New"],
             "user_id": [10, "Alice"], "expected_revenue": 100.0,
             "probability": 50.0, "date_deadline": False,
             "date_last_stage_update": "2026-06-28 09:00:00",
             "company_id": False, "company_currency": False}
            for i in range(1, n + 1)]


def test_pipeline_review_truncated_uses_server_side_totals(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    # 200 fetched rows == the cap -> fetch_with_truncation probes the count.
    fake_client.search_responses["crm.lead"] = _many_leads(200)
    fake_client.aggregate_responses_seq["crm.lead"] = [
        [{"expected_revenue:sum": 123456.0, "__count": 500}]]

    def hook(model, domain):
        # today fixed at 2026-06-30 (+7): stalled cutoff 2026-06-16 ->
        # utc bound "2026-06-15 17:00:00"; close cutoff 2026-07-30.
        if ("date_last_stage_update", "<", "2026-06-15 17:00:00") in domain:
            return 300                                   # stalled, full pop
        if ("date_deadline", "<", "2026-06-30") in domain:
            return 30                                    # overdue close
        if ("date_deadline", ">=", "2026-06-30") in domain:
            return 20                                    # closing soon
        if ("date_deadline", "=", False) in domain:
            return 450                                   # no close date
        if ("probability", "=", 100) in domain:
            return 10                                    # won
        if ("active", "=", False) in domain:
            return 10                                    # lost
        return 500                                       # truncation probe

    fake_client.search_count_hook = hook
    out = json.loads(tools_reports_sales.pipeline_review())
    s = out["summary"]
    assert s["truncated"] is True
    assert s["open_opportunities"] == 500        # full population, not 200
    assert s["expected_revenue"] == 123456.0     # server-side aggregate
    assert s["stalled"] == 300
    assert s["stalled_pct"] == 60.0
    assert s["verdict"] == "off_track"           # 60% >= 50 over FULL data
    assert s["overdue_close_date"] == 30
    assert s["closing_soon"] == 20
    assert s["no_close_date"] == 450
    assert set(s["partial_fields"]) == {
        "weighted_revenue", "expected_revenue_by_currency",
        "weighted_revenue_by_currency"}
    trunc = next(r for r in out["risks"] if r["code"] == "truncated_data")
    assert "top 200" in trunc["message"]


def test_pipeline_review_not_truncated_has_no_partial_fields(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = LEADS
    fake_client.search_count_responses["crm.lead"] = 0
    out = json.loads(tools_reports_sales.pipeline_review())
    assert "partial_fields" not in out["summary"]
    assert "truncated" not in out["summary"]



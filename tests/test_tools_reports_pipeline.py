# tests/test_tools_reports_pipeline.py
import datetime as dt
import json

from odoo_pulse import tools_reports

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
    monkeypatch.setattr(tools_reports, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


def test_pipeline_review_builds_domain(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = LEADS
    tools_reports.pipeline_review(salesperson="Alice", team="Direct")
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == "crm.lead")
    assert ("type", "=", "opportunity") in call["domain"]
    assert ("user_id.name", "ilike", "Alice") in call["domain"]
    assert ("team_id.name", "ilike", "Direct") in call["domain"]


def test_pipeline_review_summary_and_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = LEADS
    fake_client.search_count_responses["crm.lead"] = 6
    out = json.loads(tools_reports.pipeline_review())
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


def test_pipeline_review_win_rate_count_domains(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = LEADS
    tools_reports.pipeline_review()
    counts = [c for c in fake_client.calls if c["method"] == "search_count"]
    assert len(counts) == 2
    won, lost = counts
    assert ("probability", "=", 100) in won["domain"]
    assert ("date_closed", ">=", "2026-04-01") in won["domain"]  # today - 90d
    assert ("active", "=", False) in lost["domain"]
    assert ("probability", "=", 0) in lost["domain"]


def test_pipeline_review_win_rate_respects_owner_filter(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = LEADS
    tools_reports.pipeline_review(salesperson="Alice", team="Direct")
    won, lost = [c for c in fake_client.calls if c["method"] == "search_count"]
    # A filtered report must scope the win/lost counts to the same owner,
    # not report a company-wide rate against one person's pipeline.
    for call in (won, lost):
        assert ("user_id.name", "ilike", "Alice") in call["domain"]
        assert ("team_id.name", "ilike", "Direct") in call["domain"]


def test_pipeline_review_breakdown_and_risks(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = LEADS
    out = json.loads(tools_reports.pipeline_review())
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
    out = json.loads(tools_reports.pipeline_review())
    assert out["summary"]["verdict"] == "off_track"


def test_pipeline_review_empty_pipeline_is_at_risk(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["crm.lead"] = []
    out = json.loads(tools_reports.pipeline_review())
    assert out["summary"]["verdict"] == "at_risk"
    assert any(r["code"] == "empty_pipeline" for r in out["risks"])


def test_pipeline_review_custom_thresholds(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    # 1 of 3 deals stalled = 33.3% -> at_risk under defaults,
    # off_track when the off_track cut-off is lowered to 30.
    fake_client.search_responses["crm.lead"] = LEADS  # existing canned rows
    fake_client.search_count_responses["crm.lead"] = 0
    out = json.loads(tools_reports.pipeline_review(
        stalled_pct_off_track=30.0, stalled_pct_at_risk=10.0))
    assert out["summary"]["verdict"] == "off_track"
    assert out["thresholds"] == {
        "stalled_pct_at_risk": 10.0, "stalled_pct_off_track": 30.0}


def test_pipeline_review_company_filter(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses["res.company"] = [{"id": 5, "name": "Acme VN"}]
    fake_client.search_responses["crm.lead"] = []
    fake_client.search_count_responses["crm.lead"] = 0
    tools_reports.pipeline_review(company="acme")
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
    out = json.loads(tools_reports.pipeline_review())
    codes = [r["code"] for r in out["risks"]]
    assert "mixed_companies" in codes

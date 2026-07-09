# tests/test_tools_reports_absence.py
import datetime as dt
import json

from odoo_pulse import tools_reports

# today fixed at 2026-06-30; days=14 -> window ends 2026-07-14.
APPROVED = [
    {"id": 1, "employee_id": [1, "Alice"], "department_id": [1, "Eng"],
     "date_from": "2026-06-29", "date_to": "2026-07-02",
     "holiday_status_id": [1, "Paid Time Off"], "number_of_days": 4.0},
    {"id": 2, "employee_id": [2, "Bob"], "department_id": [1, "Eng"],
     "date_from": "2026-07-06", "date_to": "2026-07-10",
     "holiday_status_id": [1, "Paid Time Off"], "number_of_days": 5.0},
    {"id": 3, "employee_id": [3, "Carol"], "department_id": [2, "Sales"],
     "date_from": "2026-06-30", "date_to": "2026-06-30",
     "holiday_status_id": [2, "Sick"], "number_of_days": 1.0},
]
PENDING = [
    {"id": 4, "employee_id": [4, "Dave"], "department_id": [2, "Sales"],
     "date_from": "2026-07-03", "date_to": "2026-07-04"},
]
HEADCOUNT = [
    {"department_id": [1, "Eng"], "__count": 4},
    {"department_id": [2, "Sales"], "__count": 10},
]


def _fix_today(monkeypatch):
    monkeypatch.setattr(tools_reports, "today_in_tz", lambda offset: dt.date(2026, 6, 30))


def _setup(fake_client):
    fake_client.search_responses_seq["hr.leave"] = [list(APPROVED), list(PENDING)]
    fake_client.search_responses["hr.employee"] = HEADCOUNT


def test_absence_overview_builds_domains(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    tools_reports.absence_overview()
    leave_calls = [c for c in fake_client.calls
                   if c["method"] == "search_read" and c["model"] == "hr.leave"]
    approved, pending = leave_calls
    assert ("state", "=", "validate") in approved["domain"]
    # horizon (2026-07-14) + 1 day local midnight at +7, in UTC; and today's
    # local midnight at +7, in UTC (default offset=7).
    assert ("date_from", "<", "2026-07-14 17:00:00") in approved["domain"]
    assert ("date_to", ">=", "2026-06-29 17:00:00") in approved["domain"]
    assert ("state", "in", ["confirm", "validate1"]) in pending["domain"]


def test_absence_overview_summary_and_verdict(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_reports.absence_overview())
    s = out["summary"]
    assert s["off_today"] == 2            # Alice, Carol
    assert s["off_in_window"] == 3
    assert s["pending_approvals"] == 1
    assert s["verdict"] == "action_needed"  # pending + Eng coverage 2/4 = 0.5
    assert out["tool"] == "absence_overview"


def test_absence_overview_department_coverage(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    _setup(fake_client)
    out = json.loads(tools_reports.absence_overview())
    depts = {d["department"]: d for d in out["breakdown"]["by_department"]}
    assert depts["Eng"] == {"department": "Eng", "off_in_window": 2,
                            "headcount": 4, "coverage_risk": True}
    assert depts["Sales"]["coverage_risk"] is False
    codes = {r["code"] for r in out["risks"]}
    assert codes == {"pending_approvals", "thin_coverage"}


def test_absence_overview_clear_when_quiet(fake_client, monkeypatch):
    _fix_today(monkeypatch)
    fake_client.search_responses_seq["hr.leave"] = [[APPROVED[2]], []]
    fake_client.search_responses["hr.employee"] = HEADCOUNT
    out = json.loads(tools_reports.absence_overview())
    assert out["summary"]["verdict"] == "clear"
    assert out["risks"] == []


def test_off_today_counts_leave_ending_late_utc_yesterday(fake_client):
    import json
    from datetime import timedelta
    from odoo_pulse import tools_reports
    from odoo_pulse.workflow_helpers import today_in_tz

    today = today_in_tz(7)
    # ends 18:00 UTC "yesterday by UTC date" == 01:00 today at +7 -> off today
    frm = (today - timedelta(days=2)).strftime("%Y-%m-%d") + " 01:00:00"
    to = (today - timedelta(days=1)).strftime("%Y-%m-%d") + " 18:00:00"
    fake_client.search_responses_seq["hr.leave"] = [
        [{"id": 1, "employee_id": [1, "An"], "department_id": [1, "Dev"],
          "date_from": frm, "date_to": to,
          "holiday_status_id": [1, "PTO"], "number_of_days": 2.0}],
        [],  # pending queue
    ]
    fake_client.search_responses["hr.employee"] = []
    out = json.loads(tools_reports.absence_overview(timezone_offset=7))
    assert out["summary"]["off_today"] == 1


def test_absence_overview_fetches_concurrently(fake_client, monkeypatch):
    import threading

    _fix_today(monkeypatch)
    _setup(fake_client)
    # The first hr.leave fetch (leaves thunk) and the hr.employee headcount
    # aggregate (headcount thunk) must be in flight AT THE SAME TIME;
    # sequential execution would break the barrier, error the report and
    # fail the summary assertion. The pending hr.leave fetch passes through.
    barrier = threading.Barrier(2, timeout=2)
    seen = {"n": 0}
    orig_read = fake_client.search_read
    orig_agg = fake_client.aggregate_records

    def spying_read(*args, **kwargs):
        seen["n"] += 1
        if seen["n"] == 1:
            barrier.wait()
        return orig_read(*args, **kwargs)

    def spying_aggregate(*args, **kwargs):
        barrier.wait()
        return orig_agg(*args, **kwargs)

    monkeypatch.setattr(fake_client, "search_read", spying_read)
    monkeypatch.setattr(fake_client, "aggregate_records", spying_aggregate)
    out = json.loads(tools_reports.absence_overview())
    assert out["summary"]["off_today"] == 2
    assert out["summary"]["pending_approvals"] == 1

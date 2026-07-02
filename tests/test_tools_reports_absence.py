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
    assert ("date_from", "<=", "2026-07-14") in approved["domain"]
    assert ("date_to", ">=", "2026-06-30") in approved["domain"]
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

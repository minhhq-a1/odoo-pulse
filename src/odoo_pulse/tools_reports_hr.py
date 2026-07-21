# odoo_pulse/tools_reports_hr.py
"""HR report tools: who is off and where coverage is thin.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from datetime import timedelta

from .common.dates import parse_when, today_in_tz, utc_bound
from .common.paging import fetch_with_truncation
from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .workflow_helpers import (
    build_report,
    gather_strict,
)


@mcp.tool()
def absence_overview(
    days: int = 14,
    coverage_threshold: float = 0.3,
    timezone_offset: int = 7,
) -> str:
    """Report who is off and where coverage is thin, in one call.

    Composes approved hr.leave records overlapping the next `days` days,
    pending approval requests, and per-department headcount into an
    absence calendar, coverage-risk flags (share of a department off at
    some point in the window >= coverage_threshold), and a verdict.

    Args:
        days: Look-ahead window in days (default 14).
        coverage_threshold: Department share off in the window that counts
            as a coverage risk (default 0.3).
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        horizon = today + timedelta(days=days)

        def leave_lists():
            # Both hr.leave fetches share one thunk (ordered) so they never
            # race each other (real Odoo or the fake's per-model queue).
            approved = fetch_with_truncation(
                client, "hr.leave",
                [("state", "=", "validate"),
                 ("date_from", "<",
                  utc_bound(horizon + timedelta(days=1), timezone_offset)),
                 ("date_to", ">=", utc_bound(today, timezone_offset))],
                fields=["id", "employee_id", "department_id", "date_from",
                        "date_to", "holiday_status_id", "number_of_days"],
                limit=200, order="date_from",
            )
            pending = fetch_with_truncation(
                client, "hr.leave",
                [("state", "in", ["confirm", "validate1"])],
                fields=["id", "employee_id", "department_id", "date_from",
                        "date_to"],
                limit=200, order="date_from",
            )
            return approved, pending

        def department_headcount():
            return client.aggregate_records(
                "hr.employee", group_by=["department_id"], measures=[],
                domain=[], limit=200,
            )

        fetched = gather_strict(
            {"leaves": leave_lists, "headcount": department_headcount})
        (approved, approved_trunc), (pending, pending_trunc) = fetched["leaves"]
        agg = fetched["headcount"]

        headcount: dict[str, int] = {}
        for row in agg.get("rows", []):
            dept = row["department_id"][1] if row.get("department_id") else "(none)"
            headcount[dept] = (row.get("__count")
                               or row.get("department_id_count") or 0)

        off_today_ids: set[int] = set()
        dept_off: dict[str, set[int]] = {}
        upcoming: list[dict] = []
        for leave in approved:
            emp = leave.get("employee_id") or [0, "(unknown)"]
            dept = (leave["department_id"][1]
                    if leave.get("department_id") else "(none)")
            start = parse_when(leave.get("date_from"), timezone_offset)
            end = parse_when(leave.get("date_to"), timezone_offset)
            if start and end and start <= today <= end:
                off_today_ids.add(emp[0])
            dept_off.setdefault(dept, set()).add(emp[0])
            upcoming.append({
                "employee": emp[1], "department": dept,
                "type": (leave["holiday_status_id"][1]
                         if leave.get("holiday_status_id") else None),
                "from": leave.get("date_from"), "to": leave.get("date_to"),
                "days": leave.get("number_of_days") or 0.0,
            })

        by_department = []
        thin = 0
        for dept, emp_ids in sorted(dept_off.items()):
            count = headcount.get(dept, 0)
            risk = bool(count) and (len(emp_ids) / count) >= coverage_threshold
            if risk:
                thin += 1
            by_department.append({
                "department": dept, "off_in_window": len(emp_ids),
                "headcount": count, "coverage_risk": risk,
            })

        off_in_window = len({e for ids in dept_off.values() for e in ids})
        verdict = "action_needed" if (pending or thin) else "clear"

        summary = {
            "off_today": len(off_today_ids),
            "off_in_window": off_in_window,
            "pending_approvals": len(pending),
            "departments_at_risk": thin,
            "verdict": verdict,
        }
        for trunc in (approved_trunc, pending_trunc):
            if trunc:
                summary["truncated"] = True

        highlights = [f"{len(off_today_ids)} off today, "
                      f"{off_in_window} off within {days} days"]
        if pending:
            highlights.append(f"{len(pending)} request(s) awaiting approval")

        risks: list[dict] = []
        for trunc in (approved_trunc, pending_trunc):
            if trunc:
                risks.append({
                    "code": "truncated_data", "count": trunc["missing"],
                    "message": (
                        f"Report covers only {trunc['fetched']} of "
                        f"{trunc['total_matching']} matching leave records."
                    ),
                })
        if pending:
            risks.append({
                "code": "pending_approvals", "count": len(pending),
                "message": f"{len(pending)} leave request(s) awaiting approval",
            })
        if thin:
            risks.append({
                "code": "thin_coverage", "count": thin,
                "message": (f"{thin} department(s) with >= "
                            f"{int(coverage_threshold * 100)}% of staff off "
                            "in the window"),
            })

        return build_report(
            "absence_overview", today,
            summary=summary,
            breakdown={"by_department": by_department, "leaves": upcoming},
            highlights=highlights, risks=risks,
            extra={"days": days},
        )

    return safe(run)

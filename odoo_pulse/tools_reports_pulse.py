# odoo_pulse/tools_reports_pulse.py
"""Cross-department pulse report: the one-call company briefing.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from datetime import timedelta

from .odoo_client import OdooError
from .runtime import get_client, mcp, safe
from .workflow_helpers import (
    build_report,
    gather,
    resolve_company_id,
    today_in_tz,
    utc_bound,
)


@mcp.tool()
def business_pulse(
    timezone_offset: int = 7,
    company: str | int | None = None,
) -> str:
    """One-call company briefing: sales, leads, receivables, tasks, absences.

    The morning-standup view of the whole company: yesterday's confirmed
    revenue and new leads, overdue customer invoices, tasks past deadline,
    and who is off today. Sections are independent — if an app is not
    installed, its section reports available=false and the rest still
    renders.

    Args:
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
        company: Optional company name (ilike) or id; scopes every section.
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        yesterday = today - timedelta(days=1)
        y_lo = utc_bound(yesterday, timezone_offset)
        y_hi = utc_bound(today, timezone_offset)
        t_hi = utc_bound(today + timedelta(days=1), timezone_offset)
        company_id = resolve_company_id(client, company)
        company_domain: list = (
            [("company_id", "=", company_id)] if company_id else [])
        sections: dict[str, dict] = {}

        def sales_yesterday() -> dict:
            rows = client.search_read(
                "sale.order",
                domain=[("state", "in", ["sale", "done"]),
                        ("date_order", ">=", y_lo),
                        ("date_order", "<", y_hi),
                        *company_domain],
                fields=["id", "amount_total"], limit=200,
            )
            return {"orders": len(rows),
                    "revenue": round(sum(r.get("amount_total") or 0.0
                                         for r in rows), 2)}

        def new_leads() -> dict:
            n = client.search_count("crm.lead", [
                ("create_date", ">=", y_lo),
                ("create_date", "<", y_hi),
                *company_domain])
            return {"new_leads": n}

        def overdue_invoices() -> dict:
            rows = client.search_read(
                "account.move",
                domain=[("move_type", "=", "out_invoice"),
                        ("state", "=", "posted"),
                        ("payment_state", "in", ["not_paid", "partial"]),
                        ("invoice_date_due", "<", today.isoformat()),
                        *company_domain],
                fields=["id", "amount_residual"], limit=200,
            )
            return {"overdue_invoices": len(rows),
                    "overdue_amount": round(sum(r.get("amount_residual") or 0.0
                                                for r in rows), 2)}

        def overdue_tasks() -> dict:
            # date_deadline is a Date field on most versions; kept as a plain date bound deliberately (see plan Task 2) — do not "fix" to utc_bound.
            n = client.search_count("project.task", [
                ("date_deadline", "<", today.isoformat()),
                ("stage_id.fold", "=", False),
                *company_domain])
            return {"overdue_tasks": n}

        def people_off() -> dict:
            n = client.search_count("hr.leave", [
                ("state", "=", "validate"),
                ("date_from", "<", t_hi),
                ("date_to", ">=", y_hi),
                *company_domain])
            return {"off_today": n}

        outcomes = gather({
            "sales": sales_yesterday,
            "crm": new_leads,
            "receivables": overdue_invoices,
            "projects": overdue_tasks,
            "hr": people_off,
        })
        for name, outcome in outcomes.items():
            if isinstance(outcome, OdooError):
                # An app that isn't installed degrades its own section only.
                sections[name] = {"available": False, "reason": str(outcome)}
            elif isinstance(outcome, Exception):
                raise outcome
            else:
                sections[name] = {"available": True, **outcome}

        attention = (
            sections["receivables"].get("overdue_invoices", 0) > 0
            or sections["projects"].get("overdue_tasks", 0) > 0
        )
        verdict = "attention" if attention else "all_clear"
        unavailable = [k for k, v in sections.items() if not v["available"]]

        n_companies = 0
        if company_id is None:
            try:
                n_companies = client.search_count("res.company", [])
            except OdooError:
                n_companies = 0

        summary = {
            "verdict": verdict,
            "sections_available": len(sections) - len(unavailable),
            "sections_unavailable": unavailable,
        }

        highlights = []
        if sections["sales"]["available"]:
            highlights.append(
                f"yesterday: {sections['sales']['orders']} order(s), "
                f"revenue {sections['sales']['revenue']}")
        if sections["crm"]["available"]:
            highlights.append(f"{sections['crm']['new_leads']} new lead(s) yesterday")
        if sections["hr"]["available"] and sections["hr"]["off_today"]:
            highlights.append(f"{sections['hr']['off_today']} people off today")

        risks: list[dict] = []
        if sections["receivables"].get("overdue_invoices"):
            risks.append({
                "code": "overdue_invoices",
                "count": sections["receivables"]["overdue_invoices"],
                "message": (
                    f"{sections['receivables']['overdue_invoices']} customer "
                    f"invoice(s) overdue, "
                    f"{sections['receivables']['overdue_amount']} outstanding"),
            })
        if sections["projects"].get("overdue_tasks"):
            risks.append({
                "code": "overdue_tasks",
                "count": sections["projects"]["overdue_tasks"],
                "message": (f"{sections['projects']['overdue_tasks']} task(s) "
                            "past deadline"),
            })
        if n_companies > 1:
            risks.append({
                "code": "multi_company_totals", "count": n_companies,
                "message": (
                    f"Instance has {n_companies} companies; section totals mix "
                    "them (and their currencies). Pass company= to scope."),
            })
        for name in unavailable:
            risks.append({
                "code": "section_unavailable", "count": 1,
                "message": f"{name}: {sections[name]['reason']}",
            })

        return build_report(
            "business_pulse", today,
            summary=summary,
            breakdown={"sections": sections},
            highlights=highlights, risks=risks,
            extra={"company": company},
        )

    return safe(run)

"""Business pulse report service."""

from __future__ import annotations

from datetime import timedelta

from ..common.concurrency import gather
from ..common.dates import utc_bound
from ..common.reporting import build_report
from ..core.errors import OdooError
from .crm.metrics import new_leads
from .finance.metrics import overdue_receivables
from .hr.metrics import employees_off
from .projects.metrics import overdue_open_tasks
from .report_context import build_report_context
from .sales.metrics import confirmed_sales


def build_business_pulse(
    client,
    *,
    timezone_offset: int = 7,
    company: str | int | None = None,
) -> dict:
    context = build_report_context(
        client, timezone_offset=timezone_offset, company=company
    )
    today = context.today
    yesterday = today - timedelta(days=1)
    yesterday_start = utc_bound(yesterday, timezone_offset)
    today_start = utc_bound(today, timezone_offset)
    tomorrow_start = utc_bound(today + timedelta(days=1), timezone_offset)

    sections: dict[str, dict] = {}

    outcomes = gather({
        "sales": lambda: confirmed_sales(
            context,
            date_from=yesterday_start,
            date_to_exclusive=today_start,
        ),
        "crm": lambda: new_leads(
            context,
            date_from=yesterday_start,
            date_to_exclusive=today_start,
        ),
        "receivables": lambda: overdue_receivables(
            context, overdue_before=today.isoformat()
        ),
        "projects": lambda: overdue_open_tasks(
            context, overdue_before=today
        ),
        "hr": lambda: employees_off(
            context,
            starts_before=tomorrow_start,
            ends_at_or_after=today_start,
        ),
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
    if context.company_id is None:
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
    mixed_sections = [
        name for name in ("sales", "receivables")
        if sections[name].get("mixed_currencies")
    ]
    if mixed_sections:
        risks.append({
            "code": "mixed_currencies",
            "count": len(mixed_sections),
            "message": (
                "Monetary scalars mix document currencies in section(s): "
                f"{', '.join(mixed_sections)}; use by_currency."),
        })

    return build_report(
        "business_pulse", today,
        summary=summary,
        breakdown={"sections": sections},
        highlights=highlights, risks=risks,
        extra={"company": company},
    )

"""Narrow CRM metrics shared by cross-domain reports."""

from __future__ import annotations

from ..report_context import ReportContext


def new_leads(
    context: ReportContext,
    *,
    date_from: str,
    date_to_exclusive: str,
) -> dict:
    count = context.client.search_count("crm.lead", [
        ("create_date", ">=", date_from),
        ("create_date", "<", date_to_exclusive),
        *context.company_domain,
    ])
    return {"new_leads": count}

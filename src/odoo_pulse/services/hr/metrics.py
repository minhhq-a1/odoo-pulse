"""Narrow HR metrics shared by cross-domain reports."""

from __future__ import annotations

from ...common.paging import paged_search_read
from ..report_context import ReportContext


def approved_leave_domain(
    context: ReportContext,
    *,
    starts_before: str,
    ends_at_or_after: str,
) -> list:
    return [
        ("state", "=", "validate"),
        ("date_from", "<", starts_before),
        ("date_to", ">=", ends_at_or_after),
        *context.company_domain,
    ]


def distinct_employee_count(rows: list[dict]) -> int:
    return len({
        row["employee_id"][0] for row in rows if row.get("employee_id")
    })


def employees_off(
    context: ReportContext,
    *,
    starts_before: str,
    ends_at_or_after: str,
) -> dict:
    rows = paged_search_read(
        context.client,
        "hr.leave",
        approved_leave_domain(
            context,
            starts_before=starts_before,
            ends_at_or_after=ends_at_or_after,
        ),
        fields=["employee_id"],
    )
    return {"off_today": distinct_employee_count(rows)}

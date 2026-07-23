"""Narrow project metrics consumed by cross-domain reports."""

from __future__ import annotations

from datetime import date

from ...common.dates import utc_bound
from ...core.errors import OdooError
from ..report_context import ReportContext


def overdue_open_tasks(
    context: ReportContext, *, overdue_before: date,
) -> dict:
    schema = context.client.fields_get(
        "project.task", attributes=["type"]
    )
    deadline = schema.get("date_deadline")
    if deadline is None:
        raise OdooError(
            "Field 'date_deadline' does not exist on project.task."
        )
    bound = (
        utc_bound(overdue_before, context.timezone_offset)
        if deadline.get("type") == "datetime"
        else overdue_before.isoformat()
    )
    count = context.client.search_count("project.task", [
        ("date_deadline", "<", bound),
        ("stage_id.fold", "=", False),
        *context.company_domain,
    ])
    return {"overdue_tasks": count}

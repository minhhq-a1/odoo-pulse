# odoo_pulse/tools_reports_pulse.py
"""Cross-department pulse report: the one-call company briefing.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .services.pulse import build_business_pulse


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
    return safe(lambda: build_business_pulse(
        get_client(), timezone_offset=timezone_offset, company=company,
    ))

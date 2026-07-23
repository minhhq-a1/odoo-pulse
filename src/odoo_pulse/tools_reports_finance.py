# odoo_pulse/tools_reports_finance.py
"""Finance report tools: AR/AP aging and who owes what.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .services.finance.receivables import build_receivables_health


@mcp.tool()
def receivables_health(
    top_n: int = 5,
    timezone_offset: int = 7,
    company: str | int | None = None,
    overdue_pct_at_risk: float = 25.0,
    overdue_pct_off_track: float = 50.0,
) -> str:
    """Report AR/AP aging and who owes what, in one call.

    Composes open posted invoices and vendor bills into standard aging
    buckets (not_due / 1-30 / 31-60 / 61-90 / 90+), the share of
    receivables overdue, the top overdue customers, and a verdict.

    Args:
        top_n: Rows in the top-overdue-customers list (default 5).
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
        company: Optional company name (ilike) or id to scope the report.
        overdue_pct_at_risk: Overdue AR share (%) that drops the verdict
            to at_risk (default 25).
        overdue_pct_off_track: Overdue AR share (%) that drops the verdict
            to off_track (default 50).
    """
    return safe(lambda: build_receivables_health(
        get_client(), top_n=top_n, timezone_offset=timezone_offset,
        company=company, overdue_pct_at_risk=overdue_pct_at_risk,
        overdue_pct_off_track=overdue_pct_off_track,
    ))


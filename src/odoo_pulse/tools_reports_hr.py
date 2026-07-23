# odoo_pulse/tools_reports_hr.py
"""HR report tools: who is off and where coverage is thin.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .services.hr.absence import build_absence_overview


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
    return safe(lambda: build_absence_overview(
        get_client(), days=days, coverage_threshold=coverage_threshold,
        timezone_offset=timezone_offset,
    ))


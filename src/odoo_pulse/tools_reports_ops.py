# odoo_pulse/tools_reports_ops.py
"""Operations report tools: purchasing and manufacturing health.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .services.operations.procurement import build_procurement_watch
from .services.operations.production import build_production_health


@mcp.tool()
def procurement_watch(
    late_grace_days: int = 0,
    rfq_stale_days: int = 7,
    top_n: int = 5,
    timezone_offset: int = 7,
    company: str | int | None = None,
) -> str:
    """Report purchasing health — late receipts and stale RFQs — in one call.

    Composes confirmed purchase orders into open value, receipts past their
    planned date, per-vendor open spend, plus a count of quotation requests
    (draft/sent) older than rfq_stale_days, and a rule-based verdict.

    Args:
        late_grace_days: Days past date_planned before a receipt counts as
            late (default 0).
        rfq_stale_days: Age in days after which a draft/sent RFQ counts as
            stale (default 7).
        top_n: Rows in the late-receipts / top-vendors lists (default 5).
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
        company: Optional company name (ilike) or id to scope the report.
    """
    return safe(lambda: build_procurement_watch(
        get_client(), late_grace_days=late_grace_days,
        rfq_stale_days=rfq_stale_days, top_n=top_n,
        timezone_offset=timezone_offset, company=company,
    ))


@mcp.tool()
def production_health(
    stuck_days: int = 14,
    top_n: int = 5,
    timezone_offset: int = 7,
    company: str | int | None = None,
) -> str:
    """Report manufacturing health — late starts and stuck orders — in one call.

    Composes open mrp.production orders (confirmed / progress / to_close)
    into a by-state backlog, orders that should have started but haven't
    (confirmed with date_start in the past), orders running longer than
    stuck_days, and a rule-based verdict.

    Args:
        stuck_days: Days an order may run (progress/to_close) before it
            counts as stuck (default 14).
        top_n: Rows in the behind-start / stuck lists (default 5).
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
        company: Optional company name (ilike) or id to scope the report.
    """
    return safe(lambda: build_production_health(
        get_client(), stuck_days=stuck_days, top_n=top_n,
        timezone_offset=timezone_offset, company=company,
    ))

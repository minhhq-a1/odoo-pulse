"""Sales report tools."""

from __future__ import annotations

from ...mcp.app import mcp
from ...mcp.result import safe
from ...mcp.runtime import get_client
from ...services.sales.snapshot import build_sales_snapshot


@mcp.tool()
def sales_snapshot(
    period_days: int = 7,
    stale_quote_days: int = 7,
    top_n: int = 5,
    timezone_offset: int = 7,
    growth_threshold_pct: float = 10.0,
    company: str | int | None = None,
    trend_weeks: int = 8,
) -> str:
    """Report how sales are going versus the previous period, in one call.

    Composes confirmed sale.order records over the last two periods into
    revenue/order deltas, top customers, top products (server-side
    aggregate over order lines), a stale-quotation count, and a
    growing / steady / declining verdict.

    Args:
        period_days: Length of the comparison window in days (default 7).
        stale_quote_days: Age in days after which a draft/sent quotation
            counts as stale (default 7).
        top_n: Rows in the top-customers / top-products lists (default 5).
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
        growth_threshold_pct: Delta (%) beyond which the verdict is
            growing / declining (default 10).
        company: Optional company name (ilike) or id to scope the report.
        trend_weeks: Weeks of history bucketed into the weekly_revenue
            trend series; 0 disables the extra query (default 8).
    """
    return safe(lambda: build_sales_snapshot(
        get_client(), period_days=period_days,
        stale_quote_days=stale_quote_days, top_n=top_n,
        timezone_offset=timezone_offset,
        growth_threshold_pct=growth_threshold_pct,
        company=company, trend_weeks=trend_weeks,
    ))

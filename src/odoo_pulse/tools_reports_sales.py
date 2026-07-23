# odoo_pulse/tools_reports_sales.py
"""Sales report tools: CRM pipeline health and the revenue snapshot.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .services.crm.pipeline import build_pipeline_review
from .services.sales.snapshot import build_sales_snapshot


@mcp.tool()
def pipeline_review(
    salesperson: str | None = None,
    team: str | None = None,
    stalled_days: int = 14,
    lookahead_days: int = 30,
    win_rate_days: int = 90,
    top_n: int = 5,
    timezone_offset: int = 7,
    company: str | int | None = None,
    stalled_pct_at_risk: float = 25.0,
    stalled_pct_off_track: float = 50.0,
) -> str:
    """Report the health of the CRM pipeline, in one call.

    Composes open crm.lead opportunities into totals (count, expected and
    probability-weighted revenue), stalled deals (no stage change in
    stalled_days), close-date buckets, per-stage / per-salesperson
    breakdowns, the recent win rate, and a rule-based verdict.

    Args:
        salesperson: Optional filter on user_id.name (ilike).
        team: Optional filter on team_id.name (ilike).
        stalled_days: Days without a stage change before a deal counts as
            stalled (default 14).
        lookahead_days: Days ahead that count as "closing soon" (default 30).
        win_rate_days: Look-back window for the won/lost ratio (default 90).
        top_n: Max stalled deals listed in the breakdown (default 5).
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
        company: Optional company name (ilike) or id; scopes every count
            and total to that company.
        stalled_pct_at_risk: Stalled share (%) at which the verdict drops
            to at_risk (default 25).
        stalled_pct_off_track: Stalled share (%) at which the verdict drops
            to off_track (default 50).
    """
    return safe(lambda: build_pipeline_review(
        get_client(), salesperson=salesperson, team=team,
        stalled_days=stalled_days, lookahead_days=lookahead_days,
        win_rate_days=win_rate_days, top_n=top_n,
        timezone_offset=timezone_offset, company=company,
        stalled_pct_at_risk=stalled_pct_at_risk,
        stalled_pct_off_track=stalled_pct_off_track,
    ))


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

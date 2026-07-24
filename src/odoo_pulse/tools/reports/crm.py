"""CRM report tools."""

from __future__ import annotations

from ...mcp.app import mcp
from ...mcp.result import safe
from ...mcp.runtime import get_client
from ...services.crm.pipeline import build_pipeline_review


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

# odoo_pulse/tools_reports.py
"""Cross-department report tools: one business question answered per call.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from datetime import timedelta

from .runtime import get_client, mcp, safe
from .workflow_helpers import (
    build_report,
    fetch_with_truncation,
    parse_deadline,
    today_in_tz,
)


@mcp.tool()
def pipeline_review(
    salesperson: str | None = None,
    team: str | None = None,
    stalled_days: int = 14,
    lookahead_days: int = 30,
    win_rate_days: int = 90,
    top_n: int = 5,
    timezone_offset: int = 7,
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
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)

        domain: list = [("type", "=", "opportunity")]
        if salesperson:
            domain.append(("user_id.name", "ilike", salesperson))
        if team:
            domain.append(("team_id.name", "ilike", team))

        leads, truncation = fetch_with_truncation(
            client, "crm.lead", domain,
            fields=["id", "name", "stage_id", "user_id", "expected_revenue",
                    "probability", "date_deadline", "date_last_stage_update"],
            limit=200, order="expected_revenue desc",
        )

        since = (today - timedelta(days=win_rate_days)).isoformat()
        won = client.search_count("crm.lead", [
            ("type", "=", "opportunity"), ("probability", "=", 100),
            ("date_closed", ">=", since)])
        lost = client.search_count("crm.lead", [
            ("type", "=", "opportunity"), ("active", "=", False),
            ("probability", "=", 0), ("date_closed", ">=", since)])
        win_rate = round(won / (won + lost) * 100, 1) if (won + lost) else None

        stalled_cutoff = today - timedelta(days=stalled_days)
        close_cutoff = today + timedelta(days=lookahead_days)

        total = len(leads)
        expected_total = weighted_total = 0.0
        stalled: list[dict] = []
        overdue_close = closing_soon = no_close_date = 0
        by_stage: dict[str, dict] = {}
        by_rep: dict[str, dict] = {}

        for lead in leads:
            revenue = lead.get("expected_revenue") or 0.0
            prob = lead.get("probability") or 0.0
            expected_total += revenue
            weighted_total += revenue * prob / 100.0

            stage = lead["stage_id"][1] if lead.get("stage_id") else "(none)"
            srec = by_stage.setdefault(
                stage, {"stage": stage, "count": 0, "expected_revenue": 0.0})
            srec["count"] += 1
            srec["expected_revenue"] += revenue

            rep = lead["user_id"][1] if lead.get("user_id") else "(unassigned)"
            rrec = by_rep.setdefault(
                rep, {"salesperson": rep, "count": 0, "expected_revenue": 0.0})
            rrec["count"] += 1
            rrec["expected_revenue"] += revenue

            moved = parse_deadline(lead.get("date_last_stage_update"))
            if moved is not None and moved < stalled_cutoff:
                stalled.append({
                    "name": lead["name"], "stage": stage, "salesperson": rep,
                    "expected_revenue": revenue,
                    "idle_days": (today - moved).days,
                })

            close = parse_deadline(lead.get("date_deadline"))
            if close is None:
                no_close_date += 1
            elif close < today:
                overdue_close += 1
            elif close <= close_cutoff:
                closing_soon += 1

        stalled.sort(key=lambda r: -r["idle_days"])
        stalled_pct = round(len(stalled) / total * 100, 1) if total else 0.0

        if total == 0:
            verdict = "at_risk"
        elif stalled_pct >= 50:
            verdict = "off_track"
        elif stalled_pct >= 25 or overdue_close > 0:
            verdict = "at_risk"
        else:
            verdict = "on_track"

        summary = {
            "open_opportunities": total,
            "expected_revenue": round(expected_total, 2),
            "weighted_revenue": round(weighted_total, 2),
            "stalled": len(stalled),
            "stalled_pct": stalled_pct,
            "overdue_close_date": overdue_close,
            "closing_soon": closing_soon,
            "no_close_date": no_close_date,
            "won_last_period": won,
            "lost_last_period": lost,
            "win_rate_pct": win_rate,
            "verdict": verdict,
        }
        if truncation:
            summary["truncated"] = True
            summary["total_matching"] = truncation["total_matching"]

        stages = sorted(by_stage.values(), key=lambda r: -r["expected_revenue"])
        reps = sorted(by_rep.values(), key=lambda r: -r["expected_revenue"])

        highlights = [
            f"{total} open opportunities worth {round(expected_total, 2)} "
            f"({round(weighted_total, 2)} weighted)"
        ]
        if win_rate is not None:
            highlights.append(f"win rate last {win_rate_days}d: {win_rate}%")
        if closing_soon:
            highlights.append(
                f"{closing_soon} deal(s) closing within {lookahead_days} days")

        risks: list[dict] = []
        if truncation:
            risks.append({
                "code": "truncated_data", "count": truncation["missing"],
                "message": (
                    f"Report covers only {truncation['fetched']} of "
                    f"{truncation['total_matching']} matching opportunities."
                ),
            })
        if total == 0:
            risks.append({"code": "empty_pipeline", "count": 0,
                          "message": "No open opportunities match the filter."})
        if stalled:
            risks.append({
                "code": "stalled_deals", "count": len(stalled),
                "message": (f"{len(stalled)} deal(s) with no stage change in "
                            f"{stalled_days}+ days"),
            })
        if overdue_close:
            risks.append({
                "code": "overdue_close_dates", "count": overdue_close,
                "message": f"{overdue_close} deal(s) past their expected close date",
            })

        return build_report(
            "pipeline_review", today,
            summary=summary,
            breakdown={"by_stage": stages, "by_salesperson": reps,
                       "stalled_deals": stalled[:top_n]},
            highlights=highlights, risks=risks,
            extra={"salesperson": salesperson, "team": team},
        )

    return safe(run)

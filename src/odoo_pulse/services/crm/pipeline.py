"""CRM pipeline health report service."""

from __future__ import annotations

from datetime import timedelta

from ...common.concurrency import gather_strict
from ...common.dates import parse_when, utc_bound
from ...common.paging import fetch_with_truncation
from ...common.reporting import build_report, distinct_companies
from ..report_context import build_report_context


def build_pipeline_review(
    client,
    *,
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
) -> dict:
    context = build_report_context(
        client, timezone_offset=timezone_offset, company=company
    )
    today = context.today
    company_id = context.company_id

    owner_filter: list = []
    if salesperson:
        owner_filter.append(("user_id.name", "ilike", salesperson))
    if team:
        owner_filter.append(("team_id.name", "ilike", team))
    if company_id:
        owner_filter.append(("company_id", "=", company_id))
    domain: list = [
        ("type", "=", "opportunity"),
        ("probability", "<", 100),
        *owner_filter,
    ]

    leads, truncation = fetch_with_truncation(
        client, "crm.lead", domain,
        fields=["id", "name", "stage_id", "user_id", "expected_revenue",
                "probability", "date_deadline", "date_last_stage_update",
                "company_id", "company_currency"],
        limit=200, order="expected_revenue desc",
    )

    # Win rate honours the same salesperson/team scope as the funnel, so a
    # filtered report never pairs a person's pipeline with a company-wide rate.
    since = utc_bound(today - timedelta(days=win_rate_days), timezone_offset)
    counts = gather_strict({
        "won": lambda: client.search_count("crm.lead", [
            ("type", "=", "opportunity"), ("probability", "=", 100),
            ("date_closed", ">=", since), *owner_filter]),
        "lost": lambda: client.search_count("crm.lead", [
            ("type", "=", "opportunity"), ("active", "=", False),
            ("probability", "=", 0), ("date_closed", ">=", since),
            *owner_filter]),
    })
    won, lost = counts["won"], counts["lost"]
    win_rate = round(won / (won + lost) * 100, 1) if (won + lost) else None

    stalled_cutoff = today - timedelta(days=stalled_days)
    close_cutoff = today + timedelta(days=lookahead_days)

    total = len(leads)
    expected_total = weighted_total = 0.0
    expected_by_cur: dict[str, float] = {}
    weighted_by_cur: dict[str, float] = {}
    stalled: list[dict] = []
    overdue_close = closing_soon = no_close_date = 0
    by_stage: dict[str, dict] = {}
    by_rep: dict[str, dict] = {}

    for lead in leads:
        revenue = lead.get("expected_revenue") or 0.0
        prob = lead.get("probability") or 0.0
        expected_total += revenue
        weighted_total += revenue * prob / 100.0

        cur = lead.get("company_currency")
        cur_name = cur[1] if cur else "(unknown)"
        expected_by_cur[cur_name] = (
            expected_by_cur.get(cur_name, 0.0) + revenue)
        weighted_by_cur[cur_name] = (
            weighted_by_cur.get(cur_name, 0.0) + revenue * prob / 100.0)

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

        moved = parse_when(lead.get("date_last_stage_update"), timezone_offset)
        if moved is not None and moved < stalled_cutoff:
            stalled.append({
                "name": lead["name"], "stage": stage, "salesperson": rep,
                "expected_revenue": revenue,
                "idle_days": (today - moved).days,
            })

        close = parse_when(lead.get("date_deadline"), timezone_offset)
        if close is None:
            no_close_date += 1
        elif close < today:
            overdue_close += 1
        elif close <= close_cutoff:
            closing_soon += 1

    stalled.sort(key=lambda r: -r["idle_days"])
    stalled_count = len(stalled)

    partial_fields: list[str] = []
    if truncation:
        # The fetched rows are only the top-N by expected revenue, so
        # every verdict input is recomputed over the FULL population:
        # one aggregate for the revenue sum, four counts for the buckets.
        total = truncation["total_matching"]
        agg = client.aggregate_records(
            "crm.lead", group_by=[],
            measures=[("expected_revenue", "sum")], domain=domain)
        agg_rows = agg.get("rows", [])
        if agg_rows:
            expected_total = agg_rows[0].get("expected_revenue:sum") or 0.0
        stalled_count = client.search_count("crm.lead", [
            *domain,
            ("date_last_stage_update", "<",
             utc_bound(stalled_cutoff, timezone_offset))])
        overdue_close = client.search_count("crm.lead", [
            *domain, ("date_deadline", "!=", False),
            ("date_deadline", "<", today.isoformat())])
        closing_soon = client.search_count("crm.lead", [
            *domain, ("date_deadline", ">=", today.isoformat()),
            ("date_deadline", "<=", close_cutoff.isoformat())])
        no_close_date = client.search_count("crm.lead", [
            *domain, ("date_deadline", "=", False)])
        # These need per-row math (revenue * probability, currency of
        # each row) and cannot be recomputed server-side over XML-RPC.
        partial_fields = ["weighted_revenue",
                          "expected_revenue_by_currency",
                          "weighted_revenue_by_currency"]

    stalled_pct = round(stalled_count / total * 100, 1) if total else 0.0

    if total == 0:
        verdict = "at_risk"
    elif stalled_pct >= stalled_pct_off_track:
        verdict = "off_track"
    elif stalled_pct >= stalled_pct_at_risk or overdue_close > 0:
        verdict = "at_risk"
    else:
        verdict = "on_track"

    summary = {
        "open_opportunities": total,
        "expected_revenue": round(expected_total, 2),
        "weighted_revenue": round(weighted_total, 2),
        "expected_revenue_by_currency": {
            k: round(v, 2) for k, v in expected_by_cur.items()},
        "weighted_revenue_by_currency": {
            k: round(v, 2) for k, v in weighted_by_cur.items()},
        "stalled": stalled_count,
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
        summary["partial_fields"] = partial_fields

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
                f"Summary totals and verdict cover all "
                f"{truncation['total_matching']} matching opportunities; "
                f"breakdowns and the stalled list cover only the top "
                f"{truncation['fetched']} by expected revenue."
            ),
        })
    if total == 0:
        risks.append({"code": "empty_pipeline", "count": 0,
                      "message": "No open opportunities match the filter."})
    if stalled_count:
        risks.append({
            "code": "stalled_deals", "count": stalled_count,
            "message": (f"{stalled_count} deal(s) with no stage change in "
                        f"{stalled_days}+ days"),
        })
    if overdue_close:
        risks.append({
            "code": "overdue_close_dates", "count": overdue_close,
            "message": f"{overdue_close} deal(s) past their expected close date",
        })

    companies = distinct_companies(leads)
    if len(companies) > 1:
        risks.append({
            "code": "mixed_companies", "count": len(companies),
            "message": (
                f"Revenue totals mix {len(companies)} companies "
                f"({', '.join(companies)}) and therefore their currencies; "
                "pass company= to scope."),
        })

    if len(expected_by_cur) > 1:
        names = ", ".join(sorted(expected_by_cur))
        risks.append({
            "code": "mixed_currencies", "count": len(expected_by_cur),
            "message": (
                f"Pipeline spans {len(expected_by_cur)} currencies "
                f"({names}); expected_revenue/weighted_revenue mix them — "
                "read the *_by_currency splits instead."),
        })

    return build_report(
        "pipeline_review", today,
        summary=summary,
        breakdown={"by_stage": stages, "by_salesperson": reps,
                   "stalled_deals": stalled[:top_n]},
        highlights=highlights, risks=risks,
        extra={"salesperson": salesperson, "team": team, "company": company,
               "thresholds": {"stalled_pct_at_risk": stalled_pct_at_risk,
                              "stalled_pct_off_track": stalled_pct_off_track}},
    )

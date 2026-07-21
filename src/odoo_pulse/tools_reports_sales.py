# odoo_pulse/tools_reports_sales.py
"""Sales report tools: CRM pipeline health and the revenue snapshot.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from datetime import timedelta

from .common.dates import parse_when, today_in_tz, utc_bound
from .common.paging import fetch_with_truncation
from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .workflow_helpers import (
    build_report,
    distinct_companies,
    gather_strict,
    resolve_company_id,
    trend_direction,
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

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)

        company_id = resolve_company_id(client, company)

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

    return safe(run)


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

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        cur_start = today - timedelta(days=period_days)
        prev_start = today - timedelta(days=2 * period_days)
        company_id = resolve_company_id(client, company)
        company_domain: list = (
            [("company_id", "=", company_id)] if company_id else [])

        cur_lo = utc_bound(cur_start, timezone_offset)
        cur_hi = utc_bound(today + timedelta(days=1), timezone_offset)
        prev_lo = utc_bound(prev_start, timezone_offset)

        base = [("state", "in", ["sale", "done"]), *company_domain]

        def period_totals(lo: str, hi: str):
            agg = client.aggregate_records(
                "sale.order", group_by=["currency_id"],
                measures=[("amount_total", "sum")],
                domain=[*base, ("date_order", ">=", lo),
                        ("date_order", "<", hi)],
                limit=200,
            )
            count, total, by_cur = 0, 0.0, {}
            for row in agg.get("rows", []):
                cur = row.get("currency_id")
                name = cur[1] if cur else "(unknown)"
                amt = row.get("amount_total:sum") or 0.0
                by_cur[name] = round(by_cur.get(name, 0.0) + amt, 2)
                total += amt
                count += row.get("__count") or 0
            return count, round(total, 2), by_cur

        def sale_order_aggregates():
            # cur/prev/cust all aggregate sale.order; kept ordered inside one
            # thunk so they never race each other (real Odoo or the fake's
            # per-model response queue).
            cur = period_totals(cur_lo, cur_hi)
            prev = period_totals(prev_lo, cur_lo)
            cust = client.aggregate_records(
                "sale.order", group_by=["partner_id"],
                measures=[("amount_total", "sum")],
                domain=[*base, ("date_order", ">=", cur_lo),
                        ("date_order", "<", cur_hi)],
                limit=top_n, order="amount_total:sum desc",
            )
            return cur, prev, cust

        def product_aggregate():
            return client.aggregate_records(
                "sale.order.line",
                group_by=["product_id"],
                measures=[("price_subtotal", "sum")],
                domain=[("order_id.state", "in", ["sale", "done"]),
                        ("order_id.date_order", ">=", cur_lo),
                        ("order_id.date_order", "<", cur_hi),
                        *([("order_id.company_id", "=", company_id)]
                          if company_id else [])],
                limit=top_n,
                order="price_subtotal:sum desc",
            )

        def stale_quote_count():
            return client.search_count("sale.order", [
                ("state", "in", ["draft", "sent"]),
                ("create_date", "<",
                 utc_bound(today - timedelta(days=stale_quote_days),
                           timezone_offset)),
                *company_domain,
            ])

        trend_start = today - timedelta(days=7 * trend_weeks)

        def trend_fetch():
            return fetch_with_truncation(
                client, "sale.order",
                [("state", "in", ["sale", "done"]),
                 ("date_order", ">=", utc_bound(trend_start, timezone_offset)),
                 ("date_order", "<", cur_hi),
                 *company_domain],
                fields=["id", "amount_total", "date_order"],
                limit=200,
            )

        thunks = {"sales": sale_order_aggregates, "products": product_aggregate,
                  "quotes": stale_quote_count}
        if trend_weeks > 0:
            thunks["trend"] = trend_fetch
        fetched = gather_strict(thunks)

        (cur_count, cur_total, by_currency), (prev_count, prev_total, _), \
            cust_agg = fetched["sales"]

        delta_pct = (round((cur_total - prev_total) / prev_total * 100, 1)
                     if prev_total else None)

        top_customers = [
            {"customer": r["partner_id"][1] if r.get("partner_id") else "(unknown)",
             "orders": r.get("__count") or 0,
             "revenue": round(r.get("amount_total:sum") or 0.0, 2)}
            for r in cust_agg.get("rows", [])
        ]

        top_products = [
            {"product": row["product_id"][1] if row.get("product_id") else "(none)",
             "revenue": row.get("price_subtotal:sum") or 0.0}
            for row in fetched["products"].get("rows", [])
        ]

        stale_quotes = fetched["quotes"]

        trend = None
        weekly: list[dict] = []
        trend_trunc = None
        if trend_weeks > 0:
            trend_rows, trend_trunc = fetched["trend"]
            buckets = [0.0] * trend_weeks
            for o in trend_rows:
                day = parse_when(o.get("date_order"), timezone_offset)
                if day is None:
                    continue
                idx = min((day - trend_start).days // 7, trend_weeks - 1)
                buckets[idx] += o.get("amount_total") or 0.0
            weekly = [
                {"week_start": (trend_start + timedelta(days=7 * i)).isoformat(),
                 "revenue": round(v, 2)}
                for i, v in enumerate(buckets)
            ]
            if trend_trunc:
                trend = None
            else:
                trend = trend_direction(
                    [w["revenue"] for w in weekly], threshold_pct=growth_threshold_pct)

        if delta_pct is None:
            verdict = "steady"
        elif delta_pct >= growth_threshold_pct:
            verdict = "growing"
        elif delta_pct <= -growth_threshold_pct:
            verdict = "declining"
        else:
            verdict = "steady"

        summary = {
            "period_days": period_days,
            "orders": cur_count,
            "revenue": round(cur_total, 2),
            "prev_orders": prev_count,
            "prev_revenue": round(prev_total, 2),
            "delta_pct": delta_pct,
            "stale_quotations": stale_quotes,
            "verdict": verdict,
            "trend": trend,
        }
        if len(by_currency) == 1:
            summary["currency"] = next(iter(by_currency))
        elif len(by_currency) > 1:
            summary["by_currency"] = by_currency

        highlights = [
            f"revenue {round(cur_total, 2)} over the last {period_days}d "
            f"vs {round(prev_total, 2)} the {period_days}d before"
        ]
        if top_customers:
            highlights.append(
                f"top customer: {top_customers[0]['customer']} "
                f"({top_customers[0]['revenue']})")
        if trend == "declining" and verdict != "declining":
            highlights.append(
                f"note: {trend_weeks}-week revenue trend is declining despite "
                "the current period holding up")

        risks: list[dict] = []
        if trend_trunc:
            risks.append({
                "code": "truncated_trend", "count": trend_trunc["missing"],
                "message": (
                    f"Trend series covers only {trend_trunc['fetched']} of "
                    f"{trend_trunc['total_matching']} orders in the window."),
            })
        if verdict == "declining":
            risks.append({
                "code": "revenue_drop", "count": cur_count,
                "message": f"Revenue down {abs(delta_pct)}% vs the previous period",
            })
        if stale_quotes:
            risks.append({
                "code": "stale_quotations", "count": stale_quotes,
                "message": (f"{stale_quotes} quotation(s) older than "
                            f"{stale_quote_days} days still not confirmed"),
            })
        if len(by_currency) > 1:
            risks.append({
                "code": "mixed_currencies", "count": len(by_currency),
                "message": (
                    "Revenue sums mix currencies "
                    f"({', '.join(sorted(by_currency))}); the headline totals "
                    "are raw sums — read by_currency instead."),
            })

        return build_report(
            "sales_snapshot", today,
            summary=summary,
            breakdown={"top_customers": top_customers,
                       "top_products": top_products,
                       "weekly_revenue": weekly},
            highlights=highlights, risks=risks,
            extra={"period_days": period_days, "company": company,
                   "thresholds": {"growth_threshold_pct": growth_threshold_pct}},
        )

    return safe(run)

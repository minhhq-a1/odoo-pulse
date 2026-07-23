"""Sales snapshot report service."""

from __future__ import annotations

from datetime import timedelta

from ...common.concurrency import gather_strict
from ...common.dates import parse_when, utc_bound
from ...common.paging import fetch_with_truncation
from ...common.reporting import build_report, trend_direction
from ..report_context import build_report_context
from .metrics import confirmed_sales


def build_sales_snapshot(
    client,
    *,
    period_days: int = 7,
    stale_quote_days: int = 7,
    top_n: int = 5,
    timezone_offset: int = 7,
    growth_threshold_pct: float = 10.0,
    company: str | int | None = None,
    trend_weeks: int = 8,
) -> dict:
    context = build_report_context(
        client, timezone_offset=timezone_offset, company=company
    )
    today = context.today
    cur_start = today - timedelta(days=period_days)
    prev_start = today - timedelta(days=2 * period_days)
    company_domain = list(context.company_domain)

    cur_lo = utc_bound(cur_start, timezone_offset)
    cur_hi = utc_bound(today + timedelta(days=1), timezone_offset)
    prev_lo = utc_bound(prev_start, timezone_offset)

    base = [("state", "in", ["sale", "done"]), *company_domain]

    def period_totals(lo: str, hi: str):
        metric = confirmed_sales(
            context,
            date_from=lo,
            date_to_exclusive=hi,
            group_limit=200,
        )
        return (
            metric["orders"],
            metric["revenue"],
            metric.get("by_currency")
            or ({metric["currency"]: metric["revenue"]}
                if metric.get("currency") else {}),
        )

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
                    *list(context.company_filter("order_id.company_id"))],
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

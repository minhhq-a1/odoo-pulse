# odoo_pulse/tools_reports.py
"""Cross-department report tools: one business question answered per call.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from datetime import timedelta

from .odoo_client import OdooError
from .runtime import get_client, mcp, safe
from .workflow_helpers import (
    build_report,
    distinct_companies,
    fetch_with_truncation,
    parse_deadline,
    resolve_company_id,
    today_in_tz,
    totals_by_currency,
    trend_direction,
    utc_bound,
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
        domain: list = [("type", "=", "opportunity"), *owner_filter]

        leads, truncation = fetch_with_truncation(
            client, "crm.lead", domain,
            fields=["id", "name", "stage_id", "user_id", "expected_revenue",
                    "probability", "date_deadline", "date_last_stage_update",
                    "company_id"],
            limit=200, order="expected_revenue desc",
        )

        # Win rate honours the same salesperson/team scope as the funnel, so a
        # filtered report never pairs a person's pipeline with a company-wide rate.
        since = (today - timedelta(days=win_rate_days)).isoformat()
        won = client.search_count("crm.lead", [
            ("type", "=", "opportunity"), ("probability", "=", 100),
            ("date_closed", ">=", since), *owner_filter])
        lost = client.search_count("crm.lead", [
            ("type", "=", "opportunity"), ("active", "=", False),
            ("probability", "=", 0), ("date_closed", ">=", since), *owner_filter])
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

        companies = distinct_companies(leads)
        if len(companies) > 1:
            risks.append({
                "code": "mixed_companies", "count": len(companies),
                "message": (
                    f"Revenue totals mix {len(companies)} companies "
                    f"({', '.join(companies)}) and therefore their currencies; "
                    "pass company= to scope."),
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

        orders, truncation = fetch_with_truncation(
            client, "sale.order",
            [("state", "in", ["sale", "done"]),
             ("date_order", ">=", prev_start.isoformat()), *company_domain],
            fields=["id", "name", "amount_total", "partner_id", "date_order",
                    "currency_id"],
            limit=200, order="date_order desc",
        )

        cur_total = prev_total = 0.0
        cur_count = prev_count = 0
        customers: dict[str, dict] = {}
        cur_rows: list[dict] = []
        for o in orders:
            day = parse_deadline(o.get("date_order"))
            amount = o.get("amount_total") or 0.0
            if day is not None and day >= cur_start:
                cur_count += 1
                cur_rows.append(o)
                cur_total += amount
                partner = o["partner_id"][1] if o.get("partner_id") else "(unknown)"
                rec = customers.setdefault(
                    partner, {"customer": partner, "orders": 0, "revenue": 0.0})
                rec["orders"] += 1
                rec["revenue"] += amount
            else:
                prev_count += 1
                prev_total += amount

        delta_pct = (round((cur_total - prev_total) / prev_total * 100, 1)
                     if prev_total else None)

        agg = client.aggregate_records(
            "sale.order.line",
            group_by=["product_id"],
            measures=[("price_subtotal", "sum")],
            domain=[("order_id.state", "in", ["sale", "done"]),
                    ("order_id.date_order", ">=", cur_start.isoformat()),
                    *([("order_id.company_id", "=", company_id)]
                      if company_id else [])],
            limit=top_n,
            order="price_subtotal:sum desc",
        )
        top_products = [
            {"product": row["product_id"][1] if row.get("product_id") else "(none)",
             "revenue": row.get("price_subtotal:sum") or 0.0}
            for row in agg.get("rows", [])
        ]

        stale_quotes = client.search_count("sale.order", [
            ("state", "in", ["draft", "sent"]),
            ("create_date", "<",
             (today - timedelta(days=stale_quote_days)).isoformat()),
            *company_domain,
        ])

        trend = None
        weekly: list[dict] = []
        trend_trunc = None
        if trend_weeks > 0:
            trend_start = today - timedelta(days=7 * trend_weeks)
            trend_rows, trend_trunc = fetch_with_truncation(
                client, "sale.order",
                [("state", "in", ["sale", "done"]),
                 ("date_order", ">=", trend_start.isoformat()),
                 *company_domain],
                fields=["id", "amount_total", "date_order"],
                limit=200,
            )
            buckets = [0.0] * trend_weeks
            for o in trend_rows:
                day = parse_deadline(o.get("date_order"))
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

        top_customers = sorted(
            customers.values(), key=lambda r: -r["revenue"])[:top_n]

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
        by_currency = totals_by_currency(cur_rows, "amount_total")
        if len(by_currency) == 1:
            summary["currency"] = next(iter(by_currency))
        elif len(by_currency) > 1:
            summary["by_currency"] = by_currency
        if truncation:
            summary["truncated"] = True
            summary["total_matching"] = truncation["total_matching"]

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
        if truncation:
            risks.append({
                "code": "truncated_data", "count": truncation["missing"],
                "message": (
                    f"Report covers only {truncation['fetched']} of "
                    f"{truncation['total_matching']} matching orders."
                ),
            })
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

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)

        company_id = resolve_company_id(client, company)
        company_domain: list = (
            [("company_id", "=", company_id)] if company_id else [])

        invoices, truncation = fetch_with_truncation(
            client, "account.move",
            [("move_type", "in", ["out_invoice", "in_invoice"]),
             ("state", "=", "posted"),
             ("payment_state", "in", ["not_paid", "partial"]),
             *company_domain],
            fields=["id", "name", "partner_id", "amount_residual",
                    "invoice_date_due", "move_type", "currency_id"],
            limit=200, order="invoice_date_due",
        )

        buckets = ("not_due", "1-30", "31-60", "61-90", "90+")
        aging = {"receivable": dict.fromkeys(buckets, 0.0),
                 "payable": dict.fromkeys(buckets, 0.0)}
        overdue_customers: dict[str, float] = {}
        ar_rows: list[dict] = []
        ar_total = ar_overdue = ap_total = 0.0
        ar_count = ap_count = ninety_plus_count = 0

        for inv in invoices:
            residual = inv.get("amount_residual") or 0.0
            side = "receivable" if inv["move_type"] == "out_invoice" else "payable"
            due = parse_deadline(inv.get("invoice_date_due"))
            days = (today - due).days if due else 0
            if days <= 0:
                bucket = "not_due"
            elif days <= 30:
                bucket = "1-30"
            elif days <= 60:
                bucket = "31-60"
            elif days <= 90:
                bucket = "61-90"
            else:
                bucket = "90+"
            aging[side][bucket] += residual

            if side == "receivable":
                ar_count += 1
                ar_total += residual
                ar_rows.append(inv)
                if bucket == "90+":
                    ninety_plus_count += 1
                if days > 0:
                    ar_overdue += residual
                    partner = (inv["partner_id"][1]
                               if inv.get("partner_id") else "(unknown)")
                    overdue_customers[partner] = (
                        overdue_customers.get(partner, 0.0) + residual)
            else:
                ap_count += 1
                ap_total += residual

        for side in aging:
            aging[side] = {b: round(v, 2) for b, v in aging[side].items()}

        pct_overdue = round(ar_overdue / ar_total * 100, 1) if ar_total else 0.0
        ninety_plus = aging["receivable"]["90+"]

        if pct_overdue >= overdue_pct_off_track:
            verdict = "off_track"
        elif pct_overdue >= overdue_pct_at_risk or ninety_plus > 0:
            verdict = "at_risk"
        else:
            verdict = "on_track"

        top_debtors = sorted(
            ({"customer": k, "overdue_amount": round(v, 2)}
             for k, v in overdue_customers.items()),
            key=lambda r: -r["overdue_amount"],
        )[:top_n]

        summary = {
            "receivable_open": ar_count,
            "receivable_total": round(ar_total, 2),
            "receivable_overdue": round(ar_overdue, 2),
            "pct_overdue": pct_overdue,
            "payable_open": ap_count,
            "payable_total": round(ap_total, 2),
            "verdict": verdict,
        }
        if truncation:
            summary["truncated"] = True
            summary["total_matching"] = truncation["total_matching"]

        by_currency = totals_by_currency(ar_rows, "amount_residual")
        if len(by_currency) == 1:
            summary["currency"] = next(iter(by_currency))
        elif len(by_currency) > 1:
            summary["by_currency"] = by_currency

        highlights = [
            f"{round(ar_total, 2)} receivable across {ar_count} invoice(s), "
            f"{pct_overdue}% overdue"
        ]
        if top_debtors:
            highlights.append(
                f"largest overdue: {top_debtors[0]['customer']} "
                f"({top_debtors[0]['overdue_amount']})")

        risks: list[dict] = []
        if truncation:
            risks.append({
                "code": "truncated_data", "count": truncation["missing"],
                "message": (
                    f"Report covers only {truncation['fetched']} of "
                    f"{truncation['total_matching']} matching invoices."
                ),
            })
        if ar_overdue > 0:
            risks.append({
                "code": "overdue_receivables", "count": len(overdue_customers),
                "message": (f"{round(ar_overdue, 2)} overdue across "
                            f"{len(overdue_customers)} customer(s)"),
            })
        if ninety_plus > 0:
            risks.append({
                "code": "aged_over_90", "count": ninety_plus_count,
                "message": (f"{ninety_plus_count} receivable(s) totaling "
                            f"{ninety_plus} are 90+ days overdue"),
            })
        if len(by_currency) > 1:
            risks.append({
                "code": "mixed_currencies", "count": len(by_currency),
                "message": (
                    "Receivable totals and aging buckets mix currencies "
                    f"({', '.join(sorted(by_currency))}); read by_currency "
                    "or pass company= to scope."),
            })

        return build_report(
            "receivables_health", today,
            summary=summary,
            breakdown={"aging": aging, "top_overdue_customers": top_debtors},
            highlights=highlights, risks=risks,
            extra={"company": company,
                   "thresholds": {"overdue_pct_at_risk": overdue_pct_at_risk,
                                  "overdue_pct_off_track": overdue_pct_off_track}},
        )

    return safe(run)


@mcp.tool()
def inventory_risk(
    dead_stock_days: int = 90,
    top_n: int = 10,
    timezone_offset: int = 7,
) -> str:
    """Report stock at risk — shortages and dead stock — in one call.

    Shortages are storable products with negative forecasted quantity
    (demand exceeds supply). Dead stock is on-hand product with no done
    stock move in dead_stock_days, valued at standard_price. The dead-stock
    check is a bounded heuristic: when the recently-moved product list hits
    the 200-group cap, a risk flags that the list may over-count.

    Args:
        dead_stock_days: No-movement window for dead stock (default 90).
        top_n: Rows listed per breakdown section (default 10).
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)

        short_rows, short_trunc = fetch_with_truncation(
            client, "product.product",
            [("type", "=", "consu"), ("is_storable", "=", True),
             ("virtual_available", "<", 0)],
            fields=["id", "name", "default_code", "qty_available",
                    "virtual_available"],
            limit=200,
        )
        shortages = [
            {"product": p["name"], "code": p.get("default_code") or None,
             "on_hand": p.get("qty_available") or 0.0,
             "forecasted": p.get("virtual_available") or 0.0}
            for p in short_rows
        ]
        shortages.sort(key=lambda r: r["forecasted"])

        since = (today - timedelta(days=dead_stock_days)).isoformat()
        agg = client.aggregate_records(
            "stock.move", group_by=["product_id"], measures=[],
            domain=[("state", "=", "done"), ("date", ">=", since)],
            limit=200,
        )
        moved_rows = agg.get("rows", [])
        moved_ids = {row["product_id"][0] for row in moved_rows
                     if row.get("product_id")}
        moved_capped = len(moved_rows) >= min(200, client.config.max_records)

        stocked, stocked_trunc = fetch_with_truncation(
            client, "product.product",
            [("type", "=", "consu"), ("is_storable", "=", True),
             ("qty_available", ">", 0)],
            fields=["id", "name", "default_code", "qty_available",
                    "standard_price"],
            limit=200,
        )
        dead: list[dict] = []
        dead_value = 0.0
        for p in stocked:
            if p["id"] in moved_ids:
                continue
            value = (p.get("standard_price") or 0.0) * (p.get("qty_available") or 0.0)
            dead_value += value
            dead.append({"product": p["name"], "code": p.get("default_code") or None,
                         "on_hand": p.get("qty_available") or 0.0,
                         "value": round(value, 2)})
        dead.sort(key=lambda r: -r["value"])

        if shortages:
            verdict = "action_needed"
        elif dead:
            verdict = "watch"
        else:
            verdict = "healthy"

        summary = {
            "shortages": len(shortages),
            "dead_stock_items": len(dead),
            "dead_stock_value": round(dead_value, 2),
            "verdict": verdict,
        }
        if short_trunc or stocked_trunc:
            summary["truncated"] = True

        highlights = []
        if shortages:
            worst = shortages[0]
            highlights.append(
                f"{len(shortages)} product(s) forecasted negative; worst: "
                f"{worst['product']} ({worst['forecasted']})")
        if dead:
            highlights.append(
                f"{len(dead)} product(s) unmoved for {dead_stock_days}+ days, "
                f"value {round(dead_value, 2)}")
        if not highlights:
            highlights.append("no shortages or dead stock detected")

        risks: list[dict] = []
        for trunc in (short_trunc, stocked_trunc):
            if trunc:
                risks.append({
                    "code": "truncated_data", "count": trunc["missing"],
                    "message": (
                        f"Report covers only {trunc['fetched']} of "
                        f"{trunc['total_matching']} matching products."
                    ),
                })
        if shortages:
            risks.append({
                "code": "negative_forecast", "count": len(shortages),
                "message": (f"{len(shortages)} product(s) promised beyond "
                            "available supply"),
            })
        if dead:
            risks.append({
                "code": "dead_stock", "count": len(dead),
                "message": (f"{round(dead_value, 2)} tied up in stock unmoved "
                            f"for {dead_stock_days}+ days"),
            })
        if moved_capped:
            risks.append({
                "code": "dead_stock_heuristic", "count": len(moved_rows),
                "message": ("Recently-moved product list hit the 200-group "
                            "cap; dead stock may be over-counted."),
            })

        return build_report(
            "inventory_risk", today,
            summary=summary,
            breakdown={"shortages": shortages[:top_n], "dead_stock": dead[:top_n]},
            highlights=highlights, risks=risks,
            extra={"dead_stock_days": dead_stock_days},
        )

    return safe(run)


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

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        horizon = today + timedelta(days=days)

        approved, approved_trunc = fetch_with_truncation(
            client, "hr.leave",
            [("state", "=", "validate"),
             ("date_from", "<=", horizon.isoformat()),
             ("date_to", ">=", today.isoformat())],
            fields=["id", "employee_id", "department_id", "date_from",
                    "date_to", "holiday_status_id", "number_of_days"],
            limit=200, order="date_from",
        )
        pending, pending_trunc = fetch_with_truncation(
            client, "hr.leave",
            [("state", "in", ["confirm", "validate1"])],
            fields=["id", "employee_id", "department_id", "date_from", "date_to"],
            limit=200, order="date_from",
        )

        agg = client.aggregate_records(
            "hr.employee", group_by=["department_id"], measures=[],
            domain=[], limit=200,
        )
        headcount: dict[str, int] = {}
        for row in agg.get("rows", []):
            dept = row["department_id"][1] if row.get("department_id") else "(none)"
            headcount[dept] = (row.get("__count")
                               or row.get("department_id_count") or 0)

        off_today_ids: set[int] = set()
        dept_off: dict[str, set[int]] = {}
        upcoming: list[dict] = []
        for leave in approved:
            emp = leave.get("employee_id") or [0, "(unknown)"]
            dept = (leave["department_id"][1]
                    if leave.get("department_id") else "(none)")
            start = parse_deadline(leave.get("date_from"))
            end = parse_deadline(leave.get("date_to"))
            if start and end and start <= today <= end:
                off_today_ids.add(emp[0])
            dept_off.setdefault(dept, set()).add(emp[0])
            upcoming.append({
                "employee": emp[1], "department": dept,
                "type": (leave["holiday_status_id"][1]
                         if leave.get("holiday_status_id") else None),
                "from": leave.get("date_from"), "to": leave.get("date_to"),
                "days": leave.get("number_of_days") or 0.0,
            })

        by_department = []
        thin = 0
        for dept, emp_ids in sorted(dept_off.items()):
            count = headcount.get(dept, 0)
            risk = bool(count) and (len(emp_ids) / count) >= coverage_threshold
            if risk:
                thin += 1
            by_department.append({
                "department": dept, "off_in_window": len(emp_ids),
                "headcount": count, "coverage_risk": risk,
            })

        off_in_window = len({e for ids in dept_off.values() for e in ids})
        verdict = "action_needed" if (pending or thin) else "clear"

        summary = {
            "off_today": len(off_today_ids),
            "off_in_window": off_in_window,
            "pending_approvals": len(pending),
            "departments_at_risk": thin,
            "verdict": verdict,
        }
        for trunc in (approved_trunc, pending_trunc):
            if trunc:
                summary["truncated"] = True

        highlights = [f"{len(off_today_ids)} off today, "
                      f"{off_in_window} off within {days} days"]
        if pending:
            highlights.append(f"{len(pending)} request(s) awaiting approval")

        risks: list[dict] = []
        for trunc in (approved_trunc, pending_trunc):
            if trunc:
                risks.append({
                    "code": "truncated_data", "count": trunc["missing"],
                    "message": (
                        f"Report covers only {trunc['fetched']} of "
                        f"{trunc['total_matching']} matching leave records."
                    ),
                })
        if pending:
            risks.append({
                "code": "pending_approvals", "count": len(pending),
                "message": f"{len(pending)} leave request(s) awaiting approval",
            })
        if thin:
            risks.append({
                "code": "thin_coverage", "count": thin,
                "message": (f"{thin} department(s) with >= "
                            f"{int(coverage_threshold * 100)}% of staff off "
                            "in the window"),
            })

        return build_report(
            "absence_overview", today,
            summary=summary,
            breakdown={"by_department": by_department, "leaves": upcoming},
            highlights=highlights, risks=risks,
            extra={"days": days},
        )

    return safe(run)


@mcp.tool()
def business_pulse(
    timezone_offset: int = 7,
    company: str | int | None = None,
) -> str:
    """One-call company briefing: sales, leads, receivables, tasks, absences.

    The morning-standup view of the whole company: yesterday's confirmed
    revenue and new leads, overdue customer invoices, tasks past deadline,
    and who is off today. Sections are independent — if an app is not
    installed, its section reports available=false and the rest still
    renders.

    Args:
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
        company: Optional company name (ilike) or id; scopes every section.
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        yesterday = today - timedelta(days=1)
        y_lo = utc_bound(yesterday, timezone_offset)
        y_hi = utc_bound(today, timezone_offset)
        t_hi = utc_bound(today + timedelta(days=1), timezone_offset)
        company_id = resolve_company_id(client, company)
        company_domain: list = (
            [("company_id", "=", company_id)] if company_id else [])
        sections: dict[str, dict] = {}

        def section(name, fn):
            try:
                sections[name] = {"available": True, **fn()}
            except OdooError as exc:
                sections[name] = {"available": False, "reason": str(exc)}

        def sales_yesterday() -> dict:
            rows = client.search_read(
                "sale.order",
                domain=[("state", "in", ["sale", "done"]),
                        ("date_order", ">=", y_lo),
                        ("date_order", "<", y_hi),
                        *company_domain],
                fields=["id", "amount_total"], limit=200,
            )
            return {"orders": len(rows),
                    "revenue": round(sum(r.get("amount_total") or 0.0
                                         for r in rows), 2)}

        def new_leads() -> dict:
            n = client.search_count("crm.lead", [
                ("create_date", ">=", y_lo),
                ("create_date", "<", y_hi),
                *company_domain])
            return {"new_leads": n}

        def overdue_invoices() -> dict:
            rows = client.search_read(
                "account.move",
                domain=[("move_type", "=", "out_invoice"),
                        ("state", "=", "posted"),
                        ("payment_state", "in", ["not_paid", "partial"]),
                        ("invoice_date_due", "<", today.isoformat()),
                        *company_domain],
                fields=["id", "amount_residual"], limit=200,
            )
            return {"overdue_invoices": len(rows),
                    "overdue_amount": round(sum(r.get("amount_residual") or 0.0
                                                for r in rows), 2)}

        def overdue_tasks() -> dict:
            n = client.search_count("project.task", [
                ("date_deadline", "<", today.isoformat()),
                ("stage_id.fold", "=", False),
                *company_domain])
            return {"overdue_tasks": n}

        def people_off() -> dict:
            n = client.search_count("hr.leave", [
                ("state", "=", "validate"),
                ("date_from", "<", t_hi),
                ("date_to", ">=", y_hi),
                *company_domain])
            return {"off_today": n}

        section("sales", sales_yesterday)
        section("crm", new_leads)
        section("receivables", overdue_invoices)
        section("projects", overdue_tasks)
        section("hr", people_off)

        attention = (
            sections["receivables"].get("overdue_invoices", 0) > 0
            or sections["projects"].get("overdue_tasks", 0) > 0
        )
        verdict = "attention" if attention else "all_clear"
        unavailable = [k for k, v in sections.items() if not v["available"]]

        n_companies = 0
        if company_id is None:
            try:
                n_companies = client.search_count("res.company", [])
            except OdooError:
                n_companies = 0

        summary = {
            "verdict": verdict,
            "sections_available": len(sections) - len(unavailable),
            "sections_unavailable": unavailable,
        }

        highlights = []
        if sections["sales"]["available"]:
            highlights.append(
                f"yesterday: {sections['sales']['orders']} order(s), "
                f"revenue {sections['sales']['revenue']}")
        if sections["crm"]["available"]:
            highlights.append(f"{sections['crm']['new_leads']} new lead(s) yesterday")
        if sections["hr"]["available"] and sections["hr"]["off_today"]:
            highlights.append(f"{sections['hr']['off_today']} people off today")

        risks: list[dict] = []
        if sections["receivables"].get("overdue_invoices"):
            risks.append({
                "code": "overdue_invoices",
                "count": sections["receivables"]["overdue_invoices"],
                "message": (
                    f"{sections['receivables']['overdue_invoices']} customer "
                    f"invoice(s) overdue, "
                    f"{sections['receivables']['overdue_amount']} outstanding"),
            })
        if sections["projects"].get("overdue_tasks"):
            risks.append({
                "code": "overdue_tasks",
                "count": sections["projects"]["overdue_tasks"],
                "message": (f"{sections['projects']['overdue_tasks']} task(s) "
                            "past deadline"),
            })
        if n_companies > 1:
            risks.append({
                "code": "multi_company_totals", "count": n_companies,
                "message": (
                    f"Instance has {n_companies} companies; section totals mix "
                    "them (and their currencies). Pass company= to scope."),
            })
        for name in unavailable:
            risks.append({
                "code": "section_unavailable", "count": 1,
                "message": f"{name}: {sections[name]['reason']}",
            })

        return build_report(
            "business_pulse", today,
            summary=summary,
            breakdown={"sections": sections},
            highlights=highlights, risks=risks,
            extra={"company": company},
        )

    return safe(run)

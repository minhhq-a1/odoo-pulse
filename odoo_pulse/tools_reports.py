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


@mcp.tool()
def sales_snapshot(
    period_days: int = 7,
    stale_quote_days: int = 7,
    top_n: int = 5,
    timezone_offset: int = 7,
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
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        cur_start = today - timedelta(days=period_days)
        prev_start = today - timedelta(days=2 * period_days)

        orders, truncation = fetch_with_truncation(
            client, "sale.order",
            [("state", "in", ["sale", "done"]),
             ("date_order", ">=", prev_start.isoformat())],
            fields=["id", "name", "amount_total", "partner_id", "date_order"],
            limit=200, order="date_order desc",
        )

        cur_total = prev_total = 0.0
        cur_count = prev_count = 0
        customers: dict[str, dict] = {}
        for o in orders:
            day = parse_deadline(o.get("date_order"))
            amount = o.get("amount_total") or 0.0
            if day is not None and day >= cur_start:
                cur_count += 1
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
            measures=["price_subtotal:sum"],
            domain=[("order_id.state", "in", ["sale", "done"]),
                    ("order_id.date_order", ">=", cur_start.isoformat())],
            limit=top_n,
        )
        top_products = [
            {"product": row["product_id"][1] if row.get("product_id") else "(none)",
             "revenue": row.get("price_subtotal") or 0.0}
            for row in agg.get("rows", [])
        ]

        stale_quotes = client.search_count("sale.order", [
            ("state", "in", ["draft", "sent"]),
            ("create_date", "<",
             (today - timedelta(days=stale_quote_days)).isoformat()),
        ])

        if delta_pct is None:
            verdict = "steady"
        elif delta_pct >= 10:
            verdict = "growing"
        elif delta_pct <= -10:
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
        }
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

        risks: list[dict] = []
        if truncation:
            risks.append({
                "code": "truncated_data", "count": truncation["missing"],
                "message": (
                    f"Report covers only {truncation['fetched']} of "
                    f"{truncation['total_matching']} matching orders."
                ),
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

        return build_report(
            "sales_snapshot", today,
            summary=summary,
            breakdown={"top_customers": top_customers,
                       "top_products": top_products},
            highlights=highlights, risks=risks,
            extra={"period_days": period_days},
        )

    return safe(run)


@mcp.tool()
def receivables_health(top_n: int = 5, timezone_offset: int = 7) -> str:
    """Report AR/AP aging and who owes what, in one call.

    Composes open posted invoices and vendor bills into standard aging
    buckets (not_due / 1-30 / 31-60 / 61-90 / 90+), the share of
    receivables overdue, the top overdue customers, and a verdict.

    Args:
        top_n: Rows in the top-overdue-customers list (default 5).
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)

        invoices, truncation = fetch_with_truncation(
            client, "account.move",
            [("move_type", "in", ["out_invoice", "in_invoice"]),
             ("state", "=", "posted"),
             ("payment_state", "in", ["not_paid", "partial"])],
            fields=["id", "name", "partner_id", "amount_residual",
                    "invoice_date_due", "move_type"],
            limit=200, order="invoice_date_due",
        )

        buckets = ("not_due", "1-30", "31-60", "61-90", "90+")
        aging = {"receivable": dict.fromkeys(buckets, 0.0),
                 "payable": dict.fromkeys(buckets, 0.0)}
        overdue_customers: dict[str, float] = {}
        ar_total = ar_overdue = ap_total = 0.0
        ar_count = ap_count = 0

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

        if pct_overdue >= 50:
            verdict = "off_track"
        elif pct_overdue >= 25 or ninety_plus > 0:
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
                "code": "aged_over_90", "count": 1,
                "message": f"{ninety_plus} receivable is 90+ days overdue",
            })

        return build_report(
            "receivables_health", today,
            summary=summary,
            breakdown={"aging": aging, "top_overdue_customers": top_debtors},
            highlights=highlights, risks=risks,
        )

    return safe(run)

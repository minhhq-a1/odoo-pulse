# odoo_pulse/tools_reports_ops.py
"""Operations report tools: purchasing and manufacturing health.

Same composition style as tools_reports: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from datetime import timedelta

from .runtime import get_client, mcp, safe
from .workflow_helpers import (
    build_report,
    fetch_with_truncation,
    gather_strict,
    parse_when,
    resolve_company_id,
    today_in_tz,
    totals_by_currency,
    utc_bound,
)


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

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        company_id = resolve_company_id(client, company)
        company_domain: list = (
            [("company_id", "=", company_id)] if company_id else [])

        fetched = gather_strict({
            "orders": lambda: fetch_with_truncation(
                client, "purchase.order",
                [("state", "=", "purchase"), *company_domain],
                fields=["id", "name", "partner_id", "date_planned",
                        "amount_total", "state", "currency_id"],
                limit=200, order="date_planned",
            ),
            "stale_rfqs": lambda: client.search_count("purchase.order", [
                ("state", "in", ["draft", "sent"]),
                ("create_date", "<",
                 utc_bound(today - timedelta(days=rfq_stale_days),
                           timezone_offset)),
                *company_domain,
            ]),
        })
        orders, truncation = fetched["orders"]
        stale_rfqs = fetched["stale_rfqs"]

        late_cutoff = today - timedelta(days=late_grace_days)
        open_value = 0.0
        late: list[dict] = []
        vendors: dict[str, dict] = {}
        for po in orders:
            amount = po.get("amount_total") or 0.0
            open_value += amount
            vendor = po["partner_id"][1] if po.get("partner_id") else "(unknown)"
            vrec = vendors.setdefault(
                vendor, {"vendor": vendor, "orders": 0, "open_value": 0.0})
            vrec["orders"] += 1
            vrec["open_value"] += amount

            planned = parse_when(po.get("date_planned"), timezone_offset)
            if planned is not None and planned < late_cutoff:
                late.append({
                    "po": po["name"], "vendor": vendor,
                    "expected": po.get("date_planned"),
                    "days_late": (today - planned).days,
                    "amount": amount,
                })
        late.sort(key=lambda r: -r["days_late"])

        if late:
            verdict = "action_needed"
        elif stale_rfqs:
            verdict = "watch"
        else:
            verdict = "healthy"

        summary = {
            "open_pos": len(orders),
            "open_value": round(open_value, 2),
            "late_receipts": len(late),
            "stale_rfqs": stale_rfqs,
            "verdict": verdict,
        }
        by_currency = totals_by_currency(orders, "amount_total")
        if len(by_currency) == 1:
            summary["currency"] = next(iter(by_currency))
        elif len(by_currency) > 1:
            summary["by_currency"] = by_currency
        if truncation:
            summary["truncated"] = True
            summary["total_matching"] = truncation["total_matching"]

        top_vendors = sorted(
            ({**v, "open_value": round(v["open_value"], 2)}
             for v in vendors.values()),
            key=lambda r: -r["open_value"],
        )[:top_n]

        highlights = [
            f"{len(orders)} confirmed PO(s) worth {round(open_value, 2)} open"]
        if late:
            worst = late[0]
            highlights.append(
                f"most overdue receipt: {worst['po']} from {worst['vendor']} "
                f"({worst['days_late']} days late)")
        if stale_rfqs:
            highlights.append(
                f"{stale_rfqs} RFQ(s) older than {rfq_stale_days} days")

        risks: list[dict] = []
        if truncation:
            risks.append({
                "code": "truncated_data", "count": truncation["missing"],
                "message": (
                    f"Report covers only {truncation['fetched']} of "
                    f"{truncation['total_matching']} matching purchase orders."),
            })
        if late:
            risks.append({
                "code": "late_receipts", "count": len(late),
                "message": (f"{len(late)} PO(s) past their planned receipt "
                            "date — production/stock may be waiting on them"),
            })
        if stale_rfqs:
            risks.append({
                "code": "stale_rfqs", "count": stale_rfqs,
                "message": (f"{stale_rfqs} RFQ(s) sitting in draft/sent for "
                            f"{rfq_stale_days}+ days"),
            })
        if len(by_currency) > 1:
            risks.append({
                "code": "mixed_currencies", "count": len(by_currency),
                "message": (
                    "Open-value totals mix currencies "
                    f"({', '.join(sorted(by_currency))}); read by_currency."),
            })

        return build_report(
            "procurement_watch", today,
            summary=summary,
            breakdown={"late_receipts": late[:top_n], "top_vendors": top_vendors},
            highlights=highlights, risks=risks,
            extra={"company": company},
        )

    return safe(run)


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

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)
        company_id = resolve_company_id(client, company)
        company_domain: list = (
            [("company_id", "=", company_id)] if company_id else [])

        orders, truncation = fetch_with_truncation(
            client, "mrp.production",
            [("state", "in", ["confirmed", "progress", "to_close"]),
             *company_domain],
            fields=["id", "name", "product_id", "product_qty", "state",
                    "date_start", "date_finished"],
            limit=200, order="date_start",
        )

        by_state: dict[str, int] = {}
        behind: list[dict] = []
        stuck: list[dict] = []
        for mo in orders:
            state = mo.get("state") or "(unknown)"
            by_state[state] = by_state.get(state, 0) + 1
            product = mo["product_id"][1] if mo.get("product_id") else "(none)"
            start = parse_when(mo.get("date_start"), timezone_offset)
            if state == "confirmed" and start is not None and start < today:
                behind.append({
                    "mo": mo["name"], "product": product,
                    "qty": mo.get("product_qty") or 0.0,
                    "planned_start": mo.get("date_start"),
                    "days_behind": (today - start).days,
                })
            elif (state in ("progress", "to_close") and start is not None
                  and (today - start).days > stuck_days):
                stuck.append({
                    "mo": mo["name"], "product": product,
                    "qty": mo.get("product_qty") or 0.0,
                    "started": mo.get("date_start"),
                    "running_days": (today - start).days,
                })
        behind.sort(key=lambda r: -r["days_behind"])
        stuck.sort(key=lambda r: -r["running_days"])

        if behind:
            verdict = "action_needed"
        elif stuck:
            verdict = "watch"
        else:
            verdict = "healthy"

        summary = {
            "open_orders": len(orders),
            "behind_start": len(behind),
            "stuck_in_progress": len(stuck),
            "verdict": verdict,
        }
        if truncation:
            summary["truncated"] = True
            summary["total_matching"] = truncation["total_matching"]

        highlights = [f"{len(orders)} open manufacturing order(s)"]
        if behind:
            worst = behind[0]
            highlights.append(
                f"{worst['mo']} ({worst['product']}) is {worst['days_behind']} "
                "day(s) past its planned start")
        if stuck:
            worst = stuck[0]
            highlights.append(
                f"{worst['mo']} has been running {worst['running_days']} day(s)")
        if verdict == "healthy":
            highlights.append("no late starts or stuck orders detected")

        risks: list[dict] = []
        if truncation:
            risks.append({
                "code": "truncated_data", "count": truncation["missing"],
                "message": (
                    f"Report covers only {truncation['fetched']} of "
                    f"{truncation['total_matching']} matching orders."),
            })
        if behind:
            risks.append({
                "code": "behind_start", "count": len(behind),
                "message": (f"{len(behind)} order(s) past their planned start "
                            "and not yet in progress"),
            })
        if stuck:
            risks.append({
                "code": "stuck_in_progress", "count": len(stuck),
                "message": (f"{len(stuck)} order(s) in progress for more than "
                            f"{stuck_days} days"),
            })

        return build_report(
            "production_health", today,
            summary=summary,
            breakdown={"by_state": by_state, "behind_start": behind[:top_n],
                       "stuck_in_progress": stuck[:top_n]},
            highlights=highlights, risks=risks,
            extra={"stuck_days": stuck_days, "company": company},
        )

    return safe(run)

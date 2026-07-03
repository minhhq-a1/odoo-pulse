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
    parse_deadline,
    resolve_company_id,
    today_in_tz,
    totals_by_currency,
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

        orders, truncation = fetch_with_truncation(
            client, "purchase.order",
            [("state", "=", "purchase"), *company_domain],
            fields=["id", "name", "partner_id", "date_planned",
                    "amount_total", "state", "currency_id"],
            limit=200, order="date_planned",
        )

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

            planned = parse_deadline(po.get("date_planned"))
            if planned is not None and planned < late_cutoff:
                late.append({
                    "po": po["name"], "vendor": vendor,
                    "expected": po.get("date_planned"),
                    "days_late": (today - planned).days,
                    "amount": amount,
                })
        late.sort(key=lambda r: -r["days_late"])

        stale_rfqs = client.search_count("purchase.order", [
            ("state", "in", ["draft", "sent"]),
            ("create_date", "<",
             (today - timedelta(days=rfq_stale_days)).isoformat()),
            *company_domain,
        ])

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

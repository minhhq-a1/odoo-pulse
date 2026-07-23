"""Procurement watch report service."""

from __future__ import annotations

from datetime import timedelta

from ...common.concurrency import gather_strict
from ...common.dates import parse_when, utc_bound
from ...common.money import totals_by_currency
from ...common.paging import fetch_with_truncation, paged_search_read
from ...common.reporting import build_report
from ...common.schema import optional_fields
from ..report_context import build_report_context


def build_procurement_watch(
    client,
    *,
    late_grace_days: int = 0,
    rfq_stale_days: int = 7,
    top_n: int = 5,
    timezone_offset: int = 7,
    company: str | int | None = None,
) -> dict:
    context = build_report_context(
        client, timezone_offset=timezone_offset, company=company
    )
    today = context.today
    company_domain = list(context.company_domain)

    order_schema = client.fields_get("purchase.order")
    has_receipt_status = "receipt_status" in order_schema
    line_fields = optional_fields(
        client,
        "purchase.order.line",
        ["order_id", "product_qty", "qty_received", "price_total"],
    )
    has_remaining_lines = set(line_fields) == {
        "order_id", "product_qty", "qty_received", "price_total"}
    order_fields = [
        "id", "name", "partner_id", "date_planned",
        "amount_total", "state", "currency_id",
    ]
    if has_receipt_status:
        order_fields.append("receipt_status")

    fetched = gather_strict({
        "orders": lambda: fetch_with_truncation(
            client, "purchase.order",
            [("state", "=", "purchase"), *company_domain],
            fields=order_fields,
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

    lines: list[dict] = []
    if has_remaining_lines and orders:
        lines = paged_search_read(
            client,
            "purchase.order.line",
            [("order_id", "in", [po["id"] for po in orders])],
            ["order_id", "product_qty", "qty_received", "price_total"],
        )
    remaining_by_order: dict[int, float] = {}
    for line in lines:
        order = line.get("order_id")
        quantity = line.get("product_qty") or 0.0
        received = line.get("qty_received") or 0.0
        if not order or quantity <= 0:
            continue
        ratio = max(quantity - received, 0.0) / quantity
        remaining_by_order[order[0]] = (
            remaining_by_order.get(order[0], 0.0)
            + (line.get("price_total") or 0.0) * ratio)

    open_orders: list[dict] = []
    for po in orders:
        if has_remaining_lines:
            amount = remaining_by_order.get(po["id"], 0.0)
            include = amount > 0
        elif has_receipt_status:
            include = po.get("receipt_status") != "full"
            amount = po.get("amount_total") or 0.0
        else:
            include = True
            amount = po.get("amount_total") or 0.0
        if not include:
            continue
        open_orders.append({**po, "open_value": amount})

    late_cutoff = today - timedelta(days=late_grace_days)
    open_value = 0.0
    late: list[dict] = []
    vendors: dict[str, dict] = {}
    for po in open_orders:
        amount = po["open_value"]
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
        "open_pos": len(open_orders),
        "open_value": round(open_value, 2),
        "late_receipts": len(late),
        "stale_rfqs": stale_rfqs,
        "receipt_tracking_available": has_receipt_status or has_remaining_lines,
        "remaining_value_available": has_remaining_lines,
        "verdict": verdict,
    }
    by_currency = totals_by_currency(open_orders, "open_value")
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
        f"{len(open_orders)} confirmed PO(s) worth {round(open_value, 2)} open"]
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
    if has_receipt_status and not has_remaining_lines:
        risks.append({
            "code": "partial_receipt_value_estimated",
            "count": len(open_orders),
            "message": (
                "Partial PO open values use full order totals; "
                "remaining line values are unavailable."),
        })
    elif not has_receipt_status and not has_remaining_lines:
        risks.append({
            "code": "receipt_tracking_unavailable",
            "count": len(open_orders),
            "message": (
                "Receipt fields are unavailable; confirmed PO "
                "population and values may include received goods."),
        })

    return build_report(
        "procurement_watch", today,
        summary=summary,
        breakdown={"late_receipts": late[:top_n], "top_vendors": top_vendors},
        highlights=highlights, risks=risks,
        extra={"company": company},
    )

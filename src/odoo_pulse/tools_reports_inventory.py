# odoo_pulse/tools_reports_inventory.py
"""Inventory report tools: shortages and dead stock.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from datetime import timedelta

from .common.dates import today_in_tz, utc_bound
from .common.paging import fetch_with_truncation
from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .workflow_helpers import (
    build_report,
    gather_strict,
    resolve_company_id,
)


@mcp.tool()
def inventory_risk(
    dead_stock_days: int = 90,
    top_n: int = 10,
    timezone_offset: int = 7,
    company: str | int | None = None,
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
        company: Optional company id or name; scopes stock quantities via
            allowed_company_ids context and dead-stock moves via company_id.
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)

        company_id = resolve_company_id(client, company)
        ctx = {"allowed_company_ids": [company_id]} if company_id else None

        since = utc_bound(today - timedelta(days=dead_stock_days), timezone_offset)

        def product_lists():
            # Both product.product fetches share one thunk (ordered) so they
            # never race each other (real Odoo or the fake's per-model queue).
            short = fetch_with_truncation(
                client, "product.product",
                [("type", "=", "consu"), ("is_storable", "=", True),
                 ("virtual_available", "<", 0)],
                fields=["id", "name", "default_code", "qty_available",
                        "virtual_available"],
                limit=200,
                context=ctx,
            )
            stocked = fetch_with_truncation(
                client, "product.product",
                [("type", "=", "consu"), ("is_storable", "=", True),
                 ("qty_available", ">", 0)],
                fields=["id", "name", "default_code", "qty_available",
                        "standard_price"],
                limit=200,
                context=ctx,
            )
            return short, stocked

        def moved_aggregate():
            domain: list = [("state", "=", "done"), ("date", ">=", since)]
            if company_id:
                domain.append(("company_id", "=", company_id))
            return client.aggregate_records(
                "stock.move", group_by=["product_id"], measures=[],
                domain=domain,
                limit=200,
            )

        fetched = gather_strict(
            {"products": product_lists, "moves": moved_aggregate})
        (short_rows, short_trunc), (stocked, stocked_trunc) = fetched["products"]
        agg = fetched["moves"]

        shortages = [
            {"product": p["name"], "code": p.get("default_code") or None,
             "on_hand": p.get("qty_available") or 0.0,
             "forecasted": p.get("virtual_available") or 0.0}
            for p in short_rows
        ]
        shortages.sort(key=lambda r: r["forecasted"])

        moved_rows = agg.get("rows", [])
        moved_ids = {row["product_id"][0] for row in moved_rows
                     if row.get("product_id")}
        moved_capped = len(moved_rows) >= min(200, client.config.max_records)
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
            extra={"dead_stock_days": dead_stock_days, "company": company},
        )

    return safe(run)

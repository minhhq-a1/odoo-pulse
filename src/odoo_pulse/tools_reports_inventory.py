# odoo_pulse/tools_reports_inventory.py
"""Inventory report tools: shortages and dead stock.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .services.inventory.risk import build_inventory_risk


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
    return safe(lambda: build_inventory_risk(
        get_client(), dead_stock_days=dead_stock_days, top_n=top_n,
        timezone_offset=timezone_offset, company=company,
    ))

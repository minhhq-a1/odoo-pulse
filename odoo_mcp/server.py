"""MCP server exposing read-only access to an Odoo instance via XML-RPC.

Generic tools (model-agnostic):
  - odoo_version, list_models, get_model_fields
  - search_read, search_count, read_records

Domain tools (convenience wrappers for common modules):
  - Contacts:   find_partner
  - CRM:        list_opportunities
  - Sales:      list_sale_orders, get_sale_order
  - Purchase:   list_purchase_orders
  - Inventory:  find_products, check_stock
  - Accounting: list_invoices

Write operations (create/write/unlink) are intentionally not exposed yet, and
the underlying client blocks them while ODOO_READ_ONLY is true.
"""

from __future__ import annotations

from .runtime import mcp

# Importing these modules registers their @mcp.tool() functions as a side effect.
from . import tools_generic  # noqa: F401  (registers generic tools)
from . import domain_tools  # noqa: F401  (registers domain tools)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

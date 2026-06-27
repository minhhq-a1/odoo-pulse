"""MCP server exposing read-only access to an Odoo instance via XML-RPC.

Generic tools (model-agnostic):
  - odoo_version, list_models, get_model_fields
  - search_read, search_count, read_records

Domain tools (convenience wrappers for common modules):
  - Contacts:   find_partner
  - CRM:        list_opportunities
  - Sales:      list_sale_orders, get_sale_order
  - Purchase:   list_purchase_orders, get_purchase_order
  - Inventory:  find_products, check_stock, list_pickings
  - Accounting: list_invoices, get_invoice, list_payments
  - HR:         employees, departments, time off, expenses, recruitment, attendance
  - Project:    projects, tasks, timesheets
  - Operations: manufacturing, BoM, PoS, repair, maintenance, helpdesk, fleet
  - Engagement: events, calendar, activities, surveys, email campaigns
  - Niche:      subscriptions, sign, documents, knowledge, approvals, lunch,
                quality, planning, eLearning, loyalty, memberships, payroll,
                appraisals, social, website, PLM, IoT, notes
  - Write:      create_record, update_records, delete_records, and helpers
                create_lead, create_contact, create_task, confirm_sale_order

Write tools are gated: they require ODOO_READ_ONLY=false, the target model in
ODOO_WRITABLE_MODELS, a per-call confirm=true, and (for deletes) ODOO_ALLOW_DELETE.
System models and the configured defaults keep the server read-only out of the box.
"""

from __future__ import annotations

from .runtime import mcp

# Importing these modules registers their @mcp.tool() functions as a side effect.
from . import tools_generic  # noqa: F401  (generic CRUD tools)
from . import tools_write  # noqa: F401
from . import domain_tools  # noqa: F401  (Contacts/CRM/Sales/Purchase/Inventory/Accounting)
from . import tools_hr  # noqa: F401  (Human Resources)
from . import tools_projects  # noqa: F401  (Project & Timesheets)
from . import tools_operations  # noqa: F401  (MRP/PoS/Repair/Maintenance/Helpdesk/Fleet)
from . import tools_engagement  # noqa: F401  (Events/Calendar/Activities/Marketing)
from . import tools_niche  # noqa: F401  (specialised / Enterprise modules)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

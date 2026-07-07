"""Domain-specific convenience tools.

These wrap the generic ``search_read`` with sensible defaults (filters, field
sets, ordering) for the most common Odoo business objects so an LLM can answer
typical questions without knowing technical model/field names.

Covered modules:
  - Contacts    (res.partner)
  - CRM         (crm.lead)
  - Sales       (sale.order, sale.order.line)
  - Purchase    (purchase.order, purchase.order.line)
  - Inventory   (product.product, stock.quant, stock.picking)
  - Accounting  (account.move, account.move.line, account.payment)

Everything here is read-only.
"""

from __future__ import annotations

from typing import Any

from .runtime import date_domain, get_client, mcp, name_domain, safe
from .workflow_helpers import optional_fields


# --- Contacts -----------------------------------------------------------------


@mcp.tool()
def find_partner(query: str, limit: int = 20) -> str:
    """Find contacts/companies (res.partner) by name, email, phone or reference.

    mobile was removed from res.partner in Odoo 19; it is searched/returned
    only when the instance still has it.

    Args:
        query: Free text matched against name, email, phone and customer ref.
        limit: Max results.
    """

    def run():
        client = get_client()
        mobile = optional_fields(client, "res.partner", ["mobile"])
        domain = name_domain(query, ["name", "email", "phone", *mobile, "ref", "vat"])
        return client.search_read(
            "res.partner",
            domain=domain,
            fields=[
                "name",
                "email",
                "phone",
                *mobile,
                "city",
                "country_id",
                "is_company",
                "customer_rank",
                "supplier_rank",
            ],
            limit=limit,
            order="name",
        )

    return safe(run)


# --- CRM ----------------------------------------------------------------------


@mcp.tool()
def list_opportunities(
    query: str | None = None,
    stage: str | None = None,
    salesperson: str | None = None,
    limit: int = 20,
) -> str:
    """List CRM opportunities (crm.lead, type='opportunity').

    Args:
        query: Free text matched against the opportunity name or partner name.
        stage: Filter by stage name (e.g. 'New', 'Qualified', 'Won').
        salesperson: Filter by the assigned salesperson's name.
        limit: Max results.
    """
    domain: list = [("type", "=", "opportunity")]
    domain += name_domain(query, ["name", "partner_name", "contact_name"])
    if stage:
        domain.append(("stage_id.name", "ilike", stage))
    if salesperson:
        domain.append(("user_id.name", "ilike", salesperson))
    return safe(
        lambda: get_client().search_read(
            "crm.lead",
            domain=domain,
            fields=[
                "name",
                "partner_id",
                "stage_id",
                "user_id",
                "expected_revenue",
                "probability",
                "date_deadline",
            ],
            limit=limit,
            order="expected_revenue desc",
        )
    )


# --- Sales --------------------------------------------------------------------

# Odoo sale.order.state codes -> human label, for readability in prompts.
_SALE_STATES = {"draft", "sent", "sale", "done", "cancel"}


@mcp.tool()
def list_sale_orders(
    customer: str | None = None,
    state: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> str:
    """List sales orders (sale.order).

    Args:
        customer: Filter by customer name (partner).
        state: Order state code: draft, sent, sale, done or cancel.
        date_from: Inclusive lower bound on order date (YYYY-MM-DD).
        date_to: Inclusive upper bound on order date (YYYY-MM-DD).
        limit: Max results.
    """
    domain: list = []
    if customer:
        domain.append(("partner_id.name", "ilike", customer))
    if state and state in _SALE_STATES:
        domain.append(("state", "=", state))
    domain += date_domain("date_order", date_from, date_to)
    return safe(
        lambda: get_client().search_read(
            "sale.order",
            domain=domain,
            fields=[
                "name",
                "partner_id",
                "date_order",
                "amount_total",
                "state",
                "invoice_status",
            ],
            limit=limit,
            order="date_order desc",
        )
    )


@mcp.tool()
def get_sale_order(order_id: int | None = None, order_name: str | None = None) -> str:
    """Fetch a single sales order with its line items.

    Provide either the numeric `order_id` or the `order_name` (e.g. 'S00042').
    Returns the order header plus its order lines (product, qty, price).
    """
    client = get_client()

    def _run() -> dict[str, Any]:
        oid = order_id
        if oid is None:
            if not order_name:
                return {"error": "Provide order_id or order_name."}
            found = client.search_read(
                "sale.order", domain=[("name", "=", order_name)], fields=["id"], limit=1
            )
            if not found:
                return {"error": f"No sale order named {order_name!r}."}
            oid = found[0]["id"]

        header = client.read(
            "sale.order",
            [oid],
            fields=[
                "name",
                "partner_id",
                "date_order",
                "amount_untaxed",
                "amount_tax",
                "amount_total",
                "state",
                "order_line",
            ],
        )
        if not header:
            return {"error": f"No sale order with id {oid}."}
        order = header[0]
        lines = client.read(
            "sale.order.line",
            order.get("order_line", []),
            fields=["product_id", "name", "product_uom_qty", "price_unit", "price_subtotal"],
        )
        order["lines"] = lines
        order.pop("order_line", None)
        return order

    return safe(_run)


# --- Purchase -----------------------------------------------------------------


@mcp.tool()
def list_purchase_orders(
    vendor: str | None = None,
    state: str | None = None,
    limit: int = 20,
) -> str:
    """List purchase orders (purchase.order).

    Args:
        vendor: Filter by vendor name.
        state: Order state code: draft, sent, purchase, done or cancel.
        limit: Max results.
    """
    domain: list = []
    if vendor:
        domain.append(("partner_id.name", "ilike", vendor))
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "purchase.order",
            domain=domain,
            fields=["name", "partner_id", "date_order", "amount_total", "state"],
            limit=limit,
            order="date_order desc",
        )
    )


# --- Inventory ----------------------------------------------------------------


@mcp.tool()
def find_products(query: str | None = None, limit: int = 20) -> str:
    """Find products (product.product) with on-hand and forecasted quantities.

    Args:
        query: Free text matched against product name or internal reference.
        limit: Max results.
    """
    domain = name_domain(query, ["name", "default_code", "barcode"])
    return safe(
        lambda: get_client().search_read(
            "product.product",
            domain=domain,
            fields=[
                "name",
                "default_code",
                "list_price",
                "standard_price",
                "qty_available",
                "virtual_available",
                "uom_id",
            ],
            limit=limit,
            order="name",
        )
    )


@mcp.tool()
def check_stock(product_query: str, limit: int = 50) -> str:
    """Check on-hand stock per location for products matching a query.

    Reads stock.quant (actual on-hand quantities) grouped by location.

    Args:
        product_query: Free text matched against product name or reference.
        limit: Max quant rows to return.
    """
    domain = [
        "|",
        ("product_id.name", "ilike", product_query),
        ("product_id.default_code", "ilike", product_query),
        ("location_id.usage", "=", "internal"),
    ]
    return safe(
        lambda: get_client().search_read(
            "stock.quant",
            domain=domain,
            fields=["product_id", "location_id", "quantity", "reserved_quantity", "available_quantity"],
            limit=limit,
            order="product_id",
        )
    )


# --- Accounting ---------------------------------------------------------------


@mcp.tool()
def list_invoices(
    customer: str | None = None,
    move_type: str = "out_invoice",
    unpaid_only: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> str:
    """List invoices/bills (account.move).

    Args:
        customer: Filter by partner name.
        move_type: 'out_invoice' (customer invoice), 'in_invoice' (vendor bill),
            'out_refund' (credit note) or 'in_refund' (vendor refund).
        unpaid_only: If true, only invoices that are not fully paid.
        date_from: Inclusive lower bound on invoice date (YYYY-MM-DD).
        date_to: Inclusive upper bound on invoice date (YYYY-MM-DD).
        limit: Max results.
    """
    domain: list = [("move_type", "=", move_type), ("state", "=", "posted")]
    if customer:
        domain.append(("partner_id.name", "ilike", customer))
    if unpaid_only:
        domain.append(("payment_state", "in", ("not_paid", "partial")))
    domain += date_domain("invoice_date", date_from, date_to)
    return safe(
        lambda: get_client().search_read(
            "account.move",
            domain=domain,
            fields=[
                "name",
                "partner_id",
                "invoice_date",
                "invoice_date_due",
                "amount_total",
                "amount_residual",
                "payment_state",
                "state",
            ],
            limit=limit,
            order="invoice_date desc",
        )
    )


@mcp.tool()
def get_invoice(move_id: int | None = None, number: str | None = None) -> str:
    """Fetch a single invoice/bill (account.move) with its line items.

    Provide either the numeric `move_id` or the `number` (e.g. 'INV/2026/0001').
    """
    client = get_client()

    def _run() -> dict[str, Any]:
        mid = move_id
        if mid is None:
            if not number:
                return {"error": "Provide move_id or number."}
            found = client.search_read(
                "account.move", domain=[("name", "=", number)], fields=["id"], limit=1
            )
            if not found:
                return {"error": f"No invoice numbered {number!r}."}
            mid = found[0]["id"]

        header = client.read(
            "account.move",
            [mid],
            fields=[
                "name",
                "partner_id",
                "move_type",
                "invoice_date",
                "invoice_date_due",
                "amount_untaxed",
                "amount_tax",
                "amount_total",
                "amount_residual",
                "payment_state",
                "state",
                "invoice_line_ids",
            ],
        )
        if not header:
            return {"error": f"No invoice with id {mid}."}
        move = header[0]
        lines = client.read(
            "account.move.line",
            move.get("invoice_line_ids", []),
            fields=["name", "product_id", "quantity", "price_unit", "price_subtotal", "account_id"],
        )
        move["lines"] = lines
        move.pop("invoice_line_ids", None)
        return move

    return safe(_run)


@mcp.tool()
def list_payments(
    partner: str | None = None,
    payment_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> str:
    """List customer/vendor payments (account.payment).

    Args:
        partner: Filter by partner name.
        payment_type: 'inbound' (received) or 'outbound' (sent).
        date_from: Inclusive lower bound on payment date (YYYY-MM-DD).
        date_to: Inclusive upper bound on payment date (YYYY-MM-DD).
        limit: Max results.
    """
    domain: list = []
    if partner:
        domain.append(("partner_id.name", "ilike", partner))
    if payment_type in ("inbound", "outbound"):
        domain.append(("payment_type", "=", payment_type))
    domain += date_domain("date", date_from, date_to)
    return safe(
        lambda: get_client().search_read(
            "account.payment",
            domain=domain,
            fields=["name", "partner_id", "payment_type", "amount", "date", "state", "journal_id"],
            limit=limit,
            order="date desc",
        )
    )


# --- Purchase (supplement) ----------------------------------------------------


@mcp.tool()
def get_purchase_order(order_id: int | None = None, order_name: str | None = None) -> str:
    """Fetch a single purchase order with its line items.

    Provide either the numeric `order_id` or the `order_name` (e.g. 'P00007').
    """
    client = get_client()

    def _run() -> dict[str, Any]:
        oid = order_id
        if oid is None:
            if not order_name:
                return {"error": "Provide order_id or order_name."}
            found = client.search_read(
                "purchase.order", domain=[("name", "=", order_name)], fields=["id"], limit=1
            )
            if not found:
                return {"error": f"No purchase order named {order_name!r}."}
            oid = found[0]["id"]

        header = client.read(
            "purchase.order",
            [oid],
            fields=[
                "name",
                "partner_id",
                "date_order",
                "amount_untaxed",
                "amount_tax",
                "amount_total",
                "state",
                "order_line",
            ],
        )
        if not header:
            return {"error": f"No purchase order with id {oid}."}
        order = header[0]
        lines = client.read(
            "purchase.order.line",
            order.get("order_line", []),
            fields=["product_id", "name", "product_qty", "price_unit", "price_subtotal"],
        )
        order["lines"] = lines
        order.pop("order_line", None)
        return order

    return safe(_run)


# --- Inventory (supplement) ---------------------------------------------------


@mcp.tool()
def list_pickings(
    picking_type: str | None = None,
    partner: str | None = None,
    state: str | None = None,
    limit: int = 20,
) -> str:
    """List stock transfers / pickings (stock.picking): deliveries, receipts, internal.

    Args:
        picking_type: 'incoming' (receipts), 'outgoing' (deliveries) or 'internal'.
        partner: Filter by partner name.
        state: draft, waiting, confirmed, assigned, done or cancel.
        limit: Max results.
    """
    domain: list = []
    if picking_type in ("incoming", "outgoing", "internal"):
        domain.append(("picking_type_id.code", "=", picking_type))
    if partner:
        domain.append(("partner_id.name", "ilike", partner))
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "stock.picking",
            domain=domain,
            fields=[
                "name",
                "partner_id",
                "scheduled_date",
                "date_done",
                "state",
                "origin",
                "picking_type_id",
            ],
            limit=limit,
            order="scheduled_date desc",
        )
    )

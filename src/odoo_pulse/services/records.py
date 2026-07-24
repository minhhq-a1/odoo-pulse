from __future__ import annotations

from typing import Any

from ..core.errors import OdooError


def read_one(client: Any, model: str, record_id: int) -> dict:
    """Read exactly one record, raising if it doesn't exist.

    Not-found is an error here (a caller asking for one record by id
    wants that record, not silence) — a deliberate deviation from
    `read_records`, which returns [] for missing ids. On live Odoo a
    missing id usually raises MissingError server-side already (an
    OdooError via execute_kw); the empty-result check below is the
    defensive catch-all and the path the FakeClient exercises in tests.
    """
    rows = client.read(model, [record_id])
    if not rows:
        raise OdooError(f"{model} record {record_id} not found")
    return rows[0]


def resolve_record_id(
    client: Any,
    *,
    model: str,
    record_id: int | None,
    reference: str | None,
    reference_field: str,
    input_error: str,
    not_found_template: str,
) -> int:
    if record_id is not None:
        return record_id
    if not reference:
        raise OdooError(input_error)
    found = client.search_read(
        model, domain=[(reference_field, "=", reference)], fields=["id"], limit=1
    )
    if not found:
        raise OdooError(not_found_template.format(reference=reference))
    return found[0]["id"]


def read_sale_order(
    client: Any, *, order_id: int | None = None, order_name: str | None = None
) -> dict:
    oid = resolve_record_id(
        client,
        model="sale.order",
        record_id=order_id,
        reference=order_name,
        reference_field="name",
        input_error="Provide order_id or order_name.",
        not_found_template="No sale order named {reference!r}.",
    )
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
        raise OdooError(f"No sale order with id {oid}.")
    order = header[0]
    lines = client.read(
        "sale.order.line",
        order.get("order_line", []),
        fields=["product_id", "name", "product_uom_qty", "price_unit", "price_subtotal"],
    )
    order["lines"] = lines
    order.pop("order_line", None)
    return order


def read_invoice(
    client: Any, *, move_id: int | None = None, number: str | None = None
) -> dict:
    mid = resolve_record_id(
        client,
        model="account.move",
        record_id=move_id,
        reference=number,
        reference_field="name",
        input_error="Provide move_id or number.",
        not_found_template="No invoice numbered {reference!r}.",
    )
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
        raise OdooError(f"No invoice with id {mid}.")
    move = header[0]
    lines = client.read(
        "account.move.line",
        move.get("invoice_line_ids", []),
        fields=["name", "product_id", "quantity", "price_unit", "price_subtotal", "account_id"],
    )
    move["lines"] = lines
    move.pop("invoice_line_ids", None)
    return move


def read_purchase_order(
    client: Any, *, order_id: int | None = None, order_name: str | None = None
) -> dict:
    oid = resolve_record_id(
        client,
        model="purchase.order",
        record_id=order_id,
        reference=order_name,
        reference_field="name",
        input_error="Provide order_id or order_name.",
        not_found_template="No purchase order named {reference!r}.",
    )
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
        raise OdooError(f"No purchase order with id {oid}.")
    order = header[0]
    lines = client.read(
        "purchase.order.line",
        order.get("order_line", []),
        fields=["product_id", "name", "product_qty", "price_unit", "price_subtotal"],
    )
    order["lines"] = lines
    order.pop("order_line", None)
    return order

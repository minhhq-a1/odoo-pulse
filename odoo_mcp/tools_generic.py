"""Generic, model-agnostic read-only tools over the Odoo external API."""

from __future__ import annotations

from .runtime import get_client, mcp, safe


@mcp.tool()
def odoo_version() -> str:
    """Check connectivity and return the Odoo server version info."""
    return safe(lambda: get_client().version())


@mcp.tool()
def list_models(name_filter: str | None = None) -> str:
    """List Odoo models (technical name + label). Optionally filter by a
    case-insensitive substring matched against the model name or label,
    e.g. 'sale', 'res.partner', 'invoice'."""
    return safe(lambda: get_client().list_models(name_filter))


@mcp.tool()
def get_model_fields(model: str, fields: list[str] | None = None) -> str:
    """Inspect the schema of an Odoo model. Returns each field's label, type,
    help text, requiredness and relation. Pass `fields` to limit the result
    to specific field names. Example model: 'res.partner'."""
    if fields:
        return safe(
            lambda: {
                name: meta
                for name, meta in get_client().fields_get(model).items()
                if name in set(fields)
            }
        )
    return safe(lambda: get_client().fields_get(model))


@mcp.tool()
def search_read(
    model: str,
    domain: list | None = None,
    fields: list[str] | None = None,
    limit: int | None = None,
    offset: int = 0,
    order: str | None = None,
) -> str:
    """Query records from an Odoo model.

    Args:
        model: Technical model name, e.g. 'sale.order', 'res.partner'.
        domain: Odoo search domain as a list of triplets, e.g.
            [["state", "=", "sale"], ["amount_total", ">", 1000]].
            Use 'and'/'|' operators as Odoo expects. Defaults to all records.
        fields: Field names to return. Omit to let Odoo decide (can be large).
        limit: Max records (capped by ODOO_MAX_RECORDS).
        offset: Pagination offset.
        order: Sort spec, e.g. 'date_order desc'.
    """
    return safe(
        lambda: get_client().search_read(
            model, domain=domain, fields=fields, limit=limit, offset=offset, order=order
        )
    )


@mcp.tool()
def search_count(model: str, domain: list | None = None) -> str:
    """Count records in a model matching an Odoo domain filter."""
    return safe(lambda: {"count": get_client().search_count(model, domain)})


@mcp.tool()
def read_records(model: str, ids: list[int], fields: list[str] | None = None) -> str:
    """Fetch specific records by their ids. Pass `fields` to limit columns."""
    return safe(lambda: get_client().read(model, ids, fields))

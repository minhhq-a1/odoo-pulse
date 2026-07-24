"""Generic, model-agnostic read-only tools over the Odoo external API."""

from __future__ import annotations

from ..mcp.app import mcp
from ..mcp.result import safe
from ..mcp.runtime import get_client
from ..services.generic import (
    aggregate_records as build_aggregate_records,
    count_records as build_count_records,
    get_model_fields as build_model_fields,
    get_odoo_version,
    list_models as build_list_models,
    read_attachment as build_attachment,
    read_records as build_read_records,
    search_records as build_search_records,
)


@mcp.tool()
def odoo_version() -> str:
    """Check connectivity and return the Odoo server version info."""
    return safe(lambda: get_odoo_version(get_client()))


@mcp.tool()
def list_models(name_filter: str | None = None) -> str:
    """List Odoo models (technical name + label). Optionally filter by a
    case-insensitive substring matched against the model name or label,
    e.g. 'sale', 'res.partner', 'invoice'."""
    return safe(lambda: build_list_models(get_client(), name_filter))


@mcp.tool()
def get_model_fields(model: str, fields: list[str] | None = None) -> str:
    """Inspect the schema of an Odoo model. Returns each field's label, type,
    help text, requiredness and relation. Pass `fields` to limit the result
    to specific field names. Example model: 'res.partner'."""
    return safe(lambda: build_model_fields(get_client(), model, fields))


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
        lambda: build_search_records(
            get_client(), model, domain=domain, fields=fields, limit=limit,
            offset=offset, order=order,
        )
    )


@mcp.tool()
def search_count(model: str, domain: list | None = None) -> str:
    """Count records in a model matching an Odoo domain filter."""
    return safe(lambda: build_count_records(get_client(), model, domain))


@mcp.tool()
def read_records(model: str, ids: list[int], fields: list[str] | None = None) -> str:
    """Fetch specific records by their ids. Pass `fields` to limit columns."""
    return safe(lambda: build_read_records(get_client(), model, ids, fields))


@mcp.tool()
def aggregate_records(
    model: str,
    group_by: list[str],
    measures: list[str] | None = None,
    domain: list | None = None,
    limit: int | None = None,
    offset: int = 0,
    order: str | None = None,
) -> str:
    """Group and aggregate records server-side (one call instead of pulling rows).

    Args:
        model: Technical model name, e.g. 'sale.order'.
        group_by: One or more fields to group on. A field may carry a
            granularity, e.g. 'date_order:month'.
        measures: 'field:agg' specs. Bare 'field' means sum. Allowed
            aggregators: sum, avg, min, max, count, count_distinct. Omit to
            count records.
        domain: Odoo search domain (list of triplets). Defaults to all records.
            limit: Max groups (capped by ODOO_MAX_RECORDS).
        offset: Pagination offset over groups.
        order: Sort spec, e.g. 'amount_total desc'.
    """
    return safe(
        lambda: build_aggregate_records(
            get_client(), model, group_by, measures=measures, domain=domain,
            limit=limit, offset=offset, order=order,
        )
    )


@mcp.tool()
def read_attachment(attachment_id: int, include_data: bool = True) -> str:
    """Read an ir.attachment: metadata always, base64 content when small enough.

    Binary attachments under ODOO_MAX_ATTACHMENT_BYTES are returned with their
    base64 `datas`; larger ones return metadata plus a warning. URL-type
    attachments return the link, never binary data.

    Args:
        attachment_id: The ir.attachment id.
        include_data: When False, return metadata only (no base64 fetch).
    """
    return safe(lambda: build_attachment(get_client(), attachment_id, include_data))

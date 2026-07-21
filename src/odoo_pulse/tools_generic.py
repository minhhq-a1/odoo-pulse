"""Generic, model-agnostic read-only tools over the Odoo external API."""

from __future__ import annotations

from .odoo_client import OdooError
from .runtime import get_client, mcp, safe


@mcp.tool()
def odoo_version() -> str:
    """Check connectivity and return the Odoo server version info."""

    def run() -> dict:
        client = get_client()
        info = dict(client.version())
        major = client.major_version()
        if major is not None and major < 18:
            info["warning"] = (
                "odoo-pulse targets Odoo 18+; report tools are not "
                "guaranteed on this version."
            )
        return info

    return safe(run)


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


_ALLOWED_AGGS = frozenset(
    {"sum", "avg", "min", "max", "count", "count_distinct"}
)


def _parse_measures(measures: list[str] | None) -> list[tuple[str, str]]:
    """Parse 'field:agg' specs into (field, aggregator) pairs.

    Bare 'field' defaults to sum. Empty input defaults to counting records.
    Raises OdooError on an unsupported aggregator so safe() reports it cleanly,
    before any Odoo call happens.
    """
    parsed: list[tuple[str, str]] = []
    for spec in measures or []:
        field, sep, agg = spec.partition(":")
        field = field.strip()
        agg = (agg.strip() or "sum") if sep else "sum"
        if not field:
            raise OdooError(f"Invalid measure spec: {spec!r}")
        if agg not in _ALLOWED_AGGS:
            raise OdooError(
                f"Unsupported aggregator {agg!r} in {spec!r}; "
                f"allowed: {sorted(_ALLOWED_AGGS)}"
            )
        parsed.append((field, agg))
    if not parsed:
        parsed = [("id", "count")]
    return parsed


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

    def run() -> dict:
        if not group_by:
            raise OdooError("group_by must contain at least one field.")
        parsed = _parse_measures(measures)
        result = get_client().aggregate_records(
            model,
            group_by,
            parsed,
            domain=domain,
            limit=limit,
            offset=offset,
            order=order,
        )
        rows = result["rows"]
        return {
            "method": result["method"],
            "major_version": result["major_version"],
            "model": model,
            "group_by": group_by,
            "measures": [f"{field}:{agg}" for field, agg in parsed],
            "row_count": len(rows),
            "rows": rows,
        }

    return safe(run)


_ATTACHMENT_META_FIELDS = [
    "name",
    "mimetype",
    "file_size",
    "type",
    "url",
    "res_model",
    "res_id",
    "checksum",
    "create_date",
]


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

    def run() -> dict:
        client = get_client()
        cap = client.config.max_attachment_bytes
        meta = client.read("ir.attachment", [attachment_id], _ATTACHMENT_META_FIELDS)
        if not meta:
            raise OdooError(f"Attachment {attachment_id} not found.")
        att = meta[0]
        warnings: list[str] = []
        data_base64 = None
        data_included = False

        if att.get("type") == "url":
            warnings.append("Attachment is a URL link; no binary data. See 'url'.")
        elif include_data:
            size = att.get("file_size") or 0
            if size <= cap:
                blob = client.read("ir.attachment", [attachment_id], ["datas"])
                data_base64 = blob[0].get("datas") if blob else None
                data_included = data_base64 is not None
            else:
                warnings.append(
                    f"file_size {size} exceeds ODOO_MAX_ATTACHMENT_BYTES "
                    f"({cap}); data omitted."
                )

        return {
            "attachment": att,
            "data_base64": data_base64,
            "data_included": data_included,
            "max_bytes": cap,
            "warnings": warnings,
        }

    return safe(run)

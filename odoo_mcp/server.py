"""MCP server exposing read-only access to an Odoo instance via XML-RPC.

Tools (read-only by default):
  - odoo_version       : connectivity / version check
  - list_models        : discover available Odoo models
  - get_model_fields   : inspect a model's schema (fields_get)
  - search_read        : query records with a domain filter
  - search_count       : count records matching a domain
  - read_records       : fetch specific records by id

Write operations (create/write/unlink) are intentionally not exposed yet.
The underlying client also blocks them while ODOO_READ_ONLY is true.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from .odoo_client import OdooClient, OdooConfig, OdooConfigError, OdooError

mcp = FastMCP("odoo-mcp")

_client: OdooClient | None = None


def get_client() -> OdooClient:
    """Lazily build the Odoo client so the server can start without creds
    being validated until the first tool call."""
    global _client
    if _client is None:
        _client = OdooClient(OdooConfig.from_env())
    return _client


def _safe(func) -> str:
    """Run a client call and serialise the result (or a friendly error) as JSON."""
    try:
        return json.dumps(func(), ensure_ascii=False, indent=2, default=str)
    except (OdooConfigError, OdooError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)


@mcp.tool()
def odoo_version() -> str:
    """Check connectivity and return the Odoo server version info."""
    return _safe(lambda: get_client().version())


@mcp.tool()
def list_models(name_filter: str | None = None) -> str:
    """List Odoo models (technical name + label). Optionally filter by a
    case-insensitive substring matched against the model name or label,
    e.g. 'sale', 'res.partner', 'invoice'."""
    return _safe(lambda: get_client().list_models(name_filter))


@mcp.tool()
def get_model_fields(model: str, fields: list[str] | None = None) -> str:
    """Inspect the schema of an Odoo model. Returns each field's label, type,
    help text, requiredness and relation. Pass `fields` to limit the result
    to specific field names. Example model: 'res.partner'."""
    if fields:
        return _safe(
            lambda: {
                name: meta
                for name, meta in get_client().fields_get(model).items()
                if name in set(fields)
            }
        )
    return _safe(lambda: get_client().fields_get(model))


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
    return _safe(
        lambda: get_client().search_read(
            model, domain=domain, fields=fields, limit=limit, offset=offset, order=order
        )
    )


@mcp.tool()
def search_count(model: str, domain: list | None = None) -> str:
    """Count records in a model matching an Odoo domain filter."""
    return _safe(lambda: {"count": get_client().search_count(model, domain)})


@mcp.tool()
def read_records(model: str, ids: list[int], fields: list[str] | None = None) -> str:
    """Fetch specific records by their ids. Pass `fields` to limit columns."""
    return _safe(lambda: get_client().read(model, ids, fields))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

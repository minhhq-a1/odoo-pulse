"""Shared runtime: the MCP instance, lazy Odoo client and a JSON-safe wrapper.

Kept in its own module so both the generic tools and the domain tools can
import these without creating an import cycle through ``server``.
"""

from __future__ import annotations

import json
import threading

from mcp.server.fastmcp import FastMCP

from .odoo_client import OdooClient, OdooConfig, OdooConfigError, OdooError

mcp = FastMCP("odoo-pulse")

_client: OdooClient | None = None
_client_lock = threading.Lock()


def get_client() -> OdooClient:
    """Lazily build the Odoo client so the server can start without creds
    being validated until the first tool call. Safe under concurrent calls."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = OdooClient(OdooConfig.from_env())
    return _client


def safe(func) -> str:
    """Run a client call and serialise the result (or a friendly error) as JSON."""
    try:
        return json.dumps(func(), ensure_ascii=False, indent=2, default=str)
    except (OdooConfigError, OdooError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)
    except Exception as exc:  # shaping bugs must not leak raw tracebacks
        return json.dumps(
            {"error": f"internal error: {type(exc).__name__}: {exc}"},
            ensure_ascii=False, indent=2,
        )


def name_domain(query: str | None, fields: list[str]) -> list:
    """Build an OR-of-ilike domain across `fields` for a free-text query.

    e.g. name_domain("acme", ["name", "email"]) ->
        ["|", ("name", "ilike", "acme"), ("email", "ilike", "acme")]
    """
    if not query:
        return []
    triplets = [(f, "ilike", query) for f in fields]
    if len(triplets) == 1:
        return [triplets[0]]
    return ["|"] * (len(triplets) - 1) + triplets


def date_domain(field: str, date_from: str | None, date_to: str | None) -> list:
    """Build a closed-interval domain on a date/datetime field."""
    domain: list = []
    if date_from:
        domain.append((field, ">=", date_from))
    if date_to:
        domain.append((field, "<=", date_to))
    return domain


def preview(action, model, *, values=None, ids=None, affected=None) -> dict:
    """Describe a write that WOULD happen, without performing it."""
    payload: dict = {
        "preview": True,
        "confirm_required": True,
        "action": action,
        "model": model,
        "hint": "Re-run with confirm=true to apply.",
    }
    if ids is not None:
        payload["ids"] = ids
        payload["count"] = len(ids)
    if affected is not None:
        payload["affected"] = affected
    if values is not None:
        payload["values"] = values
    return payload

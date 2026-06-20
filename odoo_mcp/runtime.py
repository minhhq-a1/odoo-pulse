"""Shared runtime: the MCP instance, lazy Odoo client and a JSON-safe wrapper.

Kept in its own module so both the generic tools and the domain tools can
import these without creating an import cycle through ``server``.
"""

from __future__ import annotations

import json

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


def safe(func) -> str:
    """Run a client call and serialise the result (or a friendly error) as JSON."""
    try:
        return json.dumps(func(), ensure_ascii=False, indent=2, default=str)
    except (OdooConfigError, OdooError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)

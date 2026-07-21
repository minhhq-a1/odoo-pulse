"""MCP resource: odoo://{model}/{id} — one live Odoo record as JSON.

odoo-pulse's first (and so far only) MCP Resource; everything else is a
tool. Registered as a resource *template*: clients see it via
resources/templates/list, not the plain resources/list. The read-one
behavior (including why a missing record is an error) lives in
services.records.read_one; this module is just the MCP-facing adapter.
"""

from __future__ import annotations

from ..services.records import read_one
from .app import mcp
from .result import safe
from .runtime import get_client


@mcp.resource("odoo://{model}/{id}", mime_type="application/json")
def odoo_record(model: str, id: int) -> str:
    """One Odoo record with all stored fields, e.g. odoo://res.partner/5."""
    # `id` shadows the builtin deliberately: the MCP SDK coerces this
    # from the URI string to int via pydantic.validate_call, and it
    # requires the URI template param name to match the function param
    # name exactly.
    return safe(lambda: read_one(get_client(), model, id))

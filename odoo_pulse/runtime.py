"""Shared runtime: the MCP instance, lazy Odoo client and a JSON-safe wrapper.

Kept in its own module so both the generic tools and the domain tools can
import these without creating an import cycle through ``server``.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

from .odoo_client import OdooClient, OdooConfig, OdooConfigError, OdooError

mcp = FastMCP(
    "odoo-pulse",
    instructions=(
        "Live business data from the user's own Odoo instance: records, "
        "reports, KPIs — read via tools (search_read, one-call reports) or "
        "the odoo://{model}/{id} resource. NOT for Odoo source-code or "
        "module-structure questions; use a code-index server for those."
    ),
)

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


def _iso_day(raw: str, parameter: str):
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise OdooError(
            f"Invalid {parameter} {raw!r}: expected YYYY-MM-DD")


def date_domain(
    field: str,
    date_from: str | None,
    date_to: str | None,
    *,
    as_datetime: bool = False,
) -> list:
    """Build an inclusive user-facing date range for Date or Datetime."""
    domain: list = []
    if date_from:
        start = _iso_day(date_from, "date_from")
        domain.append((field, ">=", start.isoformat()))
    if date_to:
        end = _iso_day(date_to, "date_to")
        if as_datetime:
            domain.append((field, "<", (end + timedelta(days=1)).isoformat()))
        else:
            domain.append((field, "<=", end.isoformat()))
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

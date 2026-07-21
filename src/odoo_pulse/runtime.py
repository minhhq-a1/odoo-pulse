"""Transitional facade over the split MCP runtime.

The FastMCP instance, lazy Odoo client singleton, and JSON-safe result
wrapper now live in ``odoo_pulse.mcp.*``; they are re-imported here so
existing callers keep working unchanged. The date/domain/preview helpers
below have not moved yet (they migrate in a later task).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .core.errors import OdooError
from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client

__all__ = ["mcp", "safe", "get_client", "name_domain", "date_domain", "preview"]


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

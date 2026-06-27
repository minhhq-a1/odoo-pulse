"""Write tools (create / update / delete) for the Odoo MCP server.

Every tool takes a ``confirm`` flag. With ``confirm=False`` (the default) the
tool returns a dry-run preview and performs no write. The actual write only
happens with ``confirm=True``, and even then it must clear the guard in
``OdooClient.execute_kw`` (read-only switch, allow-list, deny-list, delete gate).
"""

from __future__ import annotations

from .odoo_client import OdooError
from .runtime import get_client, mcp, preview, safe


def _display_names(model: str, ids: list[int]) -> list:
    rows = get_client().read(model, ids, fields=["display_name"])
    return [r.get("display_name") for r in rows]


def _require_ids() -> None:
    raise OdooError("ids must be a non-empty list.")


@mcp.tool()
def create_record(model: str, values: dict, confirm: bool = False) -> str:
    """Create one record. Returns a preview unless confirm=True.

    Args:
        model: Odoo model name (must be in ODOO_WRITABLE_MODELS).
        values: Field -> value mapping for the new record.
        confirm: Set True to actually create; otherwise a dry-run preview.
    """
    if not confirm:
        return safe(lambda: preview("create", model, values=values))
    return safe(lambda: {"created_id": get_client().create(model, values)})


@mcp.tool()
def update_records(
    model: str, ids: list[int], values: dict, confirm: bool = False
) -> str:
    """Update one or more records. Returns a preview unless confirm=True.

    Args:
        model: Odoo model name (must be in ODOO_WRITABLE_MODELS).
        ids: Record ids to update.
        values: Field -> value mapping to write.
        confirm: Set True to actually write; otherwise a dry-run preview.
    """
    if not ids:
        return safe(_require_ids)
    if not confirm:
        return safe(
            lambda: preview(
                "update", model, ids=ids, values=values, affected=_display_names(model, ids)
            )
        )
    return safe(lambda: {"updated": get_client().write(model, ids, values), "ids": ids})


@mcp.tool()
def delete_records(model: str, ids: list[int], confirm: bool = False) -> str:
    """Delete one or more records. Returns a preview unless confirm=True.

    Deletes also require ODOO_ALLOW_DELETE=true on the server.

    Args:
        model: Odoo model name (must be in ODOO_WRITABLE_MODELS).
        ids: Record ids to delete.
        confirm: Set True to actually delete; otherwise a dry-run preview.
    """
    if not ids:
        return safe(_require_ids)
    if not confirm:
        return safe(
            lambda: preview("delete", model, ids=ids, affected=_display_names(model, ids))
        )
    return safe(lambda: {"deleted": get_client().unlink(model, ids), "ids": ids})

"""Write tools (create / update / delete) for the Odoo MCP server.

Every tool takes a ``confirm`` flag. With ``confirm=False`` (the default) the
tool returns a dry-run preview and performs no write. The actual write only
happens with ``confirm=True``, and even then it must clear the guard in
``OdooClient.execute_kw`` (read-only switch, allow-list, deny-list, delete gate).
"""

from __future__ import annotations

from .core.errors import OdooError
from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .services.writes import preview


def _display_names(model: str, ids: list[int]) -> list:
    rows = get_client().read(model, ids, fields=["display_name"])
    return [r.get("display_name") for r in rows]


def _require_ids() -> None:
    raise OdooError("ids must be a non-empty list.")


def _merge_extra(values: dict, extra_values: dict | None) -> dict:
    """Merge caller-supplied extra fields into a helper-built values dict.

    Lets callers pass instance-specific or mandatory custom fields (e.g. a
    custom required ``presales_id`` on crm.lead) that the helper doesn't model.
    Explicit keys in ``extra_values`` win over the helper's own mapping.
    """
    if extra_values:
        values.update(extra_values)
    return values


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


@mcp.tool()
def create_lead(
    name: str,
    contact_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    description: str | None = None,
    extra_values: dict | None = None,
    confirm: bool = False,
) -> str:
    """Create a CRM lead/opportunity (crm.lead). Preview unless confirm=True.

    Use extra_values to set fields this helper doesn't model, including custom
    mandatory fields (e.g. {"presales_id": 5}).
    """
    values: dict = {"name": name}
    if contact_name:
        values["contact_name"] = contact_name
    if email:
        values["email_from"] = email
    if phone:
        values["phone"] = phone
    if description:
        values["description"] = description
    values = _merge_extra(values, extra_values)
    if not confirm:
        return safe(lambda: preview("create", "crm.lead", values=values))
    return safe(lambda: {"created_id": get_client().create("crm.lead", values)})


@mcp.tool()
def create_contact(
    name: str,
    email: str | None = None,
    phone: str | None = None,
    is_company: bool = False,
    parent_id: int | None = None,
    extra_values: dict | None = None,
    confirm: bool = False,
) -> str:
    """Create a contact (res.partner). Preview unless confirm=True.

    Use extra_values to set fields this helper doesn't model (e.g. {"vat": ...}).
    """
    values: dict = {"name": name}
    if email:
        values["email"] = email
    if phone:
        values["phone"] = phone
    if is_company:
        values["is_company"] = True
    if parent_id:
        values["parent_id"] = parent_id
    values = _merge_extra(values, extra_values)
    if not confirm:
        return safe(lambda: preview("create", "res.partner", values=values))
    return safe(lambda: {"created_id": get_client().create("res.partner", values)})


@mcp.tool()
def create_task(
    name: str,
    project_id: int,
    user_id: int | None = None,
    description: str | None = None,
    date_deadline: str | None = None,
    extra_values: dict | None = None,
    confirm: bool = False,
) -> str:
    """Create a project task (project.task). Preview unless confirm=True.

    Use list_projects to find the project_id first. Use extra_values to set
    fields this helper doesn't model (e.g. {"tag_ids": [(6, 0, [1])]}).
    """
    values: dict = {"name": name, "project_id": project_id}
    if user_id:
        values["user_ids"] = [(6, 0, [user_id])]
    if description:
        values["description"] = description
    if date_deadline:
        values["date_deadline"] = date_deadline
    values = _merge_extra(values, extra_values)
    if not confirm:
        return safe(lambda: preview("create", "project.task", values=values))
    return safe(lambda: {"created_id": get_client().create("project.task", values)})


@mcp.tool()
def confirm_sale_order(order_id: int, confirm: bool = False) -> str:
    """Confirm a quotation into a sales order (sale.order action_confirm)."""
    if not confirm:
        return safe(lambda: preview("action_confirm", "sale.order", ids=[order_id]))
    return safe(
        lambda: {
            "confirmed": get_client().execute_kw(
                "sale.order", "action_confirm", [[order_id]]
            )
        }
    )

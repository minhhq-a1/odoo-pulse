"""Write tools (create / update / delete) for the Odoo MCP server.

Every tool takes a ``confirm`` flag. With ``confirm=False`` (the default) the
tool returns a dry-run preview and performs no write. The actual write only
happens with ``confirm=True``, and even then it must clear the guard in
``OdooClient.execute_kw`` (read-only switch, allow-list, deny-list, delete gate).
"""

from __future__ import annotations

from ..core.errors import OdooConfigError
from ..mcp.app import mcp
from ..mcp.result import safe
from ..mcp.runtime import get_client
from ..services.writes import (
    confirm_sale_order as build_confirm_sale_order,
    create_contact as build_create_contact,
    create_lead as build_create_lead,
    create_record as build_create_record,
    create_task as build_create_task,
    delete_records as build_delete_records,
    update_records as build_update_records,
)


def _client_for(confirm: bool):
    if not confirm:
        try:
            return get_client()
        except OdooConfigError:
            return None
    return get_client()


@mcp.tool()
def create_record(model: str, values: dict, confirm: bool = False) -> str:
    """Create one record. Returns a preview unless confirm=True.

    Args:
        model: Odoo model name (must be in ODOO_WRITABLE_MODELS).
        values: Field -> value mapping for the new record.
        confirm: Set True to actually create; otherwise a dry-run preview.
    """
    return safe(
        lambda: build_create_record(
            _client_for(confirm), model=model, values=values, confirm=confirm
        )
    )


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
    return safe(
        lambda: build_update_records(
            _client_for(confirm), model=model, ids=ids, values=values, confirm=confirm
        )
    )


@mcp.tool()
def delete_records(model: str, ids: list[int], confirm: bool = False) -> str:
    """Delete one or more records. Returns a preview unless confirm=True.

    Deletes also require ODOO_ALLOW_DELETE=true on the server.

    Args:
        model: Odoo model name (must be in ODOO_WRITABLE_MODELS).
        ids: Record ids to delete.
        confirm: Set True to actually delete; otherwise a dry-run preview.
    """
    return safe(
        lambda: build_delete_records(
            _client_for(confirm), model=model, ids=ids, confirm=confirm
        )
    )


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
    return safe(
        lambda: build_create_lead(
            _client_for(confirm), name=name, contact_name=contact_name, email=email,
            phone=phone, description=description, extra_values=extra_values,
            confirm=confirm,
        )
    )


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
    return safe(
        lambda: build_create_contact(
            _client_for(confirm), name=name, email=email, phone=phone,
            is_company=is_company, parent_id=parent_id,
            extra_values=extra_values, confirm=confirm,
        )
    )


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
    return safe(
        lambda: build_create_task(
            _client_for(confirm), name=name, project_id=project_id, user_id=user_id,
            description=description, date_deadline=date_deadline,
            extra_values=extra_values, confirm=confirm,
        )
    )


@mcp.tool()
def confirm_sale_order(order_id: int, confirm: bool = False) -> str:
    """Confirm a quotation into a sales order (sale.order action_confirm)."""
    return safe(
        lambda: build_confirm_sale_order(
            _client_for(confirm), order_id=order_id, confirm=confirm
        )
    )

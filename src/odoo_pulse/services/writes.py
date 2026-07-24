from __future__ import annotations

from typing import Any

from ..core.errors import OdooError


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


def display_names(client: Any, model: str, ids: list[int]) -> list:
    rows = client.read(model, ids, fields=["display_name"])
    return [r.get("display_name") for r in rows]


def require_ids() -> None:
    raise OdooError("ids must be a non-empty list.")


def merge_extra(values: dict, extra_values: dict | None) -> dict:
    if extra_values:
        values.update(extra_values)
    return values


def create_record(client: Any, *, model: str, values: dict,
                  confirm: bool = False) -> dict:
    if not confirm:
        return preview("create", model, values=values)
    return {"created_id": client.create(model, values)}


def update_records(client: Any, *, model: str, ids: list[int], values: dict,
                   confirm: bool = False) -> dict:
    if not ids:
        require_ids()
    if not confirm:
        return preview(
            "update", model, ids=ids, values=values,
            affected=display_names(client, model, ids),
        )
    return {"updated": client.write(model, ids, values), "ids": ids}


def delete_records(client: Any, *, model: str, ids: list[int],
                   confirm: bool = False) -> dict:
    if not ids:
        require_ids()
    if not confirm:
        return preview(
            "delete", model, ids=ids,
            affected=display_names(client, model, ids),
        )
    return {"deleted": client.unlink(model, ids), "ids": ids}


def create_lead(client: Any, *, name: str, contact_name: str | None = None,
                email: str | None = None, phone: str | None = None,
                description: str | None = None,
                extra_values: dict | None = None,
                confirm: bool = False) -> dict:
    values: dict = {"name": name}
    if contact_name:
        values["contact_name"] = contact_name
    if email:
        values["email_from"] = email
    if phone:
        values["phone"] = phone
    if description:
        values["description"] = description
    values = merge_extra(values, extra_values)
    if not confirm:
        return preview("create", "crm.lead", values=values)
    return {"created_id": client.create("crm.lead", values)}


def create_contact(client: Any, *, name: str, email: str | None = None,
                   phone: str | None = None, is_company: bool = False,
                   parent_id: int | None = None,
                   extra_values: dict | None = None,
                   confirm: bool = False) -> dict:
    values: dict = {"name": name}
    if email:
        values["email"] = email
    if phone:
        values["phone"] = phone
    if is_company:
        values["is_company"] = True
    if parent_id:
        values["parent_id"] = parent_id
    values = merge_extra(values, extra_values)
    if not confirm:
        return preview("create", "res.partner", values=values)
    return {"created_id": client.create("res.partner", values)}


def create_task(client: Any, *, name: str, project_id: int,
                user_id: int | None = None,
                description: str | None = None,
                date_deadline: str | None = None,
                extra_values: dict | None = None,
                confirm: bool = False) -> dict:
    values: dict = {"name": name, "project_id": project_id}
    if user_id:
        values["user_ids"] = [(6, 0, [user_id])]
    if description:
        values["description"] = description
    if date_deadline:
        values["date_deadline"] = date_deadline
    values = merge_extra(values, extra_values)
    if not confirm:
        return preview("create", "project.task", values=values)
    return {"created_id": client.create("project.task", values)}


def confirm_sale_order(client: Any, *, order_id: int,
                       confirm: bool = False) -> dict:
    if not confirm:
        return preview("action_confirm", "sale.order", ids=[order_id])
    return {
        "confirmed": client.execute_kw(
            "sale.order", "action_confirm", [[order_id]]
        )
    }

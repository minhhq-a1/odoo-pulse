# odoo_pulse/common/schema.py
"""Schema-lookup primitives shared by tool modules.

Both helpers lean on the client's cached ``fields_get`` (caching stays
owned by ``core.client``; nothing here adds a second cache or a client
singleton).
"""

from __future__ import annotations

from typing import Any

from ..core.errors import OdooError


def ensure_field(client: Any, model: str, field: str, hint: str = "") -> None:
    """Raise OdooError when `field` is absent from `model`'s schema.

    Uses the client's cached fields_get, so the check costs nothing after
    the first call. Lets instance-specific fields (e.g. x_priority_score) fail
    with guidance instead of a raw Odoo fault.
    """
    if field not in client.fields_get(model):
        message = f"Field '{field}' does not exist on {model}."
        if hint:
            message += f" {hint}"
        raise OdooError(message)


def optional_fields(client: Any, model: str, candidates: list[str]) -> list[str]:
    """Subset of `candidates` that exist on `model`'s schema, in order.

    For fields that are custom (x_priority_score) or version-dependent
    (res.partner.mobile, removed in Odoo 19): list tools request them when
    available and silently degrade when not. Uses the cached fields_get,
    so the check is free after the first call per model.
    """
    schema = client.fields_get(model)
    return [f for f in candidates if f in schema]

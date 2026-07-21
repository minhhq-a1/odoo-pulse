# odoo_pulse/services/writes.py
"""Write-preview shaping.

Describes a write that WOULD happen, without performing it, so every write
tool can return the same dry-run struct by default. Write execution itself
stays in tools_write.py until Plan 4 folds it into a dedicated write-execution
service.
"""

from __future__ import annotations


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

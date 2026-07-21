# odoo_pulse/services/projects/queries.py
"""Read-only project-domain query helpers.

These orchestrate reads through an Odoo client (real or fake). They never
write. Keeping them here lets multiple composed tools (and standup_digest)
stay DRY and independently testable.
"""

from __future__ import annotations

from typing import Any


def resolve_user_names(client: Any, user_ids: Any) -> dict[int, str]:
    """Map res.users ids to names, including archived users.

    Returns {} and makes no call when there are no ids. De-duplicates ids.
    """
    ids = list({uid for uid in user_ids})
    if not ids:
        return {}
    users = client.execute_kw(
        "res.users",
        "search_read",
        [[("id", "in", ids)]],
        {"fields": ["id", "name"], "limit": len(ids), "context": {"active_test": False}},
    )
    return {u["id"]: u["name"] for u in users}

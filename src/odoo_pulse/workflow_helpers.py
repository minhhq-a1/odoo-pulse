# odoo_pulse/workflow_helpers.py
"""Shared building blocks for composed workflow tools.

These orchestrate reads through an Odoo client (real or fake) and shape the
common report envelope. They never write. Keeping them here lets multiple
composed tools (and standup_digest) stay DRY and independently testable.
"""

from __future__ import annotations

from typing import Any


CLOSED_TASK_STATES = ("1_done", "1_canceled")


def task_closed_scope(
    client: Any, *, closed: bool, stage_names: list[str]
) -> tuple[list, list[str], str]:
    """Return server domain, extra fields, and stable/fallback strategy."""
    schema = client.fields_get("project.task")
    if "state" in schema:
        operator = "in" if closed else "not in"
        return [(
            "state", operator, list(CLOSED_TASK_STATES))], ["state"], "state"
    if "is_closed" in schema:
        return [], ["is_closed"], "is_closed"
    operator = "in" if closed else "not in"
    return [("stage_id.name", operator, stage_names)], [], "stage"


def task_matches_scope(
    task: dict,
    strategy: str,
    *,
    closed: bool,
    stage_names: list[str],
) -> bool:
    if strategy == "state":
        is_closed = task.get("state") in CLOSED_TASK_STATES
    elif strategy == "is_closed":
        is_closed = bool(task.get("is_closed"))
    else:
        stage = task.get("stage_id")
        name = stage[1].casefold() if stage else ""
        is_closed = name in {value.casefold() for value in stage_names}
    return is_closed if closed else not is_closed


def task_scope_warning(strategy: str) -> str | None:
    if strategy == "is_closed":
        return "project.task.state unavailable; is_closed filtered client-side"
    if strategy == "stage":
        return "stable task state unavailable; stage-name fallback applied"
    return None


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

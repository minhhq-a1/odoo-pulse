# odoo_mcp/workflow_helpers.py
"""Shared building blocks for composed workflow tools.

These orchestrate reads through an Odoo client (real or fake) and shape the
common report envelope. They never write. Keeping them here lets multiple
composed tools (and standup_digest) stay DRY and independently testable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any


def today_in_tz(timezone_offset: int) -> date:
    """Current calendar date at a fixed UTC offset (default team tz is +7)."""
    tz = timezone(timedelta(hours=timezone_offset))
    return datetime.now(tz).date()


def parse_deadline(raw: Any) -> date | None:
    """Parse Odoo's 'YYYY-MM-DD[ HH:MM:SS]' (or false) into a date, or None."""
    if not raw:
        return None
    return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()


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


def _as_of_str(as_of: Any) -> str:
    return as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)


def build_report(
    tool: str,
    as_of: Any,
    summary: dict,
    breakdown: dict | None = None,
    highlights: list[str] | None = None,
    risks: list[dict] | None = None,
    extra: dict | None = None,
) -> dict:
    """Assemble the composed-tool envelope with a stable key order.

    Order: tool, as_of, <extra keys>, summary, breakdown, highlights, risks.
    """
    report: dict[str, Any] = {"tool": tool, "as_of": _as_of_str(as_of)}
    if extra:
        report.update(extra)
    report["summary"] = summary
    report["breakdown"] = breakdown or {}
    report["highlights"] = highlights or []
    report["risks"] = risks or []
    return report

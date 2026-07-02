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


def fetch_with_truncation(
    client: Any,
    model: str,
    domain: list,
    fields: list[str],
    limit: int,
    order: str | None = None,
) -> tuple[list[dict], dict | None]:
    """search_read that also detects silent truncation against the row cap.

    ``client.search_read`` caps every call at ``min(limit, config.max_records)``.
    When the fetched row count lands exactly on that cap, more matching rows
    may exist server-side and a composed report built only from the fetched
    rows would silently cover a subset. This mirrors the client's own capping
    logic (rather than reaching into the private ``_cap_limit``) and issues
    one extra ``search_count`` only when the cap was actually hit.

    Returns ``(rows, None)`` when the result set is known-complete, or
    ``(rows, {"total_matching", "fetched", "missing"})`` when it's truncated.
    """
    effective_limit = client.config.max_records
    if limit and 0 < limit <= effective_limit:
        effective_limit = limit

    rows = client.search_read(model, domain=domain, fields=fields, limit=limit, order=order)
    if len(rows) != effective_limit:
        return rows, None

    total = client.search_count(model, domain)
    if total <= len(rows):
        return rows, None

    return rows, {
        "total_matching": total,
        "fetched": len(rows),
        "missing": total - len(rows),
    }


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

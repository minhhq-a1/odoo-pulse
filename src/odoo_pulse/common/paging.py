# odoo_pulse/common/paging.py
"""Bounded-read primitives shared by report and workflow tools.

These orchestrate reads through an Odoo client (real or fake) and detect
or avoid silent truncation against the row cap. They never write.
"""

from __future__ import annotations

from typing import Any

from ..core.errors import OdooError


def fetch_with_truncation(
    client: Any,
    model: str,
    domain: list,
    fields: list[str],
    limit: int,
    order: str | None = None,
    context: dict | None = None,
) -> tuple[list[dict], dict | None]:
    """search_read that also detects silent truncation against the row cap.

    ``client.search_read`` caps every call at ``min(limit, config.max_records)``.
    When the fetched row count lands exactly on that cap, more matching rows
    may exist server-side and a composed report built only from the fetched
    rows would silently cover a subset. This mirrors the client's own capping
    logic (rather than reaching into the private ``_cap_limit``) and issues
    one extra ``search_count`` only when the cap was actually hit.

    ``context`` is forwarded to search_read (not to the truncation search_count;
    the count may be unscoped in the rare capped case).

    Returns ``(rows, None)`` when the result set is known-complete, or
    ``(rows, {"total_matching", "fetched", "missing"})`` when it's truncated.
    """
    effective_limit = client.config.max_records
    if limit and 0 < limit <= effective_limit:
        effective_limit = limit

    rows = client.search_read(
        model, domain=domain, fields=fields, limit=limit, order=order, context=context
    )
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


def paged_search_read(
    client: Any,
    model: str,
    domain: list,
    fields: list[str],
    page: int = 500,
    max_pages: int = 50,
    order: str = "id",
) -> list[dict]:
    """Fetch every matching row with stable, bounded offset pagination."""
    step = min(page, client.config.max_records)
    if step <= 0:
        raise OdooError(
            f"{model}: pagination requires a positive page size, got {step}")
    rows: list[dict] = []
    for index in range(max_pages):
        batch = client.search_read(
            model,
            domain=domain,
            fields=fields,
            limit=step,
            offset=index * step,
            order=order,
        )
        rows.extend(batch)
        if len(batch) < step:
            return rows
    raise OdooError(
        f"{model}: more than {max_pages * step} rows match; narrow the filters.")

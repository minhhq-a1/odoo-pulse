# odoo_pulse/workflow_helpers.py
"""Shared building blocks for composed workflow tools.

These orchestrate reads through an Odoo client (real or fake) and shape the
common report envelope. They never write. Keeping them here lets multiple
composed tools (and standup_digest) stay DRY and independently testable.
"""

from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Any

from .odoo_client import OdooError


def today_in_tz(timezone_offset: int) -> date:
    """Current calendar date at a fixed UTC offset (default team tz is +7)."""
    tz = timezone(timedelta(hours=timezone_offset))
    return datetime.now(tz).date()


def parse_when(raw: Any, timezone_offset: int = 0) -> date | None:
    """Parse an Odoo date ('YYYY-MM-DD') or UTC datetime
    ('YYYY-MM-DD HH:MM:SS') into the calendar date at the given UTC offset.

    Datetime values are shifted by timezone_offset hours before taking the
    date; plain date values pass through unshifted. Falsy input -> None.
    """
    if not raw:
        return None
    s = str(raw)
    if len(s) <= 10:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    return (dt + timedelta(hours=timezone_offset)).date()


def utc_bound(day: date, timezone_offset: int) -> str:
    """Local midnight of `day` at the given UTC offset, expressed as a UTC
    datetime string suitable for domain comparisons on datetime fields."""
    dt = datetime.combine(day, dt_time.min) - timedelta(hours=timezone_offset)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


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


def resolve_company_id(client: Any, company: Any) -> int | None:
    """Resolve a company name (ilike) or id to a res.company id.

    None/empty means "no company filter". Raises OdooError when a name
    matches zero or more than one company, so a typo fails loudly instead
    of silently reporting on the wrong entity.
    """
    if company is None or company == "":
        return None
    if isinstance(company, int):
        return company
    rows = client.search_read(
        "res.company",
        domain=[("name", "ilike", str(company))],
        fields=["id", "name"],
        limit=2,
    )
    if not rows:
        raise OdooError(f"No company matching {company!r}")
    if len(rows) > 1:
        names = ", ".join(r["name"] for r in rows)
        raise OdooError(f"Ambiguous company {company!r}: matches {names}")
    return rows[0]["id"]


def distinct_companies(rows: list[dict]) -> list[str]:
    """Sorted company names appearing in rows that carry a company_id m2o."""
    return sorted({row["company_id"][1] for row in rows if row.get("company_id")})


def totals_by_currency(
    rows: list[dict], amount_field: str, currency_field: str = "currency_id"
) -> dict[str, float]:
    """Sum amount_field per currency name. Falsy currency -> '(unknown)'."""
    totals: dict[str, float] = {}
    for row in rows:
        cur = row.get(currency_field)
        name = cur[1] if cur else "(unknown)"
        totals[name] = totals.get(name, 0.0) + (row.get(amount_field) or 0.0)
    return {name: round(value, 2) for name, value in totals.items()}


def trend_direction(values: list[float], threshold_pct: float = 10.0) -> str:
    """Classify a chronological series: improving / declining / flat.

    Compares the mean of the newer half against the older half; deltas
    within +/- threshold_pct count as flat. Fewer than 4 points is flat
    (not enough signal to call a direction).
    """
    if len(values) < 4:
        return "flat"
    half = len(values) // 2
    old_avg = sum(values[:half]) / half
    new_avg = sum(values[-half:]) / half
    if old_avg == 0:
        return "improving" if new_avg > 0 else "flat"
    delta = (new_avg - old_avg) / old_avg * 100
    if delta >= threshold_pct:
        return "improving"
    if delta <= -threshold_pct:
        return "declining"
    return "flat"


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

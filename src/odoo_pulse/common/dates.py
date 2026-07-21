# odoo_pulse/common/dates.py
"""Date parsing and domain-building primitives shared across tool modules.

Two strict YYYY-MM-DD parsers exist here on purpose:
- ``parse_date_parameter``: a tool call's date_from/date_to -- surrounding
  whitespace is invalid, since these come straight off an MCP call.
- ``parse_period_date``: a periods[i].date_from/date_to value -- trims
  surrounding whitespace before parsing (periods are nested dicts, not raw
  tool parameters).
Do not merge or swap them.
"""

from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Any

from ..core.errors import OdooError


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


def parse_date_parameter(raw: str, parameter: str) -> date:
    """Strict YYYY-MM-DD tool parameter; surrounding whitespace is invalid."""
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise OdooError(f"Invalid {parameter} {raw!r}: expected YYYY-MM-DD")


def parse_period_date(value: Any, parameter: str) -> date:
    """Strict YYYY-MM-DD period value after trimming surrounding whitespace."""
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise OdooError(f"Invalid {parameter} {value!r}: expected YYYY-MM-DD")


def date_domain(
    field: str,
    date_from: str | None,
    date_to: str | None,
    *,
    as_datetime: bool = False,
) -> list:
    """Build an inclusive user-facing date range for Date or Datetime."""
    domain: list = []
    if date_from:
        start = parse_date_parameter(date_from, "date_from")
        domain.append((field, ">=", start.isoformat()))
    if date_to:
        end = parse_date_parameter(date_to, "date_to")
        if as_datetime:
            domain.append((field, "<", (end + timedelta(days=1)).isoformat()))
        else:
            domain.append((field, "<=", end.isoformat()))
    return domain


def periods_domain(
    field: str,
    periods: list[dict] | None,
    timezone_offset: int,
    as_datetime: bool = True,
) -> list:
    """OR-of-closed-ranges domain on `field` (spec: OR between periods,
    NOT a union — gaps between non-adjacent budgets stay excluded).

    as_datetime=True: bounds are local 00:00:00 / 23:59:59 at
    timezone_offset, converted to UTC datetime strings. False: plain
    YYYY-MM-DD strings for date (not datetime) fields.
    """
    subs: list[list] = []
    for i, period in enumerate(periods or []):
        d_from = (period or {}).get("date_from")
        d_to = (period or {}).get("date_to")
        if not d_from and not d_to:
            raise OdooError(
                f"periods[{i}] needs date_from and/or date_to")
        leaves: list = []
        if d_from:
            day = parse_period_date(d_from, f"periods[{i}].date_from")
            low = (utc_bound(day, timezone_offset)
                   if as_datetime else day.isoformat())
            leaves.append((field, ">=", low))
        if d_to:
            day = parse_period_date(d_to, f"periods[{i}].date_to")
            if as_datetime:
                high = (datetime.combine(day, dt_time(23, 59, 59))
                        - timedelta(hours=timezone_offset)
                        ).strftime("%Y-%m-%d %H:%M:%S")
            else:
                high = day.isoformat()
            leaves.append((field, "<=", high))
        subs.append(leaves)
    if not subs:
        return []
    if len(subs) == 1:
        return subs[0]
    out: list = ["|"] * (len(subs) - 1)
    for leaves in subs:
        if len(leaves) == 2:
            out.append("&")
        out.extend(leaves)
    return out

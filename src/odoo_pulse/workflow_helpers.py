# odoo_pulse/workflow_helpers.py
"""Shared building blocks for composed workflow tools.

These orchestrate reads through an Odoo client (real or fake) and shape the
common report envelope. They never write. Keeping them here lets multiple
composed tools (and standup_digest) stay DRY and independently testable.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .core.errors import OdooError


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


def gather(
    thunks: dict[str, Callable[[], Any]], max_workers: int = 8
) -> dict[str, Any]:
    """Run independent zero-arg callables concurrently, one thread each.

    Returns {key: outcome} in the input's key order; outcome is the
    callable's return value or the exception instance it raised. The caller
    decides per key whether an exception is fatal (re-raise) or a degraded
    section (business_pulse). Safe over one OdooClient: it builds a fresh
    XML-RPC proxy per call and its caches are lock-guarded. A single thunk
    runs inline — no thread overhead for the trivial case.
    """

    def call(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as exc:  # captured; caller chooses to re-raise
            return exc

    if len(thunks) <= 1:
        return {key: call(fn) for key, fn in thunks.items()}
    with ThreadPoolExecutor(max_workers=min(len(thunks), max_workers)) as pool:
        futures = {key: pool.submit(call, fn) for key, fn in thunks.items()}
        return {key: futures[key].result() for key in thunks}


def gather_strict(
    thunks: dict[str, Callable[[], Any]], max_workers: int = 8
) -> dict[str, Any]:
    """:func:`gather` for callers where any failure is fatal.

    Re-raises the first exception in key order instead of returning it —
    the composed report tools want a single OdooError to surface through
    ``safe()`` exactly as it would have sequentially.
    """
    results = gather(thunks, max_workers)
    for outcome in results.values():
        if isinstance(outcome, Exception):
            raise outcome
    return results

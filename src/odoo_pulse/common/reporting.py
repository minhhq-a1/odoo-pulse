# odoo_pulse/common/reporting.py
"""Reporting primitives shared by composed report/workflow tools.

These orchestrate reads through an Odoo client (real or fake) and shape the
common report envelope. They never write.
"""

from __future__ import annotations

from typing import Any

from ..core.errors import OdooError


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

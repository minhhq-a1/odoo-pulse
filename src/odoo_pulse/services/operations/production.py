"""Production health report service."""

from __future__ import annotations

from ...common.dates import parse_when
from ...common.paging import fetch_with_truncation
from ...common.reporting import build_report
from ..report_context import build_report_context


def build_production_health(
    client,
    *,
    stuck_days: int = 14,
    top_n: int = 5,
    timezone_offset: int = 7,
    company: str | int | None = None,
) -> dict:
    context = build_report_context(
        client, timezone_offset=timezone_offset, company=company
    )
    today = context.today
    company_domain = list(context.company_domain)

    orders, truncation = fetch_with_truncation(
        client, "mrp.production",
        [("state", "in", ["confirmed", "progress", "to_close"]),
         *company_domain],
        fields=["id", "name", "product_id", "product_qty", "state",
                "date_start", "date_finished"],
        limit=200, order="date_start",
    )

    by_state: dict[str, int] = {}
    behind: list[dict] = []
    stuck: list[dict] = []
    for mo in orders:
        state = mo.get("state") or "(unknown)"
        by_state[state] = by_state.get(state, 0) + 1
        product = mo["product_id"][1] if mo.get("product_id") else "(none)"
        start = parse_when(mo.get("date_start"), timezone_offset)
        if state == "confirmed" and start is not None and start < today:
            behind.append({
                "mo": mo["name"], "product": product,
                "qty": mo.get("product_qty") or 0.0,
                "planned_start": mo.get("date_start"),
                "days_behind": (today - start).days,
            })
        elif (state in ("progress", "to_close") and start is not None
              and (today - start).days > stuck_days):
            stuck.append({
                "mo": mo["name"], "product": product,
                "qty": mo.get("product_qty") or 0.0,
                "started": mo.get("date_start"),
                "running_days": (today - start).days,
            })
    behind.sort(key=lambda r: -r["days_behind"])
    stuck.sort(key=lambda r: -r["running_days"])

    if behind:
        verdict = "action_needed"
    elif stuck:
        verdict = "watch"
    else:
        verdict = "healthy"

    summary = {
        "open_orders": len(orders),
        "behind_start": len(behind),
        "stuck_in_progress": len(stuck),
        "verdict": verdict,
    }
    if truncation:
        summary["truncated"] = True
        summary["total_matching"] = truncation["total_matching"]

    highlights = [f"{len(orders)} open manufacturing order(s)"]
    if behind:
        worst = behind[0]
        highlights.append(
            f"{worst['mo']} ({worst['product']}) is {worst['days_behind']} "
            "day(s) past its planned start")
    if stuck:
        worst = stuck[0]
        highlights.append(
            f"{worst['mo']} has been running {worst['running_days']} day(s)")
    if verdict == "healthy":
        highlights.append("no late starts or stuck orders detected")

    risks: list[dict] = []
    if truncation:
        risks.append({
            "code": "truncated_data", "count": truncation["missing"],
            "message": (
                f"Report covers only {truncation['fetched']} of "
                f"{truncation['total_matching']} matching orders."),
        })
    if behind:
        risks.append({
            "code": "behind_start", "count": len(behind),
            "message": (f"{len(behind)} order(s) past their planned start "
                        "and not yet in progress"),
        })
    if stuck:
        risks.append({
            "code": "stuck_in_progress", "count": len(stuck),
            "message": (f"{len(stuck)} order(s) in progress for more than "
                        f"{stuck_days} days"),
        })

    return build_report(
        "production_health", today,
        summary=summary,
        breakdown={"by_state": by_state, "behind_start": behind[:top_n],
                   "stuck_in_progress": stuck[:top_n]},
        highlights=highlights, risks=risks,
        extra={"stuck_days": stuck_days, "company": company},
    )

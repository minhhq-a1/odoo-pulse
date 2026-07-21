# odoo_pulse/tools_reports_finance.py
"""Finance report tools: AR/AP aging and who owes what.

Same composition style as tools_workflows: bounded reads shaped into the
build_report envelope with a rule-based verdict. Read-only.
"""

from __future__ import annotations

from .common.dates import parse_when, today_in_tz
from .common.paging import fetch_with_truncation
from .mcp.app import mcp
from .mcp.result import safe
from .mcp.runtime import get_client
from .workflow_helpers import (
    build_report,
    resolve_company_id,
    totals_by_currency,
)


@mcp.tool()
def receivables_health(
    top_n: int = 5,
    timezone_offset: int = 7,
    company: str | int | None = None,
    overdue_pct_at_risk: float = 25.0,
    overdue_pct_off_track: float = 50.0,
) -> str:
    """Report AR/AP aging and who owes what, in one call.

    Composes open posted invoices and vendor bills into standard aging
    buckets (not_due / 1-30 / 31-60 / 61-90 / 90+), the share of
    receivables overdue, the top overdue customers, and a verdict.

    Args:
        top_n: Rows in the top-overdue-customers list (default 5).
        timezone_offset: UTC offset for "today" (default 7 = Asia/Ho_Chi_Minh).
        company: Optional company name (ilike) or id to scope the report.
        overdue_pct_at_risk: Overdue AR share (%) that drops the verdict
            to at_risk (default 25).
        overdue_pct_off_track: Overdue AR share (%) that drops the verdict
            to off_track (default 50).
    """

    def run() -> dict:
        client = get_client()
        today = today_in_tz(timezone_offset)

        company_id = resolve_company_id(client, company)
        company_domain: list = (
            [("company_id", "=", company_id)] if company_id else [])

        invoices, truncation = fetch_with_truncation(
            client, "account.move",
            [("move_type", "in", ["out_invoice", "in_invoice"]),
             ("state", "=", "posted"),
             ("payment_state", "in", ["not_paid", "partial"]),
             *company_domain],
            fields=["id", "name", "partner_id", "amount_residual",
                    "invoice_date_due", "move_type", "currency_id"],
            limit=200, order="invoice_date_due",
        )

        buckets = ("not_due", "1-30", "31-60", "61-90", "90+")
        aging = {"receivable": dict.fromkeys(buckets, 0.0),
                 "payable": dict.fromkeys(buckets, 0.0)}
        overdue_customers: dict[str, float] = {}
        ar_rows: list[dict] = []
        ar_total = ar_overdue = ap_total = 0.0
        ar_count = ap_count = ninety_plus_count = 0

        for inv in invoices:
            residual = inv.get("amount_residual") or 0.0
            side = "receivable" if inv["move_type"] == "out_invoice" else "payable"
            due = parse_when(inv.get("invoice_date_due"), timezone_offset)
            days = (today - due).days if due else 0
            if days <= 0:
                bucket = "not_due"
            elif days <= 30:
                bucket = "1-30"
            elif days <= 60:
                bucket = "31-60"
            elif days <= 90:
                bucket = "61-90"
            else:
                bucket = "90+"
            aging[side][bucket] += residual

            if side == "receivable":
                ar_count += 1
                ar_total += residual
                ar_rows.append(inv)
                if bucket == "90+":
                    ninety_plus_count += 1
                if days > 0:
                    ar_overdue += residual
                    partner = (inv["partner_id"][1]
                               if inv.get("partner_id") else "(unknown)")
                    overdue_customers[partner] = (
                        overdue_customers.get(partner, 0.0) + residual)
            else:
                ap_count += 1
                ap_total += residual

        for side in aging:
            aging[side] = {b: round(v, 2) for b, v in aging[side].items()}

        pct_overdue = round(ar_overdue / ar_total * 100, 1) if ar_total else 0.0
        ninety_plus = aging["receivable"]["90+"]

        if pct_overdue >= overdue_pct_off_track:
            verdict = "off_track"
        elif pct_overdue >= overdue_pct_at_risk or ninety_plus > 0:
            verdict = "at_risk"
        else:
            verdict = "on_track"

        top_debtors = sorted(
            ({"customer": k, "overdue_amount": round(v, 2)}
             for k, v in overdue_customers.items()),
            key=lambda r: -r["overdue_amount"],
        )[:top_n]

        summary = {
            "receivable_open": ar_count,
            "receivable_total": round(ar_total, 2),
            "receivable_overdue": round(ar_overdue, 2),
            "pct_overdue": pct_overdue,
            "payable_open": ap_count,
            "payable_total": round(ap_total, 2),
            "verdict": verdict,
        }
        if truncation:
            summary["truncated"] = True
            summary["total_matching"] = truncation["total_matching"]

        by_currency = totals_by_currency(ar_rows, "amount_residual")
        if len(by_currency) == 1:
            summary["currency"] = next(iter(by_currency))
        elif len(by_currency) > 1:
            summary["by_currency"] = by_currency

        highlights = [
            f"{round(ar_total, 2)} receivable across {ar_count} invoice(s), "
            f"{pct_overdue}% overdue"
        ]
        if top_debtors:
            highlights.append(
                f"largest overdue: {top_debtors[0]['customer']} "
                f"({top_debtors[0]['overdue_amount']})")

        risks: list[dict] = []
        if truncation:
            risks.append({
                "code": "truncated_data", "count": truncation["missing"],
                "message": (
                    f"Report covers only {truncation['fetched']} of "
                    f"{truncation['total_matching']} matching invoices."
                ),
            })
        if ar_overdue > 0:
            risks.append({
                "code": "overdue_receivables", "count": len(overdue_customers),
                "message": (f"{round(ar_overdue, 2)} overdue across "
                            f"{len(overdue_customers)} customer(s)"),
            })
        if ninety_plus > 0:
            risks.append({
                "code": "aged_over_90", "count": ninety_plus_count,
                "message": (f"{ninety_plus_count} receivable(s) totaling "
                            f"{ninety_plus} are 90+ days overdue"),
            })
        if len(by_currency) > 1:
            risks.append({
                "code": "mixed_currencies", "count": len(by_currency),
                "message": (
                    "Receivable totals and aging buckets mix currencies "
                    f"({', '.join(sorted(by_currency))}); read by_currency "
                    "or pass company= to scope."),
            })

        return build_report(
            "receivables_health", today,
            summary=summary,
            breakdown={"aging": aging, "top_overdue_customers": top_debtors},
            highlights=highlights, risks=risks,
            extra={"company": company,
                   "thresholds": {"overdue_pct_at_risk": overdue_pct_at_risk,
                                  "overdue_pct_off_track": overdue_pct_off_track}},
        )

    return safe(run)

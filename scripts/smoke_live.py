#!/usr/bin/env python3
"""Live smoke test against a *real* Odoo instance.

Unlike the pytest suite (which mocks XML-RPC), this script actually connects to
Odoo using the credentials in your environment / .env file and calls every
read-only tool once - the default surface (Generic, Reports, Reports-Ops,
Workflows) plus the opt-in breadth wrappers (Core/HR/Project/Operations/
Engagement/Niche) - reporting OK / not-installed / needs-attention for each.
It is the fastest way to confirm a real connection works and to catch
field-name or aggregate-key-shape mismatches on a specific Odoo version.

Usage:
    cp .env.example .env      # fill in your ODOO_* credentials
    python scripts/smoke_live.py
    python scripts/smoke_live.py --env /path/to/.env --limit 1

It stays read-only and never creates/updates/deletes anything.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Allow running as a plain script (python scripts/smoke_live.py) by making the
# repo root importable, since sys.path[0] would otherwise be scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_env(path: Path) -> None:
    """Minimal .env loader (does not override already-set variables)."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


# Terminal colours (disabled when output is not a TTY).
class C:
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def _plain() -> None:
    for name in ("GREEN", "YELLOW", "RED", "DIM", "BOLD", "RESET"):
        setattr(C, name, "")


def _read_records_probe(model: str = "res.partner", **_ignored) -> str:
    """read_records has no discovery path of its own, so look up one real id
    via search_read first. display_name is present on every model, so this
    stays generic instead of hard-coding a model-specific field."""
    from odoo_pulse import tools_generic

    probe = json.loads(
        tools_generic.search_read(model=model, domain=[], fields=["id"], limit=1)
    )
    ids = [probe[0]["id"]] if isinstance(probe, list) and probe else [1]
    return tools_generic.read_records(model=model, ids=ids, fields=["id", "display_name"])


# Tools whose *success* contract is plain text/markdown rather than JSON
# (only their error path is JSON). Handled specially in main()'s result parsing.
TEXT_RESULT_TOOLS = {"standup_digest"}


def build_cases(limit: int):
    """(group, label, callable, kwargs) for every read-only tool in the
    default (core, reports) surface plus the opt-in breadth wrappers."""
    from odoo_pulse import (
        domain_tools,
        tools_engagement,
        tools_generic,
        tools_hr,
        tools_niche,
        tools_operations,
        tools_projects,
        tools_reports_finance,
        tools_reports_hr,
        tools_reports_inventory,
        tools_reports_ops,
        tools_reports_pulse,
        tools_reports_sales,
        tools_workflows,
    )

    return [
        # group, label, func, kwargs
        # --- Generic (core group) ---
        ("Generic", "list_models", tools_generic.list_models, {"name_filter": "sale"}),
        (
            "Generic",
            "get_model_fields",
            tools_generic.get_model_fields,
            {"model": "res.partner", "fields": ["name", "email"]},
        ),
        (
            "Generic",
            "search_read",
            tools_generic.search_read,
            {"model": "res.partner", "domain": [], "fields": ["id", "name"], "limit": limit},
        ),
        (
            "Generic",
            "search_count",
            tools_generic.search_count,
            {"model": "res.partner", "domain": []},
        ),
        ("Generic", "read_records", _read_records_probe, {"model": "res.partner"}),
        (
            "Generic",
            "aggregate_records (ir.attachment)",
            tools_generic.aggregate_records,
            {
                # ir.attachment always exists (base model) and always holds
                # rows even on a fresh DB (web assets), so the key contract
                # (spec keys + __count) is verified against real rows on any
                # instance - business models may legitimately be empty.
                "model": "ir.attachment",
                "group_by": ["res_model"],
                "measures": ["file_size:sum"],
                "limit": limit,
            },
        ),
        # --- Reports (reports group) ---
        ("Reports", "pipeline_review", tools_reports_sales.pipeline_review, {}),
        ("Reports", "sales_snapshot", tools_reports_sales.sales_snapshot, {}),
        ("Reports", "receivables_health", tools_reports_finance.receivables_health, {}),
        ("Reports", "inventory_risk", tools_reports_inventory.inventory_risk, {}),
        ("Reports", "absence_overview", tools_reports_hr.absence_overview, {}),
        ("Reports", "business_pulse", tools_reports_pulse.business_pulse, {}),
        # --- Reports-Ops (reports group) ---
        ("Reports-Ops", "procurement_watch", tools_reports_ops.procurement_watch, {}),
        ("Reports-Ops", "production_health", tools_reports_ops.production_health, {}),
        # --- Workflows (reports group) ---
        ("Workflows", "team_workload", tools_workflows.team_workload, {}),
        ("Workflows", "project_status_report", tools_workflows.project_status_report, {}),
        ("Workflows", "standup_digest", tools_workflows.standup_digest, {"project": "a"}),
        # --- Core (business group, opt-in breadth wrapper) ---
        ("Core", "find_partner", domain_tools.find_partner, {"query": "a", "limit": limit}),
        ("Core", "list_opportunities", domain_tools.list_opportunities, {"limit": limit}),
        ("Core", "list_sale_orders", domain_tools.list_sale_orders, {"limit": limit}),
        ("Core", "list_purchase_orders", domain_tools.list_purchase_orders, {"limit": limit}),
        ("Core", "find_products", domain_tools.find_products, {"limit": limit}),
        ("Core", "check_stock", domain_tools.check_stock, {"product_query": "a", "limit": limit}),
        ("Core", "list_invoices", domain_tools.list_invoices, {"limit": limit}),
        ("Core", "list_payments", domain_tools.list_payments, {"limit": limit}),
        ("Core", "list_pickings", domain_tools.list_pickings, {"limit": limit}),
        ("HR", "list_employees", tools_hr.list_employees, {"limit": limit}),
        ("HR", "list_departments", tools_hr.list_departments, {"limit": limit}),
        ("HR", "list_time_off", tools_hr.list_time_off, {"limit": limit}),
        ("HR", "list_expenses", tools_hr.list_expenses, {"limit": limit}),
        ("HR", "list_job_positions", tools_hr.list_job_positions, {"limit": limit}),
        ("HR", "list_applicants", tools_hr.list_applicants, {"limit": limit}),
        ("HR", "list_attendances", tools_hr.list_attendances, {"limit": limit}),
        ("Project", "list_projects", tools_projects.list_projects, {"limit": limit}),
        ("Project", "list_tasks", tools_projects.list_tasks, {"limit": limit}),
        ("Project", "list_timesheets", tools_projects.list_timesheets, {"limit": limit}),
        (
            "Operations",
            "list_manufacturing_orders",
            tools_operations.list_manufacturing_orders,
            {"limit": limit},
        ),
        ("Operations", "list_boms", tools_operations.list_boms, {"limit": limit}),
        ("Operations", "list_pos_orders", tools_operations.list_pos_orders, {"limit": limit}),
        ("Operations", "list_pos_sessions", tools_operations.list_pos_sessions, {"limit": limit}),
        ("Operations", "list_repair_orders", tools_operations.list_repair_orders, {"limit": limit}),
        (
            "Operations",
            "list_maintenance_requests",
            tools_operations.list_maintenance_requests,
            {"limit": limit},
        ),
        ("Operations", "list_equipment", tools_operations.list_equipment, {"limit": limit}),
        (
            "Operations",
            "list_helpdesk_tickets",
            tools_operations.list_helpdesk_tickets,
            {"limit": limit},
        ),
        ("Operations", "list_vehicles", tools_operations.list_vehicles, {"limit": limit}),
        ("Engagement", "list_events", tools_engagement.list_events, {"limit": limit}),
        (
            "Engagement",
            "list_event_registrations",
            tools_engagement.list_event_registrations,
            {"limit": limit},
        ),
        (
            "Engagement",
            "list_calendar_events",
            tools_engagement.list_calendar_events,
            {"limit": limit},
        ),
        ("Engagement", "list_activities", tools_engagement.list_activities, {"limit": limit}),
        ("Engagement", "list_surveys", tools_engagement.list_surveys, {"limit": limit}),
        (
            "Engagement",
            "list_email_campaigns",
            tools_engagement.list_email_campaigns,
            {"limit": limit},
        ),
        ("Niche", "list_subscriptions", tools_niche.list_subscriptions, {"limit": limit}),
        ("Niche", "list_sign_requests", tools_niche.list_sign_requests, {"limit": limit}),
        ("Niche", "list_documents", tools_niche.list_documents, {"limit": limit}),
        (
            "Niche",
            "list_knowledge_articles",
            tools_niche.list_knowledge_articles,
            {"limit": limit},
        ),
        (
            "Niche",
            "list_approval_requests",
            tools_niche.list_approval_requests,
            {"limit": limit},
        ),
        ("Niche", "list_lunch_orders", tools_niche.list_lunch_orders, {"limit": limit}),
        ("Niche", "list_quality_checks", tools_niche.list_quality_checks, {"limit": limit}),
        ("Niche", "list_quality_alerts", tools_niche.list_quality_alerts, {"limit": limit}),
        ("Niche", "list_planning_slots", tools_niche.list_planning_slots, {"limit": limit}),
        ("Niche", "list_courses", tools_niche.list_courses, {"limit": limit}),
        ("Niche", "list_loyalty_programs", tools_niche.list_loyalty_programs, {"limit": limit}),
        ("Niche", "list_loyalty_cards", tools_niche.list_loyalty_cards, {"limit": limit}),
        ("Niche", "list_memberships", tools_niche.list_memberships, {"limit": limit}),
        ("Niche", "list_payslips", tools_niche.list_payslips, {"limit": limit}),
        ("Niche", "list_appraisals", tools_niche.list_appraisals, {"limit": limit}),
        ("Niche", "list_social_posts", tools_niche.list_social_posts, {"limit": limit}),
        ("Niche", "list_website_visitors", tools_niche.list_website_visitors, {"limit": limit}),
        (
            "Niche",
            "list_engineering_changes",
            tools_niche.list_engineering_changes,
            {"limit": limit},
        ),
        ("Niche", "list_iot_devices", tools_niche.list_iot_devices, {"limit": limit}),
        ("Niche", "list_notes", tools_niche.list_notes, {"limit": limit}),
    ]


# Heuristic: tell "app not installed" apart from a real schema problem.
_NOT_INSTALLED_HINTS = ("doesn't exist", "does not exist", "object ", "invalid model")


# Deliberately strict: "Invalid field" stays CHECK, never skip - that is
# exactly how the res.partner.mobile removal on Odoo 19 was caught. Tools
# that can miss fields legitimately must degrade in the tool itself
# (optional_fields / ensure_field), not be masked here.
def classify_error(message: str) -> str:
    low = message.lower()
    if any(hint in low for hint in _NOT_INSTALLED_HINTS):
        return "skip"  # app not installed - expected
    return "attention"  # likely a field-name mismatch worth fixing


def describe_result(data) -> str:
    """Short human-readable summary of a successful tool result.

    List-style tools return a bare list of records. aggregate_records and the
    report/workflow tools return a dict; surface their row_count/verdict
    instead of the misleading "1 record(s)" a flat len() would give.
    """
    if isinstance(data, list):
        return f"{len(data)} record(s)"
    if isinstance(data, dict):
        if "row_count" in data:
            return f"{data['row_count']} group(s), method={data.get('method')}"
        verdict = data.get("summary", {}).get("verdict") if isinstance(data.get("summary"), dict) else None
        if verdict:
            return f"verdict={verdict}"
        if "summary" in data:
            return "report ok"
    return "1 record(s)"


def check_aggregate_contract(data) -> str | None:
    """Verify the aggregate_records key contract against real rows.

    Every row must carry each requested '<field>:<agg>' spec key plus
    '__count', on BOTH dispatch paths (legacy read_group is normalised
    client-side; formatted_read_group requests __count explicitly). With
    zero rows the contract cannot be verified, which must not silently
    count as a pass.

    Returns a problem description, or None when the contract holds.
    """
    if not (isinstance(data, dict) and "row_count" in data):
        return None
    if data["row_count"] == 0:
        return "no rows - key contract UNVERIFIED; point the probe at a model with data"
    row = data["rows"][0]
    missing = [key for key in [*data.get("measures", []), "__count"] if key not in row]
    if missing:
        return (
            f"rows are missing key(s) {missing} (method={data.get('method')}); "
            "normalisation contract broken"
        )
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="Path to the .env file")
    parser.add_argument("--limit", type=int, default=1, help="Records per tool")
    parser.add_argument("--no-color", action="store_true", help="Disable colours")
    args = parser.parse_args()

    if args.no_color or not sys.stdout.isatty():
        _plain()

    load_env(Path(args.env))

    # Import after env is loaded.
    from odoo_pulse.core.errors import OdooConfigError
    from odoo_pulse.runtime import get_client

    # 1) Connectivity check.
    print(f"{C.BOLD}Connecting to Odoo...{C.RESET}")
    try:
        version = get_client().version()
    except OdooConfigError as exc:
        print(f"{C.RED}Configuration error:{C.RESET} {exc}")
        print("Copy .env.example to .env and fill in your ODOO_* credentials.")
        return 2
    except Exception as exc:  # noqa: BLE001 - surface any connection/auth issue
        print(f"{C.RED}Could not connect / authenticate:{C.RESET} {exc}")
        return 2

    print(
        f"{C.GREEN}Connected{C.RESET} - server version "
        f"{version.get('server_version', '?')}\n"
    )

    # 2) Sweep every tool.
    counts = {"ok": 0, "skip": 0, "attention": 0}
    current_group = None

    for group, label, func, kwargs in build_cases(args.limit):
        if group != current_group:
            print(f"\n{C.BOLD}{group}{C.RESET}")
            current_group = group

        try:
            raw = func(**kwargs)
        except Exception as exc:  # noqa: BLE001 - a tool should never hard-crash
            counts["attention"] += 1
            print(f"  {C.RED}CRASH{C.RESET}  {label}: {exc}")
            continue

        if label in TEXT_RESULT_TOOLS:
            # Success contract is plain text/markdown; only the error path is
            # JSON, so a JSON-decode failure here just means "got the digest".
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                counts["ok"] += 1
                print(f"  {C.GREEN}ok   {C.RESET} {label} {C.DIM}(text report){C.RESET}")
                continue
        else:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                counts["attention"] += 1
                print(f"  {C.RED}CRASH{C.RESET}  {label}: non-JSON result ({exc})")
                continue

        if isinstance(data, dict) and "error" in data:
            kind = classify_error(data["error"])
            counts[kind] += 1
            if kind == "skip":
                print(f"  {C.DIM}skip {C.RESET} {label} {C.DIM}(app not installed){C.RESET}")
            else:
                print(f"  {C.YELLOW}CHECK{C.RESET} {label}: {data['error'][:90]}")
        else:
            problem = check_aggregate_contract(data)
            if problem:
                counts["attention"] += 1
                print(f"  {C.YELLOW}CHECK{C.RESET} {label}: {problem}")
            else:
                counts["ok"] += 1
                print(f"  {C.GREEN}ok   {C.RESET} {label} {C.DIM}({describe_result(data)}){C.RESET}")

    # 3) Summary.
    total = sum(counts.values())
    print(
        f"\n{C.BOLD}Summary:{C.RESET} {total} tools  |  "
        f"{C.GREEN}{counts['ok']} ok{C.RESET}  |  "
        f"{C.DIM}{counts['skip']} not installed{C.RESET}  |  "
        f"{C.YELLOW}{counts['attention']} need attention{C.RESET}"
    )
    if counts["attention"]:
        print(
            f"{C.YELLOW}Tools marked CHECK likely reference a field that differs on "
            f"your Odoo version - adjust the field list in the matching tool.{C.RESET}"
        )
    # Non-zero exit only when something genuinely needs fixing.
    return 1 if counts["attention"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

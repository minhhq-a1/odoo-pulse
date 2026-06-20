#!/usr/bin/env python3
"""Live smoke test against a *real* Odoo instance.

Unlike the pytest suite (which mocks XML-RPC), this script actually connects to
Odoo using the credentials in your environment / .env file and calls every
read-only list tool once, reporting OK / not-installed / needs-attention for
each. It is the fastest way to confirm a real connection works and to catch
field-name mismatches on a specific Odoo version.

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


def build_cases():
    """(group, label, callable, kwargs) for every list-style tool."""
    from odoo_mcp import (
        domain_tools,
        tools_engagement,
        tools_hr,
        tools_niche,
        tools_operations,
        tools_projects,
    )

    return [
        # group, label, func, kwargs
        ("Core", "find_partner", domain_tools.find_partner, {"query": "a"}),
        ("Core", "list_opportunities", domain_tools.list_opportunities, {}),
        ("Core", "list_sale_orders", domain_tools.list_sale_orders, {}),
        ("Core", "list_purchase_orders", domain_tools.list_purchase_orders, {}),
        ("Core", "find_products", domain_tools.find_products, {}),
        ("Core", "check_stock", domain_tools.check_stock, {"product_query": "a"}),
        ("Core", "list_invoices", domain_tools.list_invoices, {}),
        ("Core", "list_payments", domain_tools.list_payments, {}),
        ("Core", "list_pickings", domain_tools.list_pickings, {}),
        ("HR", "list_employees", tools_hr.list_employees, {}),
        ("HR", "list_departments", tools_hr.list_departments, {}),
        ("HR", "list_time_off", tools_hr.list_time_off, {}),
        ("HR", "list_expenses", tools_hr.list_expenses, {}),
        ("HR", "list_job_positions", tools_hr.list_job_positions, {}),
        ("HR", "list_applicants", tools_hr.list_applicants, {}),
        ("HR", "list_attendances", tools_hr.list_attendances, {}),
        ("Project", "list_projects", tools_projects.list_projects, {}),
        ("Project", "list_tasks", tools_projects.list_tasks, {}),
        ("Project", "list_timesheets", tools_projects.list_timesheets, {}),
        ("Operations", "list_manufacturing_orders", tools_operations.list_manufacturing_orders, {}),
        ("Operations", "list_boms", tools_operations.list_boms, {}),
        ("Operations", "list_pos_orders", tools_operations.list_pos_orders, {}),
        ("Operations", "list_pos_sessions", tools_operations.list_pos_sessions, {}),
        ("Operations", "list_repair_orders", tools_operations.list_repair_orders, {}),
        ("Operations", "list_maintenance_requests", tools_operations.list_maintenance_requests, {}),
        ("Operations", "list_equipment", tools_operations.list_equipment, {}),
        ("Operations", "list_helpdesk_tickets", tools_operations.list_helpdesk_tickets, {}),
        ("Operations", "list_vehicles", tools_operations.list_vehicles, {}),
        ("Engagement", "list_events", tools_engagement.list_events, {}),
        ("Engagement", "list_event_registrations", tools_engagement.list_event_registrations, {}),
        ("Engagement", "list_calendar_events", tools_engagement.list_calendar_events, {}),
        ("Engagement", "list_activities", tools_engagement.list_activities, {}),
        ("Engagement", "list_surveys", tools_engagement.list_surveys, {}),
        ("Engagement", "list_email_campaigns", tools_engagement.list_email_campaigns, {}),
        ("Niche", "list_subscriptions", tools_niche.list_subscriptions, {}),
        ("Niche", "list_sign_requests", tools_niche.list_sign_requests, {}),
        ("Niche", "list_documents", tools_niche.list_documents, {}),
        ("Niche", "list_knowledge_articles", tools_niche.list_knowledge_articles, {}),
        ("Niche", "list_approval_requests", tools_niche.list_approval_requests, {}),
        ("Niche", "list_lunch_orders", tools_niche.list_lunch_orders, {}),
        ("Niche", "list_quality_checks", tools_niche.list_quality_checks, {}),
        ("Niche", "list_quality_alerts", tools_niche.list_quality_alerts, {}),
        ("Niche", "list_planning_slots", tools_niche.list_planning_slots, {}),
        ("Niche", "list_courses", tools_niche.list_courses, {}),
        ("Niche", "list_loyalty_programs", tools_niche.list_loyalty_programs, {}),
        ("Niche", "list_loyalty_cards", tools_niche.list_loyalty_cards, {}),
        ("Niche", "list_memberships", tools_niche.list_memberships, {}),
        ("Niche", "list_payslips", tools_niche.list_payslips, {}),
        ("Niche", "list_appraisals", tools_niche.list_appraisals, {}),
        ("Niche", "list_social_posts", tools_niche.list_social_posts, {}),
        ("Niche", "list_website_visitors", tools_niche.list_website_visitors, {}),
        ("Niche", "list_engineering_changes", tools_niche.list_engineering_changes, {}),
        ("Niche", "list_iot_devices", tools_niche.list_iot_devices, {}),
        ("Niche", "list_notes", tools_niche.list_notes, {}),
    ]


# Heuristic: tell "app not installed" apart from a real schema problem.
_NOT_INSTALLED_HINTS = ("doesn't exist", "does not exist", "object ", "invalid model")


def classify_error(message: str) -> str:
    low = message.lower()
    if any(hint in low for hint in _NOT_INSTALLED_HINTS):
        return "skip"  # app not installed - expected
    return "attention"  # likely a field-name mismatch worth fixing


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
    from odoo_mcp.odoo_client import OdooConfigError
    from odoo_mcp.runtime import get_client

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

    for group, label, func, kwargs in build_cases():
        if group != current_group:
            print(f"\n{C.BOLD}{group}{C.RESET}")
            current_group = group

        try:
            raw = func(limit=args.limit, **kwargs)
            data = json.loads(raw)
        except Exception as exc:  # noqa: BLE001 - a tool should never hard-crash
            counts["attention"] += 1
            print(f"  {C.RED}CRASH{C.RESET}  {label}: {exc}")
            continue

        if isinstance(data, dict) and "error" in data:
            kind = classify_error(data["error"])
            counts[kind] += 1
            if kind == "skip":
                print(f"  {C.DIM}skip {C.RESET} {label} {C.DIM}(app not installed){C.RESET}")
            else:
                print(f"  {C.YELLOW}CHECK{C.RESET} {label}: {data['error'][:90]}")
        else:
            n = len(data) if isinstance(data, list) else 1
            counts["ok"] += 1
            print(f"  {C.GREEN}ok   {C.RESET} {label} {C.DIM}({n} record(s)){C.RESET}")

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

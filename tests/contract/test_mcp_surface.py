import json
import os
import subprocess
import sys


PROBE = r"""
import asyncio
import json
from odoo_pulse import server  # noqa: F401 -- registration side effects
from odoo_pulse.mcp.app import mcp

async def main():
    tools = sorted(tool.name for tool in await mcp.list_tools())
    templates = sorted(
        str(template.uriTemplate)
        for template in await mcp.list_resource_templates()
    )
    print(json.dumps({"tools": tools, "resource_templates": templates}))

asyncio.run(main())
"""


EXPECTED_BY_GROUP = {
    "core": {
        "aggregate_records", "confirm_sale_order", "create_contact",
        "create_lead", "create_record", "create_task", "delete_records",
        "get_model_fields", "list_models", "odoo_version", "read_attachment",
        "read_records", "search_count", "search_read", "update_records",
    },
    "reports": {
        "absence_overview", "business_pulse", "inventory_risk",
        "pipeline_review", "portfolio_health", "procurement_watch",
        "production_health", "project_budget", "project_dashboard",
        "project_profitability", "project_status_report",
        "project_subtask_hours", "receivables_health", "sales_snapshot",
        "standup_digest", "team_workload",
    },
    "business": {
        "check_stock", "find_partner", "find_products", "get_invoice",
        "get_purchase_order", "get_sale_order", "list_invoices",
        "list_opportunities", "list_payments", "list_pickings",
        "list_purchase_orders", "list_sale_orders",
    },
    "hr": {
        "list_applicants", "list_attendances", "list_departments",
        "list_employees", "list_expenses", "list_job_positions",
        "list_time_off",
    },
    "projects": {"list_projects", "list_tasks", "list_timesheets"},
    "operations": {
        "list_boms", "list_equipment", "list_helpdesk_tickets",
        "list_maintenance_requests", "list_manufacturing_orders",
        "list_pos_orders", "list_pos_sessions", "list_repair_orders",
        "list_vehicles",
    },
    "engagement": {
        "list_activities", "list_calendar_events", "list_email_campaigns",
        "list_event_registrations", "list_events", "list_surveys",
    },
    "niche": {
        "list_appraisals", "list_approval_requests", "list_courses",
        "list_documents", "list_engineering_changes", "list_iot_devices",
        "list_knowledge_articles", "list_loyalty_cards",
        "list_loyalty_programs", "list_lunch_orders", "list_memberships",
        "list_notes", "list_payslips", "list_planning_slots",
        "list_quality_alerts", "list_quality_checks", "list_sign_requests",
        "list_social_posts", "list_subscriptions", "list_website_visitors",
    },
}


def probe_surface(groups: str) -> dict[str, list[str]]:
    env = os.environ.copy()
    env["ODOO_TOOL_GROUPS"] = groups
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return json.loads(result.stdout)


def test_each_tool_group_matches_its_registry_contract():
    for group, expected in EXPECTED_BY_GROUP.items():
        surface = probe_surface(group)
        assert set(surface["tools"]) == expected


def test_default_surface_is_core_plus_reports():
    surface = probe_surface("core,reports")
    expected = EXPECTED_BY_GROUP["core"] | EXPECTED_BY_GROUP["reports"]
    assert set(surface["tools"]) == expected
    assert len(surface["tools"]) == 31
    assert surface["resource_templates"] == ["odoo://{model}/{id}"]


def test_all_surface_is_exact_union_of_groups():
    surface = probe_surface("all")
    expected = set().union(*EXPECTED_BY_GROUP.values())
    assert set(surface["tools"]) == expected
    assert len(surface["tools"]) == 88

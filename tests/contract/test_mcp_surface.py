import hashlib
import json
import os
import subprocess
import sys


PROBE = r"""
import asyncio
import json
from odoo_pulse import server  # noqa: F401 -- registration side effects
from odoo_pulse.mcp.app import mcp

PROJECT_TOOL_NAMES = {
    "portfolio_health",
    "project_budget",
    "project_dashboard",
    "project_profitability",
    "project_status_report",
    "project_subtask_hours",
}

async def main():
    registered = sorted(await mcp.list_tools(), key=lambda tool: tool.name)
    templates = sorted(
        str(template.uriTemplate)
        for template in await mcp.list_resource_templates()
    )
    project_contracts = {
        tool.name: {
            "description": tool.description,
            "input_schema": tool.inputSchema,
        }
        for tool in registered
        if tool.name in PROJECT_TOOL_NAMES
    }
    print(json.dumps({
        "tools": [tool.name for tool in registered],
        "resource_templates": templates,
        "project_contracts": project_contracts,
    }, sort_keys=True))

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


EXPECTED_PROJECT_TOOL_CONTRACT = {
    "portfolio_health": {
        "description_sha256": "52988dde7d1225b94ee15b07069caeee6c50e094aaa9c4b0e67c37602867fbd7",
        "input_schema_sha256": "f891a13ac81caa9ffd255f008fb33c7176c0d463a3269e134f275ed6d311b71f",
    },
    "project_budget": {
        "description_sha256": "ed8a60d67c9784ac462e671a3cf1431b3d6a1d1913495a91cedc55af8d6124d9",
        "input_schema_sha256": "c183c7a58a433f3ea302777a1224986ddf33d9d173a993b7e0c29794f362ff6e",
    },
    "project_dashboard": {
        "description_sha256": "3ffdfbe122777eba916cf71bb5d98d0a2e215597e752d62553f159bbe4a3baf8",
        "input_schema_sha256": "7b60ee446f274c18d26a80294e089089738ecd4581bec382d6809b69536bc41a",
    },
    "project_profitability": {
        "description_sha256": "f25e57c197971a861cd443f009d6f2cfc98302c0a204fa0cfb878d74a11f2ad6",
        "input_schema_sha256": "6c6a559bb6122e5096e3bcb46a4e7dc759c07d3bd97de3ac6992586d46d7f02f",
    },
    "project_status_report": {
        "description_sha256": "777dd9bf1d584abb888ed4eedf395e08ed72f6bd83352fb94293d70a687504b8",
        "input_schema_sha256": "550f88a23f098b7502706944a38aea69fe8c4e71d67e56aba7798447ca0102b0",
    },
    "project_subtask_hours": {
        "description_sha256": "405514120a47f40f8ff40b2f4bb5169d3b2ae4d617c91da508b5124c3b1a3258",
        "input_schema_sha256": "d34f1055a6f854a98929499d5f15e8b46debaecad7ff85444d4414e6cdba57d8",
    },
}


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def json_sha256(value: object) -> str:
    normalized = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


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


def test_project_tool_descriptions_and_input_schemas_match_registry_contract():
    contracts = probe_surface("core,reports")["project_contracts"]
    actual = {
        name: {
            "description_sha256": text_sha256(contract["description"]),
            "input_schema_sha256": json_sha256(contract["input_schema"]),
        }
        for name, contract in sorted(contracts.items())
    }
    assert actual == EXPECTED_PROJECT_TOOL_CONTRACT

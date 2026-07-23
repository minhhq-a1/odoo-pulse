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

PLAN4_TOOL_NAMES = {
    "absence_overview",
    "business_pulse",
    "inventory_risk",
    "pipeline_review",
    "procurement_watch",
    "production_health",
    "receivables_health",
    "sales_snapshot",
    "standup_digest",
    "team_workload",
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
    plan4_contracts = {
        tool.name: {
            "description": tool.description,
            "input_schema": tool.inputSchema,
        }
        for tool in registered
        if tool.name in PLAN4_TOOL_NAMES
    }
    print(json.dumps({
        "tools": [tool.name for tool in registered],
        "resource_templates": templates,
        "project_contracts": project_contracts,
        "plan4_contracts": plan4_contracts,
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


EXPECTED_PLAN4_TOOL_CONTRACT = {
    "absence_overview": {
        "description_sha256": "a5f104892fca6d8a812941acac0d7e0af5bcfe826fa6c838dee32732b8c5fb4e",
        "input_schema_sha256": "26e7522bbd5618744c164bd5916ddb44dfbabcce9c1530cab774bfe24abde682",
    },
    "business_pulse": {
        "description_sha256": "549ec69947e0634fda558736ea04a5da9fc6cb0cd5071c57e13129e6b18bf4aa",
        "input_schema_sha256": "718ba0ee33c2587f5b05032612244f65d06a89737f2cbbdbdd0e028f06e9260b",
    },
    "inventory_risk": {
        "description_sha256": "09fe25ecf5b5ccf6a646f1f79549e32b11f1a550a1cad14508dfe88d36693b47",
        "input_schema_sha256": "f80d2c8c402115f6c31c1c34b163ab40a5d05eb69ddfac9b5e3366f8e267272f",
    },
    "pipeline_review": {
        "description_sha256": "921e18de636a00983a07305584fd75d34fa513531b3027be98bffe753aba1414",
        "input_schema_sha256": "9d7ef4da84130e155c0e42dca664092ee3110095b761348fedf1df6a00ab758a",
    },
    "procurement_watch": {
        "description_sha256": "87f0a99edb320314a34a0e2a0141fcc0e188e90892d3b7c46f6782637b48d83a",
        "input_schema_sha256": "0cb0a9db82def6563fd20edc90dcb90e5d4522d60e60dd74347b897c3a731396",
    },
    "production_health": {
        "description_sha256": "10c0eb3d9fd320dc5f698474eed3f9902dbc5262dfaa15e2c771b629a1d673ff",
        "input_schema_sha256": "e5a2421aa25dc6c7fb0d39631a13e714e4406d7eddda8190453fbf53bc770ce4",
    },
    "receivables_health": {
        "description_sha256": "01d162099b66df664f69b5a49d0cdd14cd228d50c109987bbef4766000bc7ee7",
        "input_schema_sha256": "8aef37f4b37cf330a70b585af6f858bcf89a400961f1efabb9ea3496c59aff98",
    },
    "sales_snapshot": {
        "description_sha256": "36452bcda7455c440ccc6474098c186e956bffadf9886a2088cebd048cb908fc",
        "input_schema_sha256": "e931ce30b493246b2e2d05bcb6560a1e983d62a13d30b77fb3cf98724923ea0d",
    },
    "standup_digest": {
        "description_sha256": "0bd9d46121e2e32188f523c0129bf21c2d07a9a8b38a911dfbfcda3110e3bb6f",
        "input_schema_sha256": "7a20b7bba34c76f9ea552bf83672be14037c69273a2d312b2bfc2f220bb65e04",
    },
    "team_workload": {
        "description_sha256": "5613a1ce6712fea6da425d27981c94c424bbf2b671a6d2ad52997dc35fca2ac7",
        "input_schema_sha256": "30c277f6b067d1f0e0ed989c1a44404b5a93eb1ba4fa4b12e615a0b5ba67d464",
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


def test_plan4_tool_descriptions_and_input_schemas_match_registry_contract():
    contracts = probe_surface("core,reports")["plan4_contracts"]
    actual = {
        name: {
            "description_sha256": text_sha256(contract["description"]),
            "input_schema_sha256": json_sha256(contract["input_schema"]),
        }
        for name, contract in sorted(contracts.items())
    }
    assert actual == EXPECTED_PLAN4_TOOL_CONTRACT

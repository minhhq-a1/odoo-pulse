import hashlib
import inspect
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
        "description_sha256": "180bca5ba6dcc8188ab99cd57a5167bf9fd01880e7867b19081aa859ea1c757f",
        "input_schema_sha256": "f891a13ac81caa9ffd255f008fb33c7176c0d463a3269e134f275ed6d311b71f",
    },
    "project_budget": {
        "description_sha256": "587c62889141f91013fe2cb0f3faaeaec3aebc5ee142c84a97cda7f054a7d54b",
        "input_schema_sha256": "c183c7a58a433f3ea302777a1224986ddf33d9d173a993b7e0c29794f362ff6e",
    },
    "project_dashboard": {
        "description_sha256": "61041ef220d424b05d64c76f74946ffd0bb7f09a79dedf111411e33620a5ca8d",
        "input_schema_sha256": "7b60ee446f274c18d26a80294e089089738ecd4581bec382d6809b69536bc41a",
    },
    "project_profitability": {
        "description_sha256": "7b79be3ea8eacba825e6d598d4cb88dcde9813e92814d56c7dafc181db57ba20",
        "input_schema_sha256": "6c6a559bb6122e5096e3bcb46a4e7dc759c07d3bd97de3ac6992586d46d7f02f",
    },
    "project_status_report": {
        "description_sha256": "e67b606e912198804d8444012ac624ea95838c5745d46fc5bacab5d2d728009f",
        "input_schema_sha256": "550f88a23f098b7502706944a38aea69fe8c4e71d67e56aba7798447ca0102b0",
    },
    "project_subtask_hours": {
        "description_sha256": "74cb95d873791eea38189e3bc3e4df47f5f36a442e427057027136ea65c43822",
        "input_schema_sha256": "d34f1055a6f854a98929499d5f15e8b46debaecad7ff85444d4414e6cdba57d8",
    },
}


EXPECTED_PLAN4_TOOL_CONTRACT = {
    "absence_overview": {
        "description_sha256": "288b185244ad232264e705f98d569f4b467b1fe93dbf16a6e0696681dde55982",
        "input_schema_sha256": "26e7522bbd5618744c164bd5916ddb44dfbabcce9c1530cab774bfe24abde682",
    },
    "business_pulse": {
        "description_sha256": "63a262a45d307e86e8b2403e58101c59badcdce87078507d41aebe409f68c139",
        "input_schema_sha256": "718ba0ee33c2587f5b05032612244f65d06a89737f2cbbdbdd0e028f06e9260b",
    },
    "inventory_risk": {
        "description_sha256": "8f54ede37cfdfc74aa2afd29776b5033f54b932c2e8b5057f1e3db0d8f9a1c5d",
        "input_schema_sha256": "f80d2c8c402115f6c31c1c34b163ab40a5d05eb69ddfac9b5e3366f8e267272f",
    },
    "pipeline_review": {
        "description_sha256": "12eca53ff9c2433151f4cc4095d0ef04852a899e726e5009a3981ecc55b7c153",
        "input_schema_sha256": "9d7ef4da84130e155c0e42dca664092ee3110095b761348fedf1df6a00ab758a",
    },
    "procurement_watch": {
        "description_sha256": "fe86a853f970ed7291d5d533aee84e54bacb99a2fe107c3f7ee61f7fe7bf580a",
        "input_schema_sha256": "0cb0a9db82def6563fd20edc90dcb90e5d4522d60e60dd74347b897c3a731396",
    },
    "production_health": {
        "description_sha256": "ac66780e4c10067abd7de3e39755b76bf4f79fdf7f754a32d498bc2092d3332b",
        "input_schema_sha256": "e5a2421aa25dc6c7fb0d39631a13e714e4406d7eddda8190453fbf53bc770ce4",
    },
    "receivables_health": {
        "description_sha256": "de035192878fb88bb2cf7ab4a3762e0e8c00365c3e9594995face17838534249",
        "input_schema_sha256": "8aef37f4b37cf330a70b585af6f858bcf89a400961f1efabb9ea3496c59aff98",
    },
    "sales_snapshot": {
        "description_sha256": "c0bcc11ffb1c169dd6669df15ba91917d9dfe55063ffee99104ed9fb64fa450b",
        "input_schema_sha256": "e931ce30b493246b2e2d05bcb6560a1e983d62a13d30b77fb3cf98724923ea0d",
    },
    "standup_digest": {
        "description_sha256": "ddf962b6378301f7c80833947c97769c08a07908989956fde9c5a6bf95496a9c",
        "input_schema_sha256": "7a20b7bba34c76f9ea552bf83672be14037c69273a2d312b2bfc2f220bb65e04",
    },
    "team_workload": {
        "description_sha256": "6deedd7ecbacf3dac0677865c0e908c3c375b8ea0ef6e7272bda4d8074b4ab15",
        "input_schema_sha256": "30c277f6b067d1f0e0ed989c1a44404b5a93eb1ba4fa4b12e615a0b5ba67d464",
    },
}


def text_sha256(value: str) -> str:
    # Normalize with inspect.cleandoc so the fingerprint is stable across
    # Python versions. CPython 3.13 changed the compiler to strip common
    # leading whitespace from docstring constants (see "What's New in Python
    # 3.13"), so the raw ``fn.__doc__`` — which FastMCP exposes verbatim as
    # ``tool.description`` — differs byte-for-byte between <=3.12 and >=3.13.
    # cleandoc removes that indentation on both sides, keying the contract to
    # the meaningful description text rather than the compiler's dedent policy.
    normalized = inspect.cleandoc(value)
    return hashlib.sha256(normalized.encode()).hexdigest()


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


def test_text_sha256_is_stable_across_docstring_dedent_policy():
    # CPython <=3.12 stores a docstring constant verbatim, preserving the
    # source indentation of continuation lines. CPython 3.13 strips the common
    # leading whitespace at compile time. FastMCP exposes the raw docstring as
    # tool.description, so these two forms are what the same tool yields on
    # different interpreters. text_sha256 must hash them identically.
    raw_indented = (
        "Report which projects are in trouble.\n"
        "\n"
        "    Composes records into a verdict.\n"
        "\n"
        "    Args:\n"
        "        manager: Optional filter.\n"
        "    "
    )
    compiler_dedented = (
        "Report which projects are in trouble.\n"
        "\n"
        "Composes records into a verdict.\n"
        "\n"
        "Args:\n"
        "    manager: Optional filter.\n"
    )
    assert raw_indented != compiler_dedented
    assert text_sha256(raw_indented) == text_sha256(compiler_dedented)
    # And both equal the hash of the plain cleandoc form.
    assert text_sha256(raw_indented) == hashlib.sha256(
        inspect.cleandoc(raw_indented).encode()
    ).hexdigest()

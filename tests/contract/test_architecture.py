import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "odoo_pulse"

RPC_METHODS = {
    "aggregate_records", "fields_get", "search_count", "search_read",
    "read", "execute_kw",
}


def test_services_do_not_import_mcp_or_tool_adapters():
    violations = []
    for path in sorted((PACKAGE / "services").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                parts = module.split(".")
                if ("mcp" in parts or "json" in parts
                        or any(part.startswith("tools_") for part in parts)):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if ("mcp" in parts or "json" in parts
                            or any(part.startswith("tools_") for part in parts)):
                        violations.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}"
                        )
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "tool"
            for node in ast.walk(tree)
        ), path
    assert violations == []


def test_plan4_adapters_are_thin_and_delegate_to_designated_builders():
    adapters = {
        "tools_reports_sales.py": {
            "pipeline_review": ("safe", "build_pipeline_review"),
            "sales_snapshot": ("safe", "build_sales_snapshot"),
        },
        "tools_reports_finance.py": {
            "receivables_health": ("safe", "build_receivables_health"),
        },
        "tools_reports_hr.py": {
            "absence_overview": ("safe", "build_absence_overview"),
        },
        "tools_reports_inventory.py": {
            "inventory_risk": ("safe", "build_inventory_risk"),
        },
        "tools_reports_ops.py": {
            "procurement_watch": ("safe", "build_procurement_watch"),
            "production_health": ("safe", "build_production_health"),
        },
        "tools_reports_pulse.py": {
            "business_pulse": ("safe", "build_business_pulse"),
        },
        "tools_workflows.py": {
            "team_workload": ("safe", "build_team_workload"),
            "standup_digest": ("safe_text", "build_standup_digest"),
        },
    }
    for filename, delegations in adapters.items():
        path = PACKAGE / filename
        tree = ast.parse(path.read_text())
        adapter_imports = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                adapter_imports.extend((node.module or "").split("."))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    adapter_imports.extend(alias.name.split("."))
        assert not any(part.startswith("tools_") for part in adapter_imports), path

        functions = {
            node.name: node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in delegations
        }
        assert set(functions) == set(delegations)
        for name, function in functions.items():
            assert not any(
                isinstance(node, (ast.For, ast.While, ast.Try))
                for node in ast.walk(function)
            ), f"{filename}:{name}"
            forbidden_calls = [
                node for node in ast.walk(function)
                if isinstance(node, ast.Call) and (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "build_report"
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr in RPC_METHODS
                )
            ]
            assert forbidden_calls == [], f"{filename}:{name}"

            returns = [
                node for node in function.body if isinstance(node, ast.Return)
            ]
            assert len(returns) == 1, f"{filename}:{name}"
            boundary_call = returns[0].value
            expected_boundary, expected_builder = delegations[name]
            assert isinstance(boundary_call, ast.Call), f"{filename}:{name}"
            assert isinstance(boundary_call.func, ast.Name)
            assert boundary_call.func.id == expected_boundary
            assert len(boundary_call.args) == 1
            callback = boundary_call.args[0]
            assert isinstance(callback, ast.Lambda)
            builder_call = callback.body
            assert isinstance(builder_call, ast.Call)
            assert isinstance(builder_call.func, ast.Name)
            assert builder_call.func.id == expected_builder
            assert builder_call.args
            client_call = builder_call.args[0]
            assert isinstance(client_call, ast.Call)
            assert isinstance(client_call.func, ast.Name)
            assert client_call.func.id == "get_client"

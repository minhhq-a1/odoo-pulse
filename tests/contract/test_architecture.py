import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "odoo_pulse"

RPC_METHODS = {
    "aggregate_records", "fields_get", "search_count", "search_read",
    "read", "execute_kw", "write", "create", "unlink",
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
        "tools/reports/sales.py": {
            "sales_snapshot": ("safe", "build_sales_snapshot"),
        },
        "tools/reports/finance.py": {
            "receivables_health": ("safe", "build_receivables_health"),
        },
        "tools/reports/hr.py": {
            "absence_overview": ("safe", "build_absence_overview"),
        },
        "tools/reports/inventory.py": {
            "inventory_risk": ("safe", "build_inventory_risk"),
        },
        "tools/reports/operations.py": {
            "procurement_watch": ("safe", "build_procurement_watch"),
            "production_health": ("safe", "build_production_health"),
        },
        "tools/reports/pulse.py": {
            "business_pulse": ("safe", "build_business_pulse"),
        },
        "tools/reports/workflows.py": {
            "pipeline_review": ("safe", "build_pipeline_review"),
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


def test_write_service_does_not_reimplement_core_guards():
    """services/writes.py must not inspect env vars or import core.client."""
    path = PACKAGE / "services" / "writes.py"
    source = path.read_text()
    tree = ast.parse(source)
    forbidden_imports = {"core.client", "OdooClient"}
    forbidden_strings = {"ODOO_READ_ONLY", "ODOO_WRITABLE_MODELS", "_check_write"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "core.client" not in module, (
                f"services/writes.py must not import core.client (line {node.lineno})"
            )
            for alias in node.names:
                assert alias.name not in forbidden_imports, (
                    f"Forbidden import {alias.name!r} in services/writes.py:{node.lineno}"
                )
    for name in forbidden_strings:
        assert name not in source, (
            f"services/writes.py must not reference {name!r}; "
            "write guards belong exclusively in core.client"
        )


def test_all_decorated_tools_live_under_tools_package():
    """Every @mcp.tool() decoration must be in a file under src/odoo_pulse/tools/."""
    tools_dir = PACKAGE / "tools"
    outside_violations = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.is_relative_to(tools_dir):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "tool"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "mcp"
            ):
                outside_violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert outside_violations == [], (
        "Found @mcp.tool() decorations outside tools/: " + str(outside_violations)
    )


def test_no_flat_adapter_modules_or_cross_tool_imports_remain():
    """No tools_*.py flat files; no tool module imports from another tool module."""
    flat_files = list(PACKAGE.glob("tools_*.py"))
    assert flat_files == [], f"Stale flat adapter files: {flat_files}"

    tools_dir = PACKAGE / "tools"
    tools_dotted_prefix = "odoo_pulse.tools."
    cross_imports = []
    for path in sorted(tools_dir.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text())
        own_dotted = (
            "odoo_pulse."
            + str(path.relative_to(PACKAGE)).replace("/", ".").removesuffix(".py")
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith(tools_dotted_prefix) and not own_dotted.startswith(
                    module
                ):
                    cross_imports.append(f"{path.relative_to(ROOT)}:{node.lineno} -> {module}")
    assert cross_imports == [], f"Cross-tool imports found: {cross_imports}"


def test_breadth_list_adapters_delegate_without_direct_rpc():
    """tools/lists/*.py must not call client.search_read / client.execute_kw directly."""
    lists_dir = PACKAGE / "tools" / "lists"
    violations = []
    for path in sorted(lists_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text())
        for func_node in ast.walk(tree):
            if not isinstance(func_node, ast.FunctionDef):
                continue
            for node in ast.walk(func_node):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in RPC_METHODS
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in ("client", "get_client()")
                ):
                    violations.append(f"{path.relative_to(ROOT)}:{node.col_offset} direct RPC {node.func.attr!r}")
    assert violations == [], f"Breadth list adapters contain direct RPC calls: {violations}"

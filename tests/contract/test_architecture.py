import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "odoo_pulse"

RPC_METHODS = {
    "aggregate_records", "fields_get", "search_count", "search_read",
    "read", "execute_kw", "write", "create", "unlink",
    "list_models", "version", "major_version",
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
            "pipeline_review": ("safe", "build_pipeline_review"),
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


def test_write_guards_and_decorated_tool_locations():
    """services/writes.py must not reimplement guards; every @mcp.tool() must live under tools/ (exactly 88)."""
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

    tools_dir = PACKAGE / "tools"
    outside_violations = []
    tool_count = 0
    for path in sorted(PACKAGE.rglob("*.py")):
        t = ast.parse(path.read_text())
        for node in ast.walk(t):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "tool"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "mcp"
            ):
                if path.is_relative_to(tools_dir):
                    tool_count += 1
                else:
                    outside_violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert outside_violations == [], f"Found @mcp.tool() decorations outside tools/: {outside_violations}"
    assert tool_count == 88, f"Expected 88 @mcp.tool() decorations under tools/, found {tool_count}"


def test_clean_package_layout_and_breadth_list_delegation():
    """No flat adapter files or cross-tool imports; tools/lists/*.py locked and delegate without direct RPC."""
    assert not (PACKAGE / "domain_tools.py").exists(), "domain_tools.py still exists"
    flat_files = list(PACKAGE.glob("tools_*.py"))
    assert flat_files == [], f"Stale flat adapter files: {flat_files}"

    tools_dir = PACKAGE / "tools"
    lists_dir = tools_dir / "lists"
    expected_list_files = {
        "business.py", "engagement.py", "hr.py",
        "niche.py", "operations.py", "projects.py",
    }
    actual_list_files = {p.name for p in lists_dir.glob("*.py") if p.name != "__init__.py"}
    assert actual_list_files == expected_list_files, f"Unexpected list files: {actual_list_files}"

    allowed_subpackages = {"common", "core", "mcp", "services"}
    cross_imports = []
    for path in sorted(tools_dir.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
                    parts = mod.split(".")
                    if parts[0] == "tools" or (parts[0] == "odoo_pulse" and len(parts) > 1 and parts[1] == "tools"):
                        cross_imports.append(f"{path.relative_to(ROOT)}:{node.lineno} -> {mod}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level == 0:
                    parts = module.split(".")
                    if parts[0] == "tools" or (parts[0] == "odoo_pulse" and len(parts) > 1 and parts[1] == "tools"):
                        cross_imports.append(f"{path.relative_to(ROOT)}:{node.lineno} -> {module}")
                else:
                    parts = module.split(".") if module else []
                    first_target = parts[0] if parts else ""
                    if first_target and first_target not in allowed_subpackages:
                        cross_imports.append(f"{path.relative_to(ROOT)}:{node.lineno} -> relative {module}")
                    elif not first_target:
                        cross_imports.append(f"{path.relative_to(ROOT)}:{node.lineno} -> bare relative import")
    assert cross_imports == [], f"Cross-tool imports found: {cross_imports}"

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
                ):
                    violations.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} direct RPC {node.func.attr!r}"
                    )
    assert violations == [], f"Breadth list adapters contain direct RPC calls: {violations}"

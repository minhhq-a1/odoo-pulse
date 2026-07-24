import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "src" / "odoo_pulse"


def test_services_have_no_mcp_or_tool_imports_or_global_client():
    services_dir = ROOT / "services"
    forbidden_imports = {"mcp", "tools", "tools_generic", "tools_write", "tools_workflows"}

    for py_file in services_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    pkg = alias.name.split(".")[0]
                    assert pkg not in forbidden_imports, f"{py_file} imports forbidden module {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    pkg = node.module.split(".")[0]
                    assert pkg not in forbidden_imports, f"{py_file} imports from forbidden module {node.module}"
                    if node.level > 0 and node.module in ("mcp", "tools"):
                        assert False, f"{py_file} imports from relative forbidden module {node.module}"
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "get_client":
                    assert False, f"{py_file} calls get_client()"


def test_architecture_layer_dependency_direction():
    # Enforce strict hierarchy: core -> common -> services -> mcp/tools
    # core and common cannot import services, mcp, or tools
    for layer in ("core", "common"):
        layer_dir = ROOT / layer
        for py_file in layer_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    top = node.module.split(".")[0]
                    assert top not in ("services", "mcp", "tools"), f"{py_file} imports upper layer {node.module}"

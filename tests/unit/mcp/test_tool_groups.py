# tests/test_tool_groups.py
import pytest

from odoo_pulse.mcp.registry import GROUP_MODULES, modules_to_load, parse_groups


def test_default_groups_are_core_and_reports():
    assert parse_groups(None) == ["core", "reports"]
    assert parse_groups("") == ["core", "reports"]


def test_all_enables_every_group():
    assert parse_groups("all") == list(GROUP_MODULES)


def test_custom_selection_preserves_order_and_trims_whitespace():
    assert parse_groups(" core , hr ") == ["core", "hr"]


def test_unknown_group_raises_with_valid_names():
    with pytest.raises(ValueError, match="warehouse"):
        parse_groups("core,warehouse")


def test_modules_to_load_default(monkeypatch):
    monkeypatch.delenv("ODOO_TOOL_GROUPS", raising=False)
    assert modules_to_load() == [
        "tools.generic", "tools.writes", "mcp.resources",
        "tools.reports.workflows", "tools.reports.sales", "tools.reports.finance",
        "tools.reports.inventory", "tools.reports.hr", "tools.reports.pulse",
        "tools.reports.operations", "tools.reports.projects",
    ]


def test_modules_to_load_reads_env(monkeypatch):
    monkeypatch.setenv("ODOO_TOOL_GROUPS", "core,projects")
    assert modules_to_load() == ["tools.generic", "tools.writes", "mcp.resources", "tools.lists.projects"]


def test_modules_to_load_deduplicates():
    assert modules_to_load("core,core,reports") == [
        "tools.generic", "tools.writes", "mcp.resources",
        "tools.reports.workflows", "tools.reports.sales", "tools.reports.finance",
        "tools.reports.inventory", "tools.reports.hr", "tools.reports.pulse",
        "tools.reports.operations", "tools.reports.projects",
    ]


def test_reports_group_includes_ops_module():
    assert "tools.reports.operations" in GROUP_MODULES["reports"]


def test_reports_group_includes_workflows_module():
    assert "tools.reports.workflows" in GROUP_MODULES["reports"]


def test_reports_group_includes_projects_module():
    assert "tools.reports.projects" in GROUP_MODULES["reports"]


def test_core_group_includes_resources_module():
    assert "mcp.resources" in GROUP_MODULES["core"]


def test_opt_in_groups_map_to_tools_lists_subpackage():
    for group in ("hr", "projects", "operations", "engagement", "niche"):
        mod = GROUP_MODULES[group][0]
        assert mod.startswith("tools.lists.")

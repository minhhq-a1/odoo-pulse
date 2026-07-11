# tests/test_tool_groups.py
import pytest

from odoo_pulse.tool_groups import GROUP_MODULES, modules_to_load, parse_groups


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
        "tools_generic", "tools_write", "tools_workflows", "tools_reports_sales",
        "tools_reports_finance", "tools_reports_inventory", "tools_reports_hr",
        "tools_reports_pulse", "tools_reports_ops", "tools_reports_projects",
    ]


def test_modules_to_load_reads_env(monkeypatch):
    monkeypatch.setenv("ODOO_TOOL_GROUPS", "core,projects")
    assert modules_to_load() == ["tools_generic", "tools_write", "tools_projects"]


def test_modules_to_load_deduplicates():
    assert modules_to_load("core,core,reports") == [
        "tools_generic", "tools_write", "tools_workflows", "tools_reports_sales",
        "tools_reports_finance", "tools_reports_inventory", "tools_reports_hr",
        "tools_reports_pulse", "tools_reports_ops", "tools_reports_projects",
    ]


def test_reports_group_includes_ops_module():
    assert "tools_reports_ops" in GROUP_MODULES["reports"]


def test_reports_group_includes_projects_module():
    assert "tools_reports_projects" in GROUP_MODULES["reports"]

import importlib
from pathlib import Path

import odoo_pulse


def test_package_is_loaded_from_src_layout():
    package_dir = Path(odoo_pulse.__file__).resolve().parent
    assert package_dir.name == "odoo_pulse"
    assert package_dir.parent.name == "src"


def test_package_service_and_tool_modules_are_packaged_and_importable():
    modules = [
        "odoo_pulse.services.report_context",
        "odoo_pulse.services.pulse",
        "odoo_pulse.services.crm.metrics",
        "odoo_pulse.services.crm.pipeline",
        "odoo_pulse.services.sales.metrics",
        "odoo_pulse.services.sales.snapshot",
        "odoo_pulse.services.finance.metrics",
        "odoo_pulse.services.finance.receivables",
        "odoo_pulse.services.hr.metrics",
        "odoo_pulse.services.hr.absence",
        "odoo_pulse.services.inventory.risk",
        "odoo_pulse.services.operations.procurement",
        "odoo_pulse.services.operations.production",
        "odoo_pulse.services.projects.metrics",
        "odoo_pulse.services.projects.workload",
        "odoo_pulse.services.projects.standup",
        "odoo_pulse.services.generic",
        "odoo_pulse.services.records",
        "odoo_pulse.services.writes",
        "odoo_pulse.tools.generic",
        "odoo_pulse.tools.writes",
        "odoo_pulse.tools.lists.business",
        "odoo_pulse.tools.lists.engagement",
        "odoo_pulse.tools.lists.hr",
        "odoo_pulse.tools.lists.niche",
        "odoo_pulse.tools.lists.operations",
        "odoo_pulse.tools.lists.projects",
        "odoo_pulse.tools.reports.workflows",
        "odoo_pulse.tools.reports.finance",
        "odoo_pulse.tools.reports.hr",
        "odoo_pulse.tools.reports.inventory",
        "odoo_pulse.tools.reports.operations",
        "odoo_pulse.tools.reports.projects",
        "odoo_pulse.tools.reports.pulse",
        "odoo_pulse.tools.reports.sales",
    ]
    assert [importlib.import_module(name).__name__ for name in modules] == modules

    package = Path(odoo_pulse.__file__).resolve().parent
    assert not (package / "domain_tools.py").exists()
    assert list(package.glob("tools_*.py")) == []
    assert not (package / "tools" / "lists" / "project.py").exists()

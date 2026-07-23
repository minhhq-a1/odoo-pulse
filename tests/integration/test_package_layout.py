from pathlib import Path

import odoo_pulse


def test_package_is_loaded_from_src_layout():
    package_dir = Path(odoo_pulse.__file__).resolve().parent
    assert package_dir.name == "odoo_pulse"
    assert package_dir.parent.name == "src"


def test_plan4_service_modules_are_packaged_and_importable():
    import importlib

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
    ]
    assert [importlib.import_module(name).__name__ for name in modules] == modules

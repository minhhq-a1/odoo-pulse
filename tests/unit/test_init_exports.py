import odoo_pulse


def test_package_exposes_version_string():
    assert isinstance(odoo_pulse.__version__, str)
    assert odoo_pulse.__version__ == "0.1.0"


def test_package_exposes_mcp_runtime_symbols():
    assert hasattr(odoo_pulse, "mcp")
    assert hasattr(odoo_pulse, "get_client")


def test_package_exposes_core_error_classes():
    assert issubclass(odoo_pulse.OdooConfigError, Exception)
    assert issubclass(odoo_pulse.OdooError, Exception)


def test_package_exposes_clean_subpackage_namespaces():
    for name in ("core", "common", "services", "tools"):
        assert hasattr(odoo_pulse, name)

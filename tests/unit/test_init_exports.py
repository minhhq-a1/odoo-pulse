import odoo_pulse


def test_package_exposes_version_string():
    assert isinstance(odoo_pulse.__version__, str)
    assert odoo_pulse.__version__ != ""


def test_package_all_is_version_only():
    assert odoo_pulse.__all__ == ["__version__"]

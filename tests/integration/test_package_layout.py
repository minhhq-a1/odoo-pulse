from pathlib import Path

import odoo_pulse


def test_package_is_loaded_from_src_layout():
    package_dir = Path(odoo_pulse.__file__).resolve().parent
    assert package_dir.name == "odoo_pulse"
    assert package_dir.parent.name == "src"

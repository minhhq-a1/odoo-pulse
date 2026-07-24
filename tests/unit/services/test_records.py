import pytest

from odoo_pulse.core.errors import OdooError
from odoo_pulse.services.records import read_one, read_sale_order


def test_read_one_service_raises_on_missing_record(fake_client):
    fake_client.read_responses["res.partner"] = []
    with pytest.raises(OdooError, match="not found"):
        read_one(fake_client, "res.partner", 999)


def test_read_sale_order_service_expands_line_items(fake_client):
    fake_client.search_responses["sale.order"] = [{"id": 5}]
    fake_client.read_responses["sale.order"] = [
        {"id": 5, "name": "S00005", "order_line": [10]}
    ]
    fake_client.read_responses["sale.order.line"] = [
        {"id": 10, "name": "Line A"}
    ]
    result = read_sale_order(fake_client, order_name="S00005")
    assert result["name"] == "S00005"
    assert result["lines"] == [{"id": 10, "name": "Line A"}]
    assert "order_line" not in result

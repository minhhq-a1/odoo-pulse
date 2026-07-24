import pytest

from odoo_pulse.core.errors import OdooError
from odoo_pulse.services.generic import parse_measures, read_attachment


def test_parse_measures_defaults_and_rejects_unsupported_aggregators():
    assert parse_measures(None) == [("id", "count")]
    assert parse_measures(["amount_total"]) == [("amount_total", "sum")]
    with pytest.raises(OdooError, match="median"):
        parse_measures(["amount_total:median"])


def test_read_attachment_service_returns_python_payload(fake_client):
    fake_client.read_responses["ir.attachment"] = [{
        "name": "invoice.pdf", "type": "binary", "file_size": 10,
        "url": False, "datas": "QkFTRTY0",
    }]
    result = read_attachment(fake_client, 7)
    assert isinstance(result, dict)
    assert result["data_base64"] == "QkFTRTY0"
    assert result["data_included"] is True

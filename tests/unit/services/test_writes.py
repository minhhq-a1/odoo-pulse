import pytest

from odoo_pulse.core.errors import OdooError
from odoo_pulse.services.writes import delete_records, update_records


def test_update_records_service_requires_non_empty_ids(fake_client):
    with pytest.raises(OdooError, match="non-empty list"):
        update_records(fake_client, model="res.partner", ids=[], values={"name": "X"})


def test_delete_records_service_returns_preview_by_default(fake_client):
    fake_client.read_responses["res.partner"] = [{"display_name": "Partner 1"}]
    res = delete_records(fake_client, model="res.partner", ids=[1])
    assert res["preview"] is True
    assert res["action"] == "delete"
    assert res["affected"] == ["Partner 1"]

import pytest

from odoo_pulse.core.errors import OdooConfigError, OdooError
from odoo_pulse.services.writes import delete_records, display_names, update_records


def test_update_records_service_requires_non_empty_ids(fake_client):
    with pytest.raises(OdooError, match="non-empty list"):
        update_records(fake_client, model="res.partner", ids=[], values={"name": "X"})

    # display_names with client=None returns None
    assert display_names(None, "res.partner", [1]) is None

    # display_names propagates OdooError / OdooConfigError when client is not None
    for error in (OdooError("read failed"), OdooConfigError("config read failed")):
        def failing_read(*args, _error=error, **kwargs):
            raise _error

        fake_client.read = failing_read
        with pytest.raises(type(error), match=str(error)):
            display_names(fake_client, "res.partner", [1])


def test_delete_records_service_returns_preview_by_default(fake_client):
    fake_client.read_responses["res.partner"] = [{"display_name": "Partner 1"}]
    res = delete_records(fake_client, model="res.partner", ids=[1])
    assert res["preview"] is True
    assert res["action"] == "delete"
    assert res["affected"] == ["Partner 1"]

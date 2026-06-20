"""Tests for OdooClient against a fake XML-RPC proxy (no network)."""

from __future__ import annotations

import xmlrpc.client

import pytest

from odoo_mcp.odoo_client import OdooClient, OdooConfig, OdooError


class FakeProxy:
    """Stands in for the /xmlrpc/2/object ServerProxy."""

    def __init__(self, return_value=None, fault=None):
        self.return_value = return_value
        self.fault = fault
        self.calls: list[tuple] = []

    def execute_kw(self, db, uid, key, model, method, args, kwargs):
        self.calls.append((db, uid, key, model, method, args, kwargs))
        if self.fault:
            raise xmlrpc.client.Fault(2, self.fault)
        return self.return_value


def make_client(return_value=None, *, read_only=True, max_records=200, fault=None):
    cfg = OdooConfig(
        url="https://acme.odoo.com",
        db="acme",
        username="me@acme.com",
        api_key="secret",
        read_only=read_only,
        max_records=max_records,
    )
    client = OdooClient(cfg)
    proxy = FakeProxy(return_value=return_value, fault=fault)
    # Pre-seed the cached_property slots so no real network/auth happens.
    client.__dict__["uid"] = 42
    client.__dict__["_models"] = proxy
    return client, proxy


def test_execute_kw_passes_credentials_and_payload():
    client, proxy = make_client(return_value=[{"id": 1}])
    out = client.execute_kw("res.partner", "search_read", [[("a", "=", 1)]], {"limit": 5})
    assert out == [{"id": 1}]
    db, uid, key, model, method, args, kwargs = proxy.calls[0]
    assert (db, uid, key) == ("acme", 42, "secret")
    assert model == "res.partner"
    assert method == "search_read"
    assert args == [[("a", "=", 1)]]
    assert kwargs == {"limit": 5}


def test_read_only_blocks_write_methods():
    client, proxy = make_client(read_only=True)
    for method in ("create", "write", "unlink"):
        with pytest.raises(OdooError):
            client.execute_kw("res.partner", method, [[1]])
    # Nothing should have reached the proxy.
    assert proxy.calls == []


def test_write_allowed_when_not_read_only():
    client, proxy = make_client(return_value=99, read_only=False)
    assert client.execute_kw("res.partner", "create", [{"name": "X"}]) == 99
    assert proxy.calls[0][4] == "create"


def test_fault_is_wrapped_as_odoo_error():
    client, _ = make_client(fault="boom")
    with pytest.raises(OdooError) as exc:
        client.search_count("res.partner")
    assert "boom" in str(exc.value)


@pytest.mark.parametrize(
    "requested,expected",
    [(None, 200), (0, 200), (-1, 200), (5, 5), (500, 200)],
)
def test_search_read_caps_limit(requested, expected):
    client, proxy = make_client(return_value=[], max_records=200)
    client.search_read("res.partner", limit=requested)
    _, _, _, _, _, _, kwargs = proxy.calls[0]
    assert kwargs["limit"] == expected


def test_search_read_forwards_domain_fields_order():
    client, proxy = make_client(return_value=[])
    client.search_read(
        "sale.order",
        domain=[("state", "=", "sale")],
        fields=["name"],
        limit=10,
        offset=5,
        order="date_order desc",
    )
    _, _, _, model, method, args, kwargs = proxy.calls[0]
    assert model == "sale.order"
    assert method == "search_read"
    assert args == [[("state", "=", "sale")]]
    assert kwargs["fields"] == ["name"]
    assert kwargs["offset"] == 5
    assert kwargs["order"] == "date_order desc"


def test_read_and_fields_get_and_count():
    client, proxy = make_client(return_value=[{"id": 1, "name": "A"}])
    client.read("res.partner", [1], fields=["name"])
    assert proxy.calls[-1][4] == "read"
    assert proxy.calls[-1][5] == [[1]]

    client, proxy = make_client(return_value={"name": {"type": "char"}})
    client.fields_get("res.partner")
    assert proxy.calls[-1][4] == "fields_get"

    client, proxy = make_client(return_value=3)
    assert client.search_count("res.partner", [("x", "=", 1)]) == 3
    assert proxy.calls[-1][4] == "search_count"

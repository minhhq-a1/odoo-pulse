# tests/test_client_aggregate.py
import pytest

from odoo_mcp.odoo_client import OdooClient, OdooConfig, OdooError


def _client(server_version="18.0"):
    cfg = OdooConfig(url="http://x", db="d", username="u", api_key="k")
    client = OdooClient(cfg)
    client.version = lambda: {"server_version": server_version}  # type: ignore[assignment]
    calls = []

    def fake_execute_kw(model, method, args=None, kwargs=None):
        calls.append({"model": model, "method": method, "args": args, "kwargs": kwargs})
        return [{"__count": 3}]

    client.execute_kw = fake_execute_kw  # type: ignore[assignment]
    return client, calls


def test_major_version_parses_leading_int():
    client, _ = _client("saas~18.1+e")
    assert client.major_version() == 18


def test_major_version_none_when_unparseable():
    client, _ = _client(server_version="")
    assert client.major_version() is None


def test_v18_uses_read_group_legacy_kwargs():
    client, calls = _client("18.0")
    out = client.aggregate_records(
        "sale.order", ["state"], [("amount_total", "sum")], domain=[["state", "=", "sale"]]
    )
    assert out["method"] == "read_group"
    assert out["major_version"] == 18
    call = calls[-1]
    assert call["method"] == "read_group"
    assert call["args"] == [[["state", "=", "sale"]]]
    assert call["kwargs"]["fields"] == ["amount_total:sum"]
    assert call["kwargs"]["groupby"] == ["state"]
    assert call["kwargs"]["lazy"] is False


def test_v19_uses_formatted_read_group_with_aggregates():
    client, calls = _client("19.0")
    out = client.aggregate_records("sale.order", ["state"], [("amount_total", "sum")])
    assert out["method"] == "formatted_read_group"
    assert out["major_version"] == 19
    call = calls[-1]
    assert call["method"] == "formatted_read_group"
    assert call["kwargs"]["aggregates"] == ["amount_total:sum"]
    assert call["kwargs"]["groupby"] == ["state"]


def test_unknown_version_falls_back_to_read_group():
    client, calls = _client(server_version="")
    seen = []

    def fake_execute_kw(model, method, args=None, kwargs=None):
        seen.append(method)
        if method == "formatted_read_group":
            raise OdooError("Object sale.order has no method formatted_read_group")
        return [{"__count": 1}]

    client.execute_kw = fake_execute_kw  # type: ignore[assignment]
    out = client.aggregate_records("sale.order", ["state"], [("id", "count")])
    assert out["method"] == "read_group"
    assert out["major_version"] is None
    assert seen == ["formatted_read_group", "read_group"]

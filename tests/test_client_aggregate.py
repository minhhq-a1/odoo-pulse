# tests/test_client_aggregate.py
from odoo_pulse.core.config import OdooConfig
from odoo_pulse.core.errors import OdooError
from odoo_pulse.odoo_client import OdooClient


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
    assert call["kwargs"]["aggregates"] == ["amount_total:sum", "__count"]
    assert call["kwargs"]["groupby"] == ["state"]


def test_v19_empty_measures_requests_count_aggregate():
    client, calls = _client("19.0")
    out = client.aggregate_records("hr.leave", ["employee_id"], [])
    assert out["method"] == "formatted_read_group"
    call = calls[-1]
    assert call["method"] == "formatted_read_group"
    assert call["kwargs"]["aggregates"] == ["__count"]


def test_v18_empty_measures_keeps_fields_empty():
    client, calls = _client("18.0")
    out = client.aggregate_records("hr.leave", ["employee_id"], [])
    assert out["method"] == "read_group"
    call = calls[-1]
    assert call["method"] == "read_group"
    assert "__count" not in call["kwargs"]["fields"]
    assert call["kwargs"]["fields"] == []


def test_v18_order_strips_aggregate_suffix():
    client, calls = _client("18.0")
    client.aggregate_records(
        "sale.order.line",
        ["product_id"],
        [("price_subtotal", "sum")],
        order="price_subtotal:sum desc",
    )
    call = calls[-1]
    assert call["method"] == "read_group"
    assert call["kwargs"]["orderby"] == "price_subtotal desc"


def test_v18_order_keeps_non_aggregator_suffix():
    client, calls = _client("18.0")
    client.aggregate_records(
        "sale.order",
        ["date_order:month"],
        [("amount_total", "sum")],
        order="date_order:month asc, amount_total:sum desc",
    )
    call = calls[-1]
    assert call["kwargs"]["orderby"] == "date_order:month asc, amount_total desc"


def test_v19_order_passed_through_unchanged():
    client, calls = _client("19.0")
    client.aggregate_records(
        "sale.order.line",
        ["product_id"],
        [("price_subtotal", "sum")],
        order="price_subtotal:sum desc",
    )
    call = calls[-1]
    assert call["method"] == "formatted_read_group"
    assert call["kwargs"]["order"] == "price_subtotal:sum desc"


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


def test_legacy_rows_normalised_to_spec_keys():
    # legacy read_group returns bare field keys + __count (lazy=False)
    client, calls = _client("18.0")
    client.execute_kw = lambda model, method, args=None, kwargs=None: [
        {"state": "sale", "amount_total": 1500.0, "__count": 3}
    ]
    out = client.aggregate_records("sale.order", ["state"], [("amount_total", "sum")])
    row = out["rows"][0]
    assert row["amount_total:sum"] == 1500.0
    assert "amount_total" not in row
    assert row["__count"] == 3


def test_legacy_normalisation_skips_grouped_fields():
    client, calls = _client("18.0")
    client.execute_kw = lambda model, method, args=None, kwargs=None: [
        {"state": "sale", "__count": 2}
    ]
    out = client.aggregate_records("sale.order", ["state"], [])
    assert out["rows"][0]["state"] == "sale"


def test_formatted_always_requests_count():
    client, calls = _client("19.0")
    client.aggregate_records("sale.order", ["state"], [("amount_total", "sum")])
    call = calls[-1]
    assert "__count" in call["kwargs"]["aggregates"]
    assert "amount_total:sum" in call["kwargs"]["aggregates"]


def test_unknown_version_fallback_normalises_legacy_rows():
    client, calls = _client(server_version="")

    def fake_execute_kw(model, method, args=None, kwargs=None):
        if method == "formatted_read_group":
            raise OdooError("Object sale.order has no method formatted_read_group")
        return [{"state": "sale", "amount_total": 42.0, "__count": 1}]

    client.execute_kw = fake_execute_kw  # type: ignore[assignment]
    out = client.aggregate_records("sale.order", ["state"], [("amount_total", "sum")])
    row = out["rows"][0]
    assert row["amount_total:sum"] == 42.0
    assert "amount_total" not in row
    assert row["__count"] == 1

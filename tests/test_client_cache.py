# tests/test_client_cache.py
from odoo_pulse.core.config import OdooConfig
from odoo_pulse.core.client import OdooClient


def _client(ttl=300.0, max_entries=64):
    cfg = OdooConfig(
        url="http://x", db="d", username="u", api_key="k",
        schema_cache_ttl=ttl, schema_cache_max=max_entries,
    )
    client = OdooClient(cfg)
    calls = {"n": 0}

    def fake_execute_kw(model, method, args=None, kwargs=None):
        calls["n"] += 1
        return {"name": {"type": "char", "string": "Name"}}

    client.execute_kw = fake_execute_kw  # type: ignore[assignment]
    return client, calls


def test_second_fields_get_within_ttl_is_cached():
    client, calls = _client()
    client.fields_get("res.partner")
    client.fields_get("res.partner")
    assert calls["n"] == 1


def test_refresh_bypasses_cache():
    client, calls = _client()
    client.fields_get("res.partner")
    client.fields_get("res.partner", refresh=True)
    assert calls["n"] == 2


def test_ttl_zero_disables_cache():
    client, calls = _client(ttl=0)
    client.fields_get("res.partner")
    client.fields_get("res.partner")
    assert calls["n"] == 2


def test_distinct_attributes_are_separate_keys():
    client, calls = _client()
    client.fields_get("res.partner", attributes=["string"])
    client.fields_get("res.partner", attributes=["type"])
    assert calls["n"] == 2

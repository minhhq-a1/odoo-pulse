# tests/test_cache.py
import odoo_mcp.cache as cache_mod
from odoo_mcp.cache import TTLCache


def test_set_then_get_returns_value():
    c = TTLCache(ttl=10, max_entries=8)
    c.set(("res.partner", ("string",)), {"x": 1})
    assert c.get(("res.partner", ("string",))) == {"x": 1}


def test_get_missing_returns_none():
    c = TTLCache(ttl=10, max_entries=8)
    assert c.get("nope") is None


def test_expired_entry_returns_none(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: clock["t"])
    c = TTLCache(ttl=10, max_entries=8)
    c.set("k", "v")
    assert c.get("k") == "v"
    clock["t"] += 11
    assert c.get("k") is None


def test_ttl_zero_always_misses():
    c = TTLCache(ttl=0, max_entries=8)
    c.set("k", "v")
    assert c.get("k") is None


def test_lru_evicts_oldest_past_max_entries():
    c = TTLCache(ttl=100, max_entries=2)
    c.set("a", 1)
    c.set("b", 2)
    c.get("a")           # 'a' is now most-recently-used
    c.set("c", 3)        # over max -> evict least-recently-used ('b')
    assert c.get("a") == 1
    assert c.get("b") is None
    assert c.get("c") == 3

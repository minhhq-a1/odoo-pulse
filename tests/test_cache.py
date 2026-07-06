# tests/test_cache.py
import threading

import odoo_pulse.cache as cache_mod
from odoo_pulse.cache import TTLCache


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


def test_cache_survives_concurrent_get_set():
    cache = TTLCache(ttl=60, max_entries=8)
    errors: list[BaseException] = []

    def hammer(seed: int) -> None:
        try:
            for i in range(2000):
                key = (seed + i) % 16
                cache.set(key, i)
                cache.get(key)
        except BaseException as exc:  # noqa: BLE001 - we want any crash
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(cache._store) <= 8

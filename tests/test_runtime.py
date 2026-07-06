"""Tests for the shared runtime helpers."""

from __future__ import annotations

import json
import threading

from odoo_pulse import runtime


def test_name_domain_empty_query():
    assert runtime.name_domain(None, ["name"]) == []
    assert runtime.name_domain("", ["name", "email"]) == []


def test_name_domain_single_field():
    assert runtime.name_domain("acme", ["name"]) == [("name", "ilike", "acme")]


def test_name_domain_multi_field_or():
    out = runtime.name_domain("acme", ["name", "email", "phone"])
    # Two OR operators for three terms, prefix-notation as Odoo expects.
    assert out == [
        "|",
        "|",
        ("name", "ilike", "acme"),
        ("email", "ilike", "acme"),
        ("phone", "ilike", "acme"),
    ]


def test_date_domain():
    assert runtime.date_domain("date", None, None) == []
    assert runtime.date_domain("date", "2026-01-01", None) == [("date", ">=", "2026-01-01")]
    assert runtime.date_domain("date", "2026-01-01", "2026-12-31") == [
        ("date", ">=", "2026-01-01"),
        ("date", "<=", "2026-12-31"),
    ]


def test_safe_serialises_result():
    out = runtime.safe(lambda: {"a": 1})
    assert json.loads(out) == {"a": 1}


def test_safe_catches_odoo_error():
    from odoo_pulse.odoo_client import OdooError

    def boom():
        raise OdooError("kaboom")

    out = json.loads(runtime.safe(boom))
    assert out == {"error": "kaboom"}


def test_preview_create_echoes_values():
    from odoo_pulse.runtime import preview
    out = preview("create", "crm.lead", values={"name": "X"})
    assert out["preview"] is True
    assert out["confirm_required"] is True
    assert out["action"] == "create"
    assert out["model"] == "crm.lead"
    assert out["values"] == {"name": "X"}
    assert "ids" not in out


def test_preview_update_includes_ids_count_affected():
    from odoo_pulse.runtime import preview
    out = preview("update", "crm.lead", ids=[1, 2], values={"name": "Y"}, affected=["A", "B"])
    assert out["ids"] == [1, 2]
    assert out["count"] == 2
    assert out["affected"] == ["A", "B"]
    assert out["values"] == {"name": "Y"}


def test_safe_serialises_unexpected_exceptions():
    def boom():
        raise KeyError("company_id")

    out = json.loads(runtime.safe(boom))
    assert out["error"].startswith("internal error: KeyError")


def test_get_client_is_singleton_under_concurrency(monkeypatch):
    created = []

    class _Cfg:
        @staticmethod
        def from_env():
            return object()

    class _Client:
        def __init__(self, cfg):
            created.append(self)

    monkeypatch.setattr(runtime, "OdooConfig", _Cfg)
    monkeypatch.setattr(runtime, "OdooClient", _Client)
    runtime._client = None

    barrier = threading.Barrier(8)
    results = []

    def grab():
        barrier.wait()
        results.append(runtime.get_client())

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    runtime._client = None
    assert len(created) == 1
    assert len(set(map(id, results))) == 1

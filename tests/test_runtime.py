"""Tests for the shared runtime helpers."""

from __future__ import annotations

import json

from odoo_mcp import runtime


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
    from odoo_mcp.odoo_client import OdooError

    def boom():
        raise OdooError("kaboom")

    out = json.loads(runtime.safe(boom))
    assert out == {"error": "kaboom"}

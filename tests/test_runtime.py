"""Tests for the shared runtime helpers."""

from __future__ import annotations

import json
import threading

import pytest

from odoo_pulse.common.dates import date_domain, parse_date_parameter
from odoo_pulse.common.domains import name_domain
from odoo_pulse.mcp import app
from odoo_pulse.mcp import runtime as mcp_runtime
from odoo_pulse.mcp.result import safe
from odoo_pulse.services.writes import preview


def test_name_domain_empty_query():
    assert name_domain(None, ["name"]) == []
    assert name_domain("", ["name", "email"]) == []


def test_name_domain_single_field():
    assert name_domain("acme", ["name"]) == [("name", "ilike", "acme")]


def test_name_domain_multi_field_or():
    out = name_domain("acme", ["name", "email", "phone"])
    # Two OR operators for three terms, prefix-notation as Odoo expects.
    assert out == [
        "|",
        "|",
        ("name", "ilike", "acme"),
        ("email", "ilike", "acme"),
        ("phone", "ilike", "acme"),
    ]


def test_date_domain():
    assert date_domain("date", None, None) == []
    assert date_domain("date", "2026-01-01", None) == [("date", ">=", "2026-01-01")]
    assert date_domain("date", "2026-01-01", "2026-12-31") == [
        ("date", ">=", "2026-01-01"),
        ("date", "<=", "2026-12-31"),
    ]


def test_datetime_domain_uses_exclusive_next_day():
    assert date_domain(
        "date_order", "2026-01-01", "2026-06-30", as_datetime=True
    ) == [
        ("date_order", ">=", "2026-01-01"),
        ("date_order", "<", "2026-07-01"),
    ]


def test_date_domain_rejects_invalid_iso_date():
    from odoo_pulse.core.errors import OdooError
    with pytest.raises(OdooError, match="date_to"):
        date_domain("date", None, "2026-06-30 trailing")


def test_parse_date_parameter_rejects_surrounding_whitespace():
    # Unlike common.dates.parse_period_date (whitespace-tolerant, exercised
    # in test_tools_reports_projects.py's test_validate_date_passthrough_and_error),
    # parse_date_parameter is the strict tool-parameter variant: a leading
    # or trailing space must not be silently trimmed away.
    from odoo_pulse.core.errors import OdooError
    with pytest.raises(OdooError, match="date_from"):
        parse_date_parameter(" 2026-07-01", "date_from")
    with pytest.raises(OdooError, match="date_from"):
        parse_date_parameter("2026-07-01 ", "date_from")


def test_safe_serialises_result():
    out = safe(lambda: {"a": 1})
    assert json.loads(out) == {"a": 1}


def test_safe_catches_odoo_error():
    from odoo_pulse.core.errors import OdooError

    def boom():
        raise OdooError("kaboom")

    out = json.loads(safe(boom))
    assert out == {"error": "kaboom"}


def test_preview_create_echoes_values():
    out = preview("create", "crm.lead", values={"name": "X"})
    assert out["preview"] is True
    assert out["confirm_required"] is True
    assert out["action"] == "create"
    assert out["model"] == "crm.lead"
    assert out["values"] == {"name": "X"}
    assert "ids" not in out


def test_preview_update_includes_ids_count_affected():
    out = preview("update", "crm.lead", ids=[1, 2], values={"name": "Y"}, affected=["A", "B"])
    assert out["ids"] == [1, 2]
    assert out["count"] == 2
    assert out["affected"] == ["A", "B"]
    assert out["values"] == {"name": "Y"}


def test_safe_serialises_unexpected_exceptions():
    def boom():
        raise KeyError("company_id")

    out = json.loads(safe(boom))
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

    monkeypatch.setattr(mcp_runtime, "OdooConfig", _Cfg)
    monkeypatch.setattr(mcp_runtime, "OdooClient", _Client)
    mcp_runtime._client = None

    barrier = threading.Barrier(8)
    results = []

    def grab():
        barrier.wait()
        results.append(mcp_runtime.get_client())

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    mcp_runtime._client = None
    assert len(created) == 1
    assert len(set(map(id, results))) == 1


def test_mcp_server_declares_disambiguation_instructions():
    text = app.mcp.instructions
    assert text
    # Identity: live business data...
    assert "Live business data" in text
    # ...and the not-for boundary vs code-index servers.
    assert "NOT for Odoo source-code" in text

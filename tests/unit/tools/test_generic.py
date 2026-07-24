"""Detailed tests for generic tools."""

from __future__ import annotations

import json

from odoo_pulse.tools import generic as tools_generic


def test_search_read_tool_forwards_args(fake_client):
    fake_client.search_responses["sale.order"] = [{"id": 1}]
    out = json.loads(
        tools_generic.search_read(
            "sale.order",
            domain=[("state", "=", "sale")],
            fields=["name"],
            limit=5,
            order="date_order desc",
        )
    )
    assert out == [{"id": 1}]
    call = fake_client.last("search_read")
    assert call["model"] == "sale.order"
    assert call["domain"] == [("state", "=", "sale")]
    assert call["fields"] == ["name"]
    assert call["order"] == "date_order desc"


def test_search_count_tool(fake_client):
    out = json.loads(tools_generic.search_count("res.partner"))
    assert out == {"count": 7}


def test_get_model_fields_filters(fake_client):
    out = json.loads(tools_generic.get_model_fields("res.partner", fields=["name"]))
    assert set(out) == {"name"}


def test_odoo_version_warns_below_18(fake_client):
    fake_client.major = 17
    out = json.loads(tools_generic.odoo_version())
    assert "warning" in out
    assert "Odoo 18+" in out["warning"]


def test_odoo_version_no_warning_on_18(fake_client):
    out = json.loads(tools_generic.odoo_version())
    assert "warning" not in out

"""Tests for the odoo://{model}/{id} MCP resource."""

from __future__ import annotations

import asyncio
import json

from odoo_pulse.mcp import resources
from odoo_pulse.mcp.app import mcp
from odoo_pulse.services.records import read_one


def test_odoo_record_found_returns_single_dict(fake_client):
    fake_client.read_responses["res.partner"] = [
        {"id": 5, "name": "Azure Interior"}
    ]
    out = json.loads(resources.odoo_record("res.partner", 5))
    # Single record dict, not a one-element list.
    assert out == {"id": 5, "name": "Azure Interior"}
    call = fake_client.last("read")
    assert call["model"] == "res.partner"
    assert call["ids"] == [5]
    assert call["fields"] is None


def test_odoo_record_not_found_returns_error_envelope(fake_client):
    # FakeClient.read returns [] for models with no canned response.
    out = json.loads(resources.odoo_record("res.partner", 999))
    assert "error" in out
    assert "res.partner" in out["error"]
    assert "999" in out["error"]


def test_odoo_record_client_error_becomes_error_envelope(fake_client):
    fake_client.raise_error = "Access Denied"
    out = json.loads(resources.odoo_record("res.partner", 5))
    assert out == {"error": "Access Denied"}


def test_odoo_record_template_is_registered():
    templates = asyncio.run(mcp.list_resource_templates())
    ours = [t for t in templates if t.uriTemplate == "odoo://{model}/{id}"]
    assert len(ours) == 1
    assert ours[0].mimeType == "application/json"


def test_read_one_returns_python_dict(fake_client):
    fake_client.read_responses["res.partner"] = [{"id": 5, "name": "Azure Interior"}]
    assert read_one(fake_client, "res.partner", 5) == {
        "id": 5,
        "name": "Azure Interior",
    }

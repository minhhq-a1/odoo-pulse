"""Tests for the write tools: confirm gate + domain helpers."""

from __future__ import annotations

import json

import pytest

from odoo_mcp import tools_write


def test_create_record_preview_does_no_write(fake_client):
    out = json.loads(tools_write.create_record("crm.lead", {"name": "X"}, confirm=False))
    assert out["preview"] is True
    assert out["model"] == "crm.lead"
    assert out["values"] == {"name": "X"}
    # No write call reached the client.
    assert [c["method"] for c in fake_client.calls] == []


def test_create_record_confirm_writes_once(fake_client):
    out = json.loads(tools_write.create_record("crm.lead", {"name": "X"}, confirm=True))
    assert out["created_id"] == 101
    create_calls = [c for c in fake_client.calls if c["method"] == "create"]
    assert len(create_calls) == 1
    assert create_calls[0]["model"] == "crm.lead"
    assert create_calls[0]["values"] == {"name": "X"}


def test_update_records_preview_reads_affected_no_write(fake_client):
    fake_client.read_responses["crm.lead"] = [{"id": 1, "display_name": "Lead A"}]
    out = json.loads(
        tools_write.update_records("crm.lead", [1], {"name": "Y"}, confirm=False)
    )
    assert out["preview"] is True
    assert out["affected"] == ["Lead A"]
    assert "write" not in [c["method"] for c in fake_client.calls]


def test_update_records_confirm_writes(fake_client):
    out = json.loads(
        tools_write.update_records("crm.lead", [1, 2], {"name": "Y"}, confirm=True)
    )
    assert out["updated"] is True
    assert fake_client.last("write")["values"] == {"name": "Y"}


def test_delete_records_confirm_unlinks(fake_client):
    out = json.loads(tools_write.delete_records("crm.lead", [3], confirm=True))
    assert out["deleted"] is True
    assert fake_client.last("unlink")["ids"] == [3]


def test_update_records_requires_ids(fake_client):
    out = json.loads(tools_write.update_records("crm.lead", [], {"name": "Y"}, confirm=True))
    assert "error" in out
    assert fake_client.calls == []

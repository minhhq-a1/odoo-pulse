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


def test_create_lead_builds_values_and_writes(fake_client):
    out = json.loads(
        tools_write.create_lead(
            "Big deal", contact_name="Jane", email="j@x.com", phone="123", confirm=True
        )
    )
    assert out["created_id"] == 101
    call = fake_client.last("create")
    assert call["model"] == "crm.lead"
    assert call["values"] == {
        "name": "Big deal",
        "contact_name": "Jane",
        "email_from": "j@x.com",
        "phone": "123",
    }


def test_create_lead_preview_no_write(fake_client):
    out = json.loads(tools_write.create_lead("Big deal", confirm=False))
    assert out["preview"] is True
    assert out["values"] == {"name": "Big deal"}
    assert fake_client.calls == []


def test_create_contact_company_flag(fake_client):
    out = json.loads(
        tools_write.create_contact("ACME", email="a@b.com", is_company=True, confirm=True)
    )
    assert out["created_id"] == 101
    call = fake_client.last("create")
    assert call["model"] == "res.partner"
    assert call["values"] == {"name": "ACME", "email": "a@b.com", "is_company": True}


def test_create_task_sets_project_and_assignee(fake_client):
    out = json.loads(
        tools_write.create_task("Do it", project_id=7, user_id=4, confirm=True)
    )
    assert out["created_id"] == 101
    call = fake_client.last("create")
    assert call["model"] == "project.task"
    assert call["values"] == {
        "name": "Do it",
        "project_id": 7,
        "user_ids": [(6, 0, [4])],
    }


def test_create_lead_merges_extra_values(fake_client):
    out = json.loads(
        tools_write.create_lead(
            "Big deal", extra_values={"presales_id": 5, "priority": "2"}, confirm=True
        )
    )
    assert out["created_id"] == 101
    call = fake_client.last("create")
    assert call["values"] == {"name": "Big deal", "presales_id": 5, "priority": "2"}


def test_create_lead_extra_values_shows_in_preview(fake_client):
    out = json.loads(
        tools_write.create_lead("Big deal", extra_values={"presales_id": 5}, confirm=False)
    )
    assert out["preview"] is True
    assert out["values"] == {"name": "Big deal", "presales_id": 5}
    assert fake_client.calls == []


def test_create_contact_merges_extra_values(fake_client):
    out = json.loads(
        tools_write.create_contact("ACME", extra_values={"vat": "VN123"}, confirm=True)
    )
    assert out["created_id"] == 101
    assert fake_client.last("create")["values"] == {"name": "ACME", "vat": "VN123"}


def test_create_task_merges_extra_values(fake_client):
    out = json.loads(
        tools_write.create_task(
            "Do it", project_id=7, extra_values={"tag_ids": [(6, 0, [1])]}, confirm=True
        )
    )
    assert out["created_id"] == 101
    assert fake_client.last("create")["values"] == {
        "name": "Do it",
        "project_id": 7,
        "tag_ids": [(6, 0, [1])],
    }


def test_extra_values_override_helper_built_fields(fake_client):
    # An explicit extra_values key wins over the helper's own mapping.
    out = json.loads(
        tools_write.create_lead(
            "Big deal", email="a@b.com", extra_values={"email_from": "override@b.com"},
            confirm=True,
        )
    )
    assert out["created_id"] == 101
    assert fake_client.last("create")["values"]["email_from"] == "override@b.com"


def test_confirm_sale_order_calls_action_confirm(fake_client):
    out = json.loads(tools_write.confirm_sale_order(9, confirm=True))
    assert out["confirmed"] is True
    call = fake_client.last("action_confirm")
    assert call["model"] == "sale.order"
    assert call["args"] == [[9]]


def test_confirm_sale_order_preview(fake_client):
    out = json.loads(tools_write.confirm_sale_order(9, confirm=False))
    assert out["preview"] is True
    assert out["ids"] == [9]
    assert fake_client.calls == []

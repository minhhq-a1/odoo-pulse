"""Tests for tools.reports.workflows: standup_digest."""

from __future__ import annotations

import json

from odoo_pulse.tools.reports import workflows as tools_workflows


def test_standup_digest_renders_markdown_header(fake_client):
    fake_client.search_responses["project.task"] = [
        {"id": 1, "name": "Late task", "user_ids": [10], "stage_id": [2, "In Progress"],
         "date_deadline": "2000-01-01", "priority": "1"},
    ]
    fake_client.execute_kw_responses[("res.users", "search_read")] = [
        {"id": 10, "name": "Alice"},
    ]
    out = tools_workflows.standup_digest("Acme")
    assert "## 🗓️ Daily Standup — Acme" in out
    assert "Quá hạn" in out          # the overdue section header
    assert "Alice" in out            # resolved assignee name


def test_standup_digest_warns_on_truncation(fake_client):
    # exactly max_records rows returned + a larger search_count => truncated
    fake_client.config.max_records = 2
    fake_client.search_responses["project.task"] = [
        {"id": 1, "name": "T1", "user_ids": [5], "stage_id": [1, "Doing"],
         "date_deadline": False, "priority": "0"},
        {"id": 2, "name": "T2", "user_ids": [5], "stage_id": [1, "Doing"],
         "date_deadline": False, "priority": "0"},
    ]
    fake_client.search_count_responses["project.task"] = 10
    fake_client.execute_kw_responses[("res.users", "search_read")] = [
        {"id": 5, "name": "An"}]

    out = tools_workflows.standup_digest("Acme")
    assert "⚠️" in out
    assert "10" in out


def test_standup_digest_matches_stage_by_name_not_internal_state(fake_client):
    # A task whose internal state happens to be "1_done" but whose stage is
    # not one of exclude_stages must still count as open -- state must not
    # substitute for the documented stage-name match.
    fake_client.fields_responses["project.task"] = {
        "state": {"type": "selection"}}
    fake_client.search_responses["project.task"] = [{
        "id": 1, "name": "Still open", "user_ids": [10],
        "stage_id": [9, "In Progress"], "state": "1_done",
        "date_deadline": False, "priority": "0",
    }]
    fake_client.execute_kw_responses[("res.users", "search_read")] = [
        {"id": 10, "name": "Alice"},
    ]
    out = tools_workflows.standup_digest("Acme")
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read" and c["model"] == "project.task")
    assert ("stage_id.name", "not in", ["Done", "Cancelled", "Delivered"]) \
        in call["domain"]
    assert not any(leaf[0] == "state" for leaf in call["domain"]
                   if isinstance(leaf, tuple))
    assert "Still open" in out


def test_standup_digest_shaping_bug_returns_json_error(fake_client):
    # a task row missing user_ids triggers a shaping KeyError path safely
    fake_client.search_responses["project.task"] = [
        {"id": 1, "name": "T1", "stage_id": [1, "Doing"],
         "date_deadline": False, "priority": "0"}]
    out = tools_workflows.standup_digest("Acme")
    # must never raise; either a rendered digest or a JSON error payload
    assert isinstance(out, str)
    if out.startswith("{"):
        assert "error" in json.loads(out)

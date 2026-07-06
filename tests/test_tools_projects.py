"""Tests for tools_projects: list_tasks subtask filtering."""

from __future__ import annotations

import json

from odoo_pulse import tools_projects, tools_workflows


def test_list_tasks_default_excludes_subtasks(fake_client):
    """Default call must add parent_id = False to domain."""
    tools_projects.list_tasks()
    call = fake_client.last("search_read")
    assert call["model"] == "project.task"
    assert ("parent_id", "=", False) in call["domain"]


def test_list_tasks_include_subtasks_removes_parent_filter(fake_client):
    """include_subtasks=True must NOT add a parent_id filter."""
    tools_projects.list_tasks(include_subtasks=True)
    call = fake_client.last("search_read")
    parent_filters = [t for t in call["domain"] if isinstance(t, tuple) and t[0] == "parent_id"]
    assert parent_filters == [], f"Unexpected parent_id filter: {parent_filters}"


def test_list_tasks_returns_parent_id_field(fake_client):
    """parent_id must always be in the requested fields."""
    tools_projects.list_tasks()
    call = fake_client.last("search_read")
    assert "parent_id" in call["fields"]


def test_list_tasks_include_subtasks_returns_valid_json(fake_client):
    out = tools_projects.list_tasks(include_subtasks=True)
    json.loads(out)


def test_list_tasks_offset_forwarded(fake_client):
    """offset must be passed through to search_read for pagination."""
    tools_projects.list_tasks(offset=200, limit=200)
    call = fake_client.last("search_read")
    assert call["offset"] == 200
    assert call["limit"] == 200


def test_list_tasks_other_filters_still_apply_with_subtasks(fake_client):
    """project / assignee / stage filters compose correctly alongside include_subtasks."""
    tools_projects.list_tasks(
        project="MyProject", assignee="Alice", stage="In Progress", include_subtasks=True
    )
    call = fake_client.last("search_read")
    domain = call["domain"]
    assert ("project_id.name", "ilike", "MyProject") in domain
    assert ("user_ids.name", "ilike", "Alice") in domain
    assert ("stage_id.name", "ilike", "In Progress") in domain
    # No parent filter when include_subtasks=True
    assert not any(isinstance(t, tuple) and t[0] == "parent_id" for t in domain)


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
    from odoo_pulse import tools_workflows

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

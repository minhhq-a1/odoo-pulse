# tests/test_project_budget_matching.py
"""Lock the canonical budget-matching helpers (Plan 3.5 Task 4).

Pure function tests -- no client, fake or real, is needed. These pin the
Odoo prefix-notation domain shape and the authoritative row-assignment
rules (direct project link wins; an out-of-scope link must not fall
through to the account; an unlinked/shared account maps to every
requested project) so Task 5's consumer migration has a locked contract
to switch onto.
"""

from odoo_pulse.services.projects.budget import (
    budget_match_domain,
    project_ids_for_budget_row,
)


def test_match_domain_project_only():
    assert budget_match_domain(
        [1, 2], [], "project_id", "account_id"
    ) == [("project_id", "in", [1, 2])]


def test_match_domain_account_only():
    assert budget_match_domain(
        [], [11, 12], "project_id", "account_id"
    ) == [("account_id", "in", [11, 12])]


def test_match_domain_combines_direct_and_unlinked_account_rows():
    assert budget_match_domain(
        [1, 2], [11, 12], "project_id", "account_id"
    ) == [
        "|",
        ("project_id", "in", [1, 2]),
        "&",
        ("project_id", "=", False),
        ("account_id", "in", [11, 12]),
    ]


def test_direct_project_link_is_authoritative():
    row = {"project_id": [1, "Alpha"], "account_id": [11, "Shared"]}
    assert project_ids_for_budget_row(
        row,
        requested_project_ids={1, 2},
        project_ids_by_account={11: [1, 2]},
        link_field="project_id",
        account_field="account_id",
    ) == [1]


def test_out_of_scope_project_link_does_not_leak_through_account():
    row = {"project_id": [99, "Outside"], "account_id": [11, "Shared"]}
    assert project_ids_for_budget_row(
        row,
        requested_project_ids={1, 2},
        project_ids_by_account={11: [1, 2]},
        link_field="project_id",
        account_field="account_id",
    ) == []


def test_unlinked_shared_account_maps_to_every_requested_project():
    row = {"project_id": False, "account_id": [11, "Shared"]}
    assert project_ids_for_budget_row(
        row,
        requested_project_ids={1, 2},
        project_ids_by_account={11: [1, 2]},
        link_field="project_id",
        account_field="account_id",
    ) == [1, 2]

from odoo_pulse.services.projects.queries import (
    milestones_by_project,
    project_domain,
)


def test_project_domain_preserves_all_filters_and_exclusions():
    assert project_domain(
        project="Alpha", manager="Mai", customer="Acme",
        include_on_hold=False, include_done=False,
    ) == [
        ("active", "=", True),
        ("name", "ilike", "Alpha"),
        ("user_id.name", "ilike", "Mai"),
        ("partner_id.name", "ilike", "Acme"),
        ("last_update_status", "!=", "done"),
        ("last_update_status", "!=", "on_hold"),
    ]


def test_milestones_by_project_joins_by_id_and_ignores_missing_project():
    rows = [
        {"id": 1, "project_id": [7, "Same Name"]},
        {"id": 2, "project_id": [8, "Same Name"]},
        {"id": 3, "project_id": False},
    ]
    assert milestones_by_project(rows) == {
        7: [rows[0]],
        8: [rows[1]],
    }

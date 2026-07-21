import json

from odoo_pulse import tools_project_detail, tools_reports_projects, tools_workflows


def reset_calls(fake_client):
    fake_client.calls.clear()
    fake_client.search_responses_seq.clear()
    fake_client.aggregate_responses_seq.clear()


def project_row():
    return {
        "id": 1, "name": "Alpha", "user_id": [7, "PM"],
        "partner_id": [8, "Customer"], "company_id": [1, "Main Co"],
        "date_start": "2026-01-01", "date": "2020-01-01",
        "task_count": 3, "last_update_status": "on_track",
        "allocated_hours": 100.0, "delivery_hours": 20.0,
        "account_id": [11, "AA Alpha"], "active": True,
    }


def test_health_is_consistent_across_status_dashboard_and_portfolio(fake_client):
    fake_client.fields_responses["project.project"] = {
        "allocated_hours": {}, "delivery_hours": {}, "account_id": {},
    }
    fake_client.search_responses["project.project"] = [project_row()]
    fake_client.search_responses["project.milestone"] = [{
        "id": 10, "name": "Late", "deadline": "2020-02-01",
        "is_reached": False, "project_id": [1, "Alpha"],
    }]
    fake_client.search_responses["account.analytic.line"] = []
    fake_client.error_models.update({"budget.line", "crossovered.budget.lines"})

    status = json.loads(tools_workflows.project_status_report())
    status_row = status["breakdown"]["by_project"][0]

    reset_calls(fake_client)
    dashboard = json.loads(
        tools_project_detail.project_dashboard(project_id=1, include=["core"])
    )

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [[]]
    portfolio = json.loads(tools_project_detail.portfolio_health())
    portfolio_row = portfolio["projects"][0]

    assert status_row["project_id"] == dashboard["project"]["id"] \
        == portfolio_row["project_id"] == 1
    assert status_row["derived_health"] == dashboard["project"]["derived_health"] \
        == portfolio_row["derived_health"] == "off_track"
    assert status_row["native_status"] == dashboard["project"]["native_status"] \
        == portfolio_row["native_status"] == "on_track"
    assert status_row["overdue_milestones"] == dashboard["milestones"]["overdue"] \
        == portfolio_row["overdue_milestones"] == 1


def seed_budget(fake_client):
    fake_client.fields_responses["project.project"] = {"account_id": {}}
    fake_client.search_responses["project.project"] = [project_row()]
    fake_client.error_models.add("budget.line")
    fake_client.fields_responses["crossovered.budget.lines"] = {
        "project_id": {}, "analytic_account_id": {}, "planned_amount": {},
        "practical_amount": {}, "crossovered_budget_id": {},
        "date_from": {}, "date_to": {},
    }
    fake_client.search_responses["crossovered.budget.lines"] = [{
        "id": 20, "project_id": [1, "Alpha"],
        "analytic_account_id": [11, "AA Alpha"],
        "crossovered_budget_id": [7, "Budget Alpha"],
        "planned_amount": -100.0, "practical_amount": -40.0,
        "date_from": "2026-01-01", "date_to": "2026-12-31",
    }]
    fake_client.fields_responses["crossovered.budget"] = {
        "date_from": {}, "date_to": {}, "state": {},
    }
    fake_client.search_responses["crossovered.budget"] = [{
        "id": 7, "name": "Budget Alpha", "date_from": "2026-01-01",
        "date_to": "2026-12-31", "state": "validate",
    }]
    fake_client.search_responses["account.analytic.line"] = []


def test_planned_and_practical_match_budget_report_and_dashboard(fake_client):
    seed_budget(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"account_id": [11, "AA Alpha"], "amount:sum": -40.0}],
    ]
    budget = json.loads(tools_reports_projects.project_budget(project="Alpha"))
    budget_row = budget["breakdown"]["projects"][0]

    reset_calls(fake_client)
    dashboard = json.loads(tools_project_detail.project_dashboard(
        project_id=1, include=["budgets", "budget_detail"]
    ))
    detail = dashboard["budget_detail"]

    assert budget_row["project_id"] == dashboard["project_id"] == 1
    assert budget_row["planned"] == detail["planned"] == 100.0
    assert budget_row["practical"] == detail["practical"] == 40.0


def seed_profitability(fake_client):
    fake_client.fields_responses["project.project"] = {
        "allocated_hours": {}, "delivery_hours": {}, "account_id": {},
    }
    fake_client.fields_responses["account.analytic.line"] = {"project_id": {}}
    fake_client.search_responses["project.project"] = [project_row()]
    fake_client.search_responses["project.milestone"] = []
    fake_client.search_responses["account.analytic.line"] = []
    fake_client.error_models.update({"budget.line", "crossovered.budget.lines"})


def analytic_rows():
    return [
        [{"project_id": [1, "Alpha"], "unit_amount:sum": 10.0}],
        [{"account_id": [11, "AA Alpha"], "amount:sum": -40.0}],
        [{"account_id": [11, "AA Alpha"], "amount:sum": 100.0}],
    ]


def test_revenue_cost_margin_match_profitability_dashboard_and_portfolio(fake_client):
    seed_profitability(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        *analytic_rows(), [], [],
    ]
    profitability = json.loads(
        tools_reports_projects.project_profitability(project="Alpha")
    )
    profit_row = profitability["breakdown"]["projects"][0]

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = analytic_rows()[1:]
    dashboard = json.loads(
        tools_project_detail.project_dashboard(project_id=1, include=["core"])
    )

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = analytic_rows()
    portfolio = json.loads(tools_project_detail.portfolio_health())
    portfolio_row = portfolio["projects"][0]

    assert profit_row["project_id"] == dashboard["project"]["id"] \
        == portfolio_row["project_id"] == 1
    assert profit_row["revenue"] == dashboard["finance"]["revenue"] \
        == portfolio_row["revenue"] == 100.0
    assert profit_row["cost"] == dashboard["finance"]["cost_all_time"] \
        == portfolio_row["cost"] == 40.0
    assert profit_row["margin"] == dashboard["finance"]["margin"] \
        == portfolio_row["margin"] == 60.0

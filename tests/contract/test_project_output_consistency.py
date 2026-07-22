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


def seed_profitability_classified(fake_client):
    """Like seed_profitability, but the instance exposes
    analytic_profitability -- the odoo_profitability classifier path,
    not the amount-sign fallback, decides cost vs revenue here."""
    fake_client.fields_responses["project.project"] = {
        "allocated_hours": {}, "delivery_hours": {}, "account_id": {},
    }
    fake_client.fields_responses["account.analytic.line"] = {
        "project_id": {}, "analytic_profitability": {},
    }
    fake_client.search_responses["project.project"] = [project_row()]
    fake_client.search_responses["project.milestone"] = []
    fake_client.search_responses["account.analytic.line"] = []
    fake_client.error_models.update({"budget.line", "crossovered.budget.lines"})


def test_expense_credit_nets_cost_across_profitability_dashboard_and_portfolio(
        fake_client):
    # An expense credit note (-100 + 20, both loss-classified) nets to a
    # single -80 aggregate row on the loss domain; no revenue-classified
    # rows at all. cost must come out 80 (not clamped/absolute-valued away
    # from a genuine net), revenue 0, margin -80, everywhere.
    seed_profitability_classified(fake_client)

    def rows():
        return [
            [{"project_id": [1, "Alpha"], "unit_amount:sum": 10.0}],  # hours
            [{"account_id": [11, "AA Alpha"], "amount:sum": -80.0}],  # loss
            [],  # revenue: no rows
        ]

    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        *rows(), [], [],
    ]
    profitability = json.loads(
        tools_reports_projects.project_profitability(project="Alpha")
    )
    profit_row = profitability["breakdown"]["projects"][0]

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = rows()[1:]
    dashboard = json.loads(
        tools_project_detail.project_dashboard(project_id=1, include=["core"])
    )

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = rows()
    portfolio = json.loads(tools_project_detail.portfolio_health())
    portfolio_row = portfolio["projects"][0]

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = rows()[1:]
    budget = json.loads(
        tools_reports_projects.project_budget(project="Alpha")
    )
    budget_row = budget["breakdown"]["projects"][0]

    # build_budget_detail reads RAW account.analytic.line rows via
    # search_read -- a FakeClient channel independent of
    # aggregate_responses_seq -- scoped to task_id != False (no budget
    # period narrows it further here: no budget model resolves under
    # error_models, so selected budgets/periods are empty and the read is
    # all-time). Every row below carries a truthy task_id so this raw
    # population describes the SAME accounting facts as the
    # account-grouped aggregate above (-100 loss, +20 loss -> net -80 ->
    # cost 80), making the cross-output equality intentional rather than
    # comparing an all-time population against a period-scoped one.
    fake_client.search_responses["account.analytic.line"] = [
        {"id": 901, "date": "2026-01-01", "amount": -100.0,
         "unit_amount": 1.0, "employee_id": False, "task_id": [50, "T"],
         "analytic_profitability": "loss"},
        {"id": 902, "date": "2026-01-02", "amount": 20.0,
         "unit_amount": 0.5, "employee_id": False, "task_id": [50, "T"],
         "analytic_profitability": "loss"},
    ]
    reset_calls(fake_client)
    dashboard_budget = json.loads(
        tools_project_detail.project_dashboard(
            project_id=1, include=["budgets", "budget_detail"])
    )
    detail = dashboard_budget["budget_detail"]

    assert profit_row["cost"] == dashboard["finance"]["cost_all_time"] \
        == portfolio_row["cost"] == budget_row["cost"] \
        == budget["summary"]["cost"] == detail["valid_cost"] == 80.0
    assert profit_row["revenue"] == dashboard["finance"]["revenue"] \
        == portfolio_row["revenue"] == 0.0
    assert profit_row["margin"] == dashboard["finance"]["margin"] \
        == portfolio_row["margin"] == -80.0
    assert dashboard["finance"]["analytic_classification"] == "odoo_profitability"
    assert budget["analytic_classification"] == "odoo_profitability"
    assert detail["analytic_classification"] == "odoo_profitability"
    assert not any(r["code"] == "analytic_classification_fallback"
                   for r in profitability["risks"])
    assert not any(r["code"] == "analytic_classification_fallback"
                   for r in portfolio["risks"])
    assert not any(r["code"] == "analytic_classification_fallback"
                   for r in budget["risks"])
    assert "warnings" not in dashboard
    assert "warnings" not in dashboard_budget


def test_income_credit_note_nets_revenue_across_profitability_dashboard_and_portfolio(
        fake_client):
    # An income credit note (+100 - 20, both revenue-classified) nets to a
    # single 80 aggregate row on the revenue domain; no loss-classified
    # rows at all. cost 0, revenue 80, margin 80, everywhere.
    seed_profitability_classified(fake_client)

    def rows():
        return [
            [{"project_id": [1, "Alpha"], "unit_amount:sum": 10.0}],  # hours
            [],  # loss: no rows
            [{"account_id": [11, "AA Alpha"], "amount:sum": 80.0}],  # revenue
        ]

    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        *rows(), [], [],
    ]
    profitability = json.loads(
        tools_reports_projects.project_profitability(project="Alpha")
    )
    profit_row = profitability["breakdown"]["projects"][0]

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = rows()[1:]
    dashboard = json.loads(
        tools_project_detail.project_dashboard(project_id=1, include=["core"])
    )

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = rows()
    portfolio = json.loads(tools_project_detail.portfolio_health())
    portfolio_row = portfolio["projects"][0]

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = rows()[1:]
    budget = json.loads(
        tools_reports_projects.project_budget(project="Alpha")
    )
    budget_row = budget["breakdown"]["projects"][0]

    # Same two independent FakeClient channels as the expense-credit test:
    # aggregate_responses_seq feeds the account-grouped aggregate consumers
    # above, search_responses feeds build_budget_detail's raw-row read.
    # Both rows carry a truthy task_id and are revenue-classified, so
    # valid_cost must come out 0 -- a revenue-classified credit note must
    # never enter cost.
    fake_client.search_responses["account.analytic.line"] = [
        {"id": 903, "date": "2026-01-01", "amount": 100.0,
         "unit_amount": 1.0, "employee_id": False, "task_id": [51, "T"],
         "analytic_profitability": "revenue"},
        {"id": 904, "date": "2026-01-02", "amount": -20.0,
         "unit_amount": 0.5, "employee_id": False, "task_id": [51, "T"],
         "analytic_profitability": "revenue"},
    ]
    reset_calls(fake_client)
    dashboard_budget = json.loads(
        tools_project_detail.project_dashboard(
            project_id=1, include=["budgets", "budget_detail"])
    )
    detail = dashboard_budget["budget_detail"]

    assert profit_row["cost"] == dashboard["finance"]["cost_all_time"] \
        == portfolio_row["cost"] == budget_row["cost"] \
        == budget["summary"]["cost"] == detail["valid_cost"] == 0.0
    assert profit_row["revenue"] == dashboard["finance"]["revenue"] \
        == portfolio_row["revenue"] == 80.0
    assert profit_row["margin"] == dashboard["finance"]["margin"] \
        == portfolio_row["margin"] == 80.0
    assert dashboard["finance"]["analytic_classification"] == "odoo_profitability"
    assert budget["analytic_classification"] == "odoo_profitability"
    assert detail["analytic_classification"] == "odoo_profitability"
    assert not any(r["code"] == "analytic_classification_fallback"
                   for r in profitability["risks"])
    assert not any(r["code"] == "analytic_classification_fallback"
                   for r in portfolio["risks"])
    assert not any(r["code"] == "analytic_classification_fallback"
                   for r in budget["risks"])
    assert "warnings" not in dashboard
    assert "warnings" not in dashboard_budget


# -- Task 5: shared matching / sign-separated magnitudes, across consumers ----

def seed_partial_links(fake_client):
    """crossovered.budget.lines exposes BOTH a (custom) project_id link and
    the classic analytic_account_id -- three lines on the same account: one
    directly linked to project 1, one unlinked (falls through to the
    account), and one directly linked to a DIFFERENT project (99) that
    happens to share the same account. planned_amount <= 0 keeps this a
    single-sign source (crossovered's own domain), isolating the
    partial-link assignment behaviour from the mixed-sign one below.
    """
    fake_client.fields_responses["project.project"] = {"account_id": {}}
    fake_client.search_responses["project.project"] = [project_row()]
    fake_client.error_models.add("budget.line")
    fake_client.fields_responses["crossovered.budget.lines"] = {
        "project_id": {}, "analytic_account_id": {}, "planned_amount": {},
        "practical_amount": {}, "crossovered_budget_id": {},
        "date_from": {}, "date_to": {},
    }
    fake_client.search_responses["crossovered.budget.lines"] = [
        {"id": 20, "project_id": [1, "Alpha"],
         "analytic_account_id": [11, "AA Alpha"],
         "crossovered_budget_id": [7, "Budget Alpha"],
         "planned_amount": -60.0, "practical_amount": -20.0,
         "date_from": "2026-01-01", "date_to": "2026-12-31"},
        {"id": 21, "project_id": False,
         "analytic_account_id": [11, "AA Alpha"],
         "crossovered_budget_id": [7, "Budget Alpha"],
         "planned_amount": -40.0, "practical_amount": -10.0,
         "date_from": "2026-01-01", "date_to": "2026-12-31"},
        # Truthy link to project 99 (out of scope) on the SAME account:
        # must contribute nowhere in project 1's outputs.
        {"id": 22, "project_id": [99, "Zeta"],
         "analytic_account_id": [11, "AA Alpha"],
         "crossovered_budget_id": [7, "Budget Alpha"],
         "planned_amount": -99999.0, "practical_amount": -99999.0,
         "date_from": "2026-01-01", "date_to": "2026-12-31"},
    ]
    fake_client.fields_responses["crossovered.budget"] = {
        "date_from": {}, "date_to": {}, "state": {},
    }
    fake_client.search_responses["crossovered.budget"] = [{
        "id": 7, "name": "Budget Alpha", "date_from": "2026-01-01",
        "date_to": "2026-12-31", "state": "validate",
    }]
    fake_client.search_responses["account.analytic.line"] = []


def partial_link_agg_rows():
    """Same three lines, aggregate-shaped (":sum" suffix) -- fed to the
    budget_by_project consumers (profitability, portfolio_health). The
    FakeClient does not apply the query domain, so the out-of-scope
    project-99 row is deliberately included here too: only the
    canonical assignment helper (not the domain) is what must reject it.
    """
    return [
        {"project_id": [1, "Alpha"], "analytic_account_id": [11, "AA Alpha"],
         "planned_amount:sum": -60.0},
        {"project_id": False, "analytic_account_id": [11, "AA Alpha"],
         "planned_amount:sum": -40.0},
        {"project_id": [99, "Zeta"], "analytic_account_id": [11, "AA Alpha"],
         "planned_amount:sum": -99999.0},
    ]


def test_partial_project_links_match_across_budget_consumers(fake_client):
    """A direct project-linked row (-60) and a falsy-project/account-fallback
    row (-40) on the requested project's account must ADD to 100 across
    every budget consumer -- project_budget, project_profitability,
    project_dashboard's budget_detail and portfolio_health -- while a
    truthy row linked to a different project (99) sharing the same account
    contributes nowhere. This fails under the old project-level "project
    wins" precedence (which drops the unlinked row entirely once a link
    field exists) and under any regression that lets an out-of-scope
    direct link leak through the shared account.
    """
    seed_partial_links(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [[], []]
    budget = json.loads(
        tools_reports_projects.project_budget(project="Alpha"))
    budget_row = budget["breakdown"]["projects"][0]

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [], [], [], [], []]
    fake_client.aggregate_responses_seq["crossovered.budget.lines"] = [
        partial_link_agg_rows()]
    profitability = json.loads(
        tools_reports_projects.project_profitability(project="Alpha"))
    profit_row = profitability["breakdown"]["projects"][0]

    reset_calls(fake_client)
    dashboard = json.loads(tools_project_detail.project_dashboard(
        project_id=1, include=["budgets", "budget_detail"]))
    detail = dashboard["budget_detail"]

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [[], [], []]
    fake_client.aggregate_responses_seq["crossovered.budget.lines"] = [
        partial_link_agg_rows()]
    portfolio = json.loads(tools_project_detail.portfolio_health())
    portfolio_row = portfolio["projects"][0]

    assert budget_row["planned"] == 100.0
    assert profit_row["budget"] == 100.0
    assert detail["planned"] == 100.0
    assert portfolio_row["budget"] == 100.0


def seed_mixed_sign(fake_client):
    """budget.line (budget_type != revenue semantics) carries two lines on
    the SAME project: -100 (expense) and +60 (a positive/revenue-tagged
    amount the != "revenue" filter still admits through a mixed budget).
    Its own extra_domain has no <= 0 leaf, so budget_by_project must query
    non-positive THEN positive and add both magnitudes.
    """
    fake_client.fields_responses["project.project"] = {"account_id": {}}
    fake_client.search_responses["project.project"] = [project_row()]
    fake_client.error_models.add("crossovered.budget.lines")
    fake_client.fields_responses["budget.line"] = {
        "project_id": {}, "account_id": {}, "budget_amount": {},
        "practical_amount": {}, "budget_analytic_id": {},
        "date_from": {}, "date_to": {},
    }
    fake_client.search_responses["budget.line"] = [
        {"id": 30, "project_id": [1, "Alpha"],
         "account_id": [11, "AA Alpha"],
         "budget_analytic_id": [7, "Budget Alpha"],
         "budget_amount": -100.0, "practical_amount": -100.0,
         "date_from": "2026-01-01", "date_to": "2026-12-31"},
        {"id": 31, "project_id": [1, "Alpha"],
         "account_id": [11, "AA Alpha"],
         "budget_analytic_id": [7, "Budget Alpha"],
         "budget_amount": 60.0, "practical_amount": 60.0,
         "date_from": "2026-01-01", "date_to": "2026-12-31"},
    ]
    fake_client.fields_responses["budget.analytic"] = {
        "date_from": {}, "date_to": {}, "state": {},
    }
    fake_client.search_responses["budget.analytic"] = [{
        "id": 7, "name": "Budget Alpha", "date_from": "2026-01-01",
        "date_to": "2026-12-31", "state": "validate",
    }]
    fake_client.search_responses["account.analytic.line"] = []


def test_mixed_sign_budget_magnitude_matches_across_budget_consumers(
        fake_client):
    """-100 and +60 on the same project must add to 160 -- never
    abs(sum()) == 40 -- across every budget consumer. Raw consumers
    (project_budget, project_dashboard's budget_detail) already sum
    abs() per line; aggregate consumers (project_profitability,
    portfolio_health) must query and sum the two signs separately to
    reach the same total.
    """
    seed_mixed_sign(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [[], []]
    budget = json.loads(
        tools_reports_projects.project_budget(project="Alpha"))
    budget_row = budget["breakdown"]["projects"][0]

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [], [], [], [], []]
    fake_client.aggregate_responses_seq["budget.line"] = [
        [{"project_id": [1, "Alpha"], "account_id": [11, "AA Alpha"],
          "budget_amount:sum": -100.0}],
        [{"project_id": [1, "Alpha"], "account_id": [11, "AA Alpha"],
          "budget_amount:sum": 60.0}],
    ]
    profitability = json.loads(
        tools_reports_projects.project_profitability(project="Alpha"))
    profit_row = profitability["breakdown"]["projects"][0]

    reset_calls(fake_client)
    dashboard = json.loads(tools_project_detail.project_dashboard(
        project_id=1, include=["budgets", "budget_detail"]))
    detail = dashboard["budget_detail"]

    reset_calls(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [[], [], []]
    fake_client.aggregate_responses_seq["budget.line"] = [
        [{"project_id": [1, "Alpha"], "account_id": [11, "AA Alpha"],
          "budget_amount:sum": -100.0}],
        [{"project_id": [1, "Alpha"], "account_id": [11, "AA Alpha"],
          "budget_amount:sum": 60.0}],
    ]
    portfolio = json.loads(tools_project_detail.portfolio_health())
    portfolio_row = portfolio["projects"][0]

    assert budget_row["planned"] == 160.0
    assert profit_row["budget"] == 160.0
    assert detail["planned"] == 160.0
    assert portfolio_row["budget"] == 160.0

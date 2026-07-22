# tests/test_tools_project_detail.py
import json

from odoo_pulse.services.projects.budget import (
    build_budget_context,
    build_budget_detail,
    select_budgets,
)
from odoo_pulse.services.projects.dashboard import (
    build_core_section,
    build_hours_section,
    weekly_logged,
)
from odoo_pulse.services.projects.finance import FALLBACK_WARNING
from odoo_pulse.tools_project_detail import (
    portfolio_health,
    project_dashboard,
    project_subtask_hours,
)

_TASK_SCHEMA = {
    "name": {"type": "char"}, "user_ids": {"type": "many2many"},
    "date_end": {"type": "datetime"}, "delivery_hours": {"type": "float"},
    "allocated_hours": {"type": "float"}, "effective_hours": {"type": "float"},
}


def _seed_tasks(fake, schema=None):
    fake.fields_responses["project.task"] = schema or dict(_TASK_SCHEMA)
    fake.search_responses["project.task"] = [
        {"id": 1, "user_ids": [11], "date_end": "2025-10-05 10:00:00",
         "delivery_hours": 10.0, "allocated_hours": 8.0,
         "effective_hours": 9.5},
        {"id": 2, "user_ids": [11, 12], "date_end": "2025-10-20 10:00:00",
         "delivery_hours": 5.0, "allocated_hours": 4.0,
         "effective_hours": 4.5},
        {"id": 3, "user_ids": [], "date_end": False,
         "delivery_hours": 2.0, "allocated_hours": 1.0,
         "effective_hours": 1.5},
    ]


def test_subtask_hours_envelope_and_totals(fake_client):
    _seed_tasks(fake_client)
    out = json.loads(project_subtask_hours(project_id=59))
    assert out["tool"] == "project_subtask_hours"
    assert out["project_id"] == 59
    assert "as_of" in out
    assert out["totals"] == {"task_count": 3, "delivery_hours": 17.0,
                             "allocated_hours": 13.0,
                             "effective_hours": 15.5}
    assert "by_month" not in out          # group_by_month off
    assert "warnings" not in out          # all fields present
    assert out["filters"]["single_assignee_only"] is False


def test_subtask_hours_single_call_no_client_side_paging(fake_client):
    _seed_tasks(fake_client)
    json.loads(project_subtask_hours(
        project_id=59, only_closed_stages=True,
        single_assignee_only=True))
    reads = [c for c in fake_client.calls if c["method"] == "search_read"
             and c["model"] == "project.task"]
    assert len(reads) == 1  # everything in one server-side fetch


def test_subtask_hours_group_by_month(fake_client):
    _seed_tasks(fake_client)
    out = json.loads(project_subtask_hours(project_id=59,
                                           group_by_month=True))
    assert [r["month"] for r in out["by_month"]] == ["2025-10"]
    assert out["no_date_end"]["task_count"] == 1
    assert out["no_date_end"]["delivery_hours"] == 2.0


def test_subtask_hours_missing_delivery_field_warns(fake_client):
    schema = dict(_TASK_SCHEMA)
    del schema["delivery_hours"]
    _seed_tasks(fake_client, schema=schema)
    out = json.loads(project_subtask_hours(project_id=59))
    assert out["totals"]["delivery_hours"] is None
    assert out["warnings"] == \
        ["field delivery_hours does not exist on project.task"]


def test_subtask_hours_bad_period_is_clean_error(fake_client):
    _seed_tasks(fake_client)
    out = json.loads(project_subtask_hours(
        project_id=59, periods=[{"date_from": "garbage"}]))
    assert "error" in out
    assert "date_from" in out["error"]


def test_module_registered_in_reports_group():
    from odoo_pulse.mcp.registry import GROUP_MODULES
    assert "tools_project_detail" in GROUP_MODULES["reports"]


_PROJECT_SCHEMA = {
    "name": {"type": "char"}, "user_id": {"type": "many2one"},
    "partner_id": {"type": "many2one"}, "date": {"type": "date"},
    "task_count": {"type": "integer"},
    "last_update_status": {"type": "selection"},
    "delivery_hours": {"type": "float"},
    "account_id": {"type": "many2one"},
}

_MILESTONE_SCHEMA = {
    "name": {"type": "char"}, "deadline": {"type": "date"},
    "is_reached": {"type": "boolean"},
}


def _seed_core(fake):
    fake.fields_responses["project.project"] = dict(_PROJECT_SCHEMA)
    fake.fields_responses["project.milestone"] = dict(_MILESTONE_SCHEMA)
    fake.search_responses["project.project"] = [
        {"id": 59, "name": "The Body Shop", "user_id": [7, "Minh"],
         "partner_id": False, "date": "2026-07-31", "task_count": 744,
         "last_update_status": "off_track", "delivery_hours": 1500.0,
         "account_id": [5, "AA TBS"]},
    ]
    fake.search_responses["project.milestone"] = [
        {"id": 1, "name": "1.2 Go-live", "deadline": "2026-01-16",
         "is_reached": False},
        {"id": 2, "name": "Kickoff", "deadline": "2025-04-01",
         "is_reached": True},
    ]
    fake.aggregate_responses_seq["account.analytic.line"] = [
        [{"account_id": [5, "AA TBS"], "amount:sum": -1000.0}],  # cost
        [{"account_id": [5, "AA TBS"], "amount:sum": 200.0}],    # revenue
    ]
    fake.search_responses["account.analytic.line"] = [
        {"id": 900, "date": "2026-07-13", "unit_amount": 4.0},
        {"id": 901, "date": "2026-07-14", "unit_amount": 3.5},
        {"id": 902, "date": "2026-07-06", "unit_amount": 8.0},
    ]


def test_core_section_shape(fake_client):
    _seed_core(fake_client)
    core = build_core_section(fake_client, 59, 7, 7)
    p = core["project"]
    assert p["id"] == 59 and p["name"] == "The Body Shop"
    assert p["manager"] == "Minh" and p["customer"] is None
    assert p["end_date"] == "2026-07-31" and p["task_count"] == 744
    assert p["native_status"] == "off_track"
    assert p["derived_health"] == "off_track"   # overdue Go-live
    assert p["divergent"] is False
    assert p["delivery_hours"] == 1500.0
    ms = core["milestones"]
    assert ms["reached"] == 1 and ms["total"] == 2 and ms["overdue"] == 1
    assert ms["next_unreached"]["name"] == "1.2 Go-live"
    assert len(ms["list"]) == 2
    fin = core["finance"]
    # Default fake schema has no analytic_profitability field -> the
    # classifier degrades to the amount-sign fallback (still cost 1000 /
    # revenue 200 for these seeded amounts) and reports it via a warning.
    assert fin == {"revenue": 200.0, "cost_all_time": 1000.0,
                   "margin": -800.0, "analytic_classification": "sign_fallback"}
    assert core["warnings"] == [FALLBACK_WARNING]


def test_core_section_missing_project_raises(fake_client):
    fake_client.fields_responses["project.project"] = dict(_PROJECT_SCHEMA)
    fake_client.search_responses["project.project"] = []
    import pytest
    from odoo_pulse.core.errors import OdooError
    with pytest.raises(OdooError, match="No project.project with id 999"):
        build_core_section(fake_client, 999, 7, 7)


def test_core_section_missing_delivery_hours_warns(fake_client):
    _seed_core(fake_client)
    schema = dict(_PROJECT_SCHEMA)
    del schema["delivery_hours"]
    fake_client.fields_responses["project.project"] = schema
    core = build_core_section(fake_client, 59, 7, 7)
    assert core["project"]["delivery_hours"] is None
    # both the missing-field warning and the analytic classifier's
    # sign-fallback warning (default fake schema lacks
    # analytic_profitability) are present.
    assert core["warnings"] == \
        ["field delivery_hours does not exist on project.project",
         FALLBACK_WARNING]


def test_core_section_finance_soft_fails_independently(fake_client):
    _seed_core(fake_client)
    # malformed aggregate row -> TypeError inside analytic_money, NOT an
    # OdooError; weekly_logged reads account.analytic.line via search_read
    # (a separate FakeClient queue) so it is unaffected.
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"account_id": [5, "AA TBS"], "amount:sum": "not-a-number"}],
    ]
    core = build_core_section(fake_client, 59, 7, 7)
    assert "project" in core and core["project"]["id"] == 59
    assert "milestones" in core
    assert "finance" not in core
    assert core["errors"]["finance"].startswith("internal error: TypeError")
    assert core["weekly_logged"] == [
        {"week_start": "2026-07-06", "hours": 8.0},
        {"week_start": "2026-07-13", "hours": 7.5},
    ]


def test_core_section_weekly_logged_soft_fails_independently(fake_client):
    _seed_core(fake_client)
    fake_client.error_models.add("account.analytic.line")
    core = build_core_section(fake_client, 59, 7, 7)
    assert "project" in core and core["project"]["id"] == 59
    assert "milestones" in core
    assert "weekly_logged" not in core
    assert core["errors"]["weekly_logged"] == \
        "Object account.analytic.line doesn't exist"
    # finance also reads account.analytic.line via aggregate_records, which
    # now honors error_models too (matching real Odoo: an uninstalled
    # module's model fails read_group/formatted_read_group the same as
    # search_read) -- so it soft-fails alongside weekly_logged.
    assert "finance" not in core
    assert core["errors"]["finance"] == \
        "Object account.analytic.line doesn't exist"


def test_weekly_logged_iso_monday_buckets(fake_client):
    import datetime as dt
    fake_client.search_responses["account.analytic.line"] = [
        {"id": 1, "date": "2026-07-13", "unit_amount": 4.0},   # Mon
        {"id": 2, "date": "2026-07-14", "unit_amount": 3.5},   # Tue same wk
        {"id": 3, "date": "2026-07-06", "unit_amount": 8.0},   # prev week
    ]
    weeks = weekly_logged(fake_client, 59, dt.date(2026, 7, 15))
    assert weeks == [
        {"week_start": "2026-07-06", "hours": 8.0},
        {"week_start": "2026-07-13", "hours": 7.5},
    ]
    call = fake_client.last("search_read")
    assert ("date", ">=", "2026-04-22") in call["domain"]   # today - 84d


def test_hours_section_totals_and_leaderboards(fake_client):
    fake_client.fields_responses["project.task"] = {
        "user_ids": {"type": "many2many"}, "date_end": {"type": "datetime"},
        "delivery_hours": {"type": "float"},
        "allocated_hours": {"type": "float"},
        "effective_hours": {"type": "float"},
    }
    fake_client.search_responses["project.task"] = [
        {"id": 1, "user_ids": [11], "date_end": False,
         "delivery_hours": 10.0, "allocated_hours": 8.0,
         "effective_hours": 9.0},
    ]
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"employee_id": [155, "Nguyễn Văn A"], "unit_amount:sum": 320.5}],
        [{"task_id": [8554, "Build X"], "unit_amount:sum": 84.0}],
    ]
    out = build_hours_section(fake_client, 59, False, None, False, 7)
    h = out["hours"]
    assert h["subtask_delivery"] == 10.0
    assert h["by_employee"] == [{"employee_id": 155,
                                 "employee": "Nguyễn Văn A",
                                 "hours": 320.5}]
    assert h["by_task"] == [{"task_id": 8554, "task": "Build X",
                             "hours": 84.0}]


_LINE_SCHEMA = {
    "planned_amount": {"type": "float"},
    "practical_amount": {"type": "float"},
    "analytic_account_id": {"type": "many2one"},
    "crossovered_budget_id": {"type": "many2one"},
    "date_from": {"type": "date"}, "date_to": {"type": "date"},
}

_BUDGET_SCHEMA = {
    "name": {"type": "char"}, "date_from": {"type": "date"},
    "date_to": {"type": "date"}, "state": {"type": "selection"},
}


def _seed_budget(fake):
    fake.major = 18
    fake.fields_responses["project.project"] = dict(_PROJECT_SCHEMA)
    fake.search_responses["project.project"] = [
        {"id": 59, "name": "The Body Shop", "account_id": [5, "AA TBS"]}]
    # candidate probe: budget.line missing, crossovered present
    fake.error_models.add("budget.line")
    fake.fields_responses["crossovered.budget.lines"] = dict(_LINE_SCHEMA)
    fake.search_responses["crossovered.budget.lines"] = [
        {"id": 1, "planned_amount": -1593314320.0,
         "practical_amount": -1735766746.0,
         "analytic_account_id": [5, "AA TBS"],
         "crossovered_budget_id": [12, "PASX TBS"],
         "date_from": "2025-03-01", "date_to": "2026-07-31"},
    ]
    fake.fields_responses["crossovered.budget"] = dict(_BUDGET_SCHEMA)
    fake.search_responses["crossovered.budget"] = [
        {"id": 12, "name": "PASX TBS", "date_from": "2025-03-01",
         "date_to": "2026-07-31", "state": "validate"}]


def test_budget_context_lists_budgets(fake_client):
    _seed_budget(fake_client)
    ctx = build_budget_context(fake_client, 59)
    assert ctx["available"] is True
    assert ctx["budgets"] == [{"id": 12, "name": "PASX TBS",
                               "date_from": "2025-03-01",
                               "date_to": "2026-07-31",
                               "state": "validate"}]
    assert ctx["parent_field"] == "crossovered_budget_id"


def test_budget_context_excludes_revenue_lines_from_fetch(fake_client):
    # crossovered.budget.lines can carry a Revenue-category line alongside
    # Expense lines (general_budget_id="Revenue", positive planned_amount).
    # Summing abs() over both inflates planned/practical -- must be
    # excluded at the fetch domain, same as the budget.line candidate
    # already excludes revenue via budget_analytic_id.budget_type.
    _seed_budget(fake_client)
    build_budget_context(fake_client, 59)
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read"
                and c["model"] == "crossovered.budget.lines")
    assert ("planned_amount", "<=", 0) in call["domain"]


def test_budget_context_includes_zero_planned_expense_budgets(fake_client):
    # A "practical-only" budget records actuals but was never planned: its
    # line has planned_amount == 0 (e.g. "KFC - PRE-SALES", project 114).
    # A strict `planned_amount < 0` filter drops that line, so its parent
    # budget never surfaces in ctx["budgets"] and project_dashboard reports
    # the budget id as "match no budget". `<= 0` keeps zero-planned Expense
    # lines while still excluding positive Revenue lines (see the test
    # above), so such budgets stay selectable.
    _seed_budget(fake_client)
    build_budget_context(fake_client, 59)
    call = next(c for c in fake_client.calls
                if c["method"] == "search_read"
                and c["model"] == "crossovered.budget.lines")
    assert ("planned_amount", "<", 0) not in call["domain"]
    assert ("planned_amount", "<=", 0) in call["domain"]


def test_budget_context_accepts_prefetched_project_row(fake_client):
    _seed_budget(fake_client)
    row = {"id": 59, "name": "The Body Shop", "account_id": [5, "AA TBS"]}
    ctx = build_budget_context(fake_client, 59, project_row=row)
    assert ctx["available"] is True
    assert ctx["budgets"] == [{"id": 12, "name": "PASX TBS",
                               "date_from": "2025-03-01",
                               "date_to": "2026-07-31",
                               "state": "validate"}]
    proj_reads = [c for c in fake_client.calls
                  if c["method"] == "search_read"
                  and c["model"] == "project.project"]
    assert proj_reads == []              # no re-fetch: the row was given


def test_selected_none_vs_empty_list(fake_client):
    _seed_budget(fake_client)
    ctx = build_budget_context(fake_client, 59)
    ids_all, periods_all, unknown_all = select_budgets(ctx, None)
    assert ids_all == [12]
    assert periods_all == [{"date_from": "2025-03-01",
                            "date_to": "2026-07-31"}]
    assert unknown_all == []
    ids_none, periods_none, unknown_none = select_budgets(ctx, [])
    assert ids_none == [] and periods_none == [] and unknown_none == []


def test_selected_reports_unknown_ids(fake_client):
    _seed_budget(fake_client)
    ctx = build_budget_context(fake_client, 59)
    selected, periods, unknown = select_budgets(ctx, [12, 999])
    assert selected == [12]
    assert unknown == [999]
    assert periods == [{"date_from": "2025-03-01", "date_to": "2026-07-31"}]


def test_budget_detail_signs_and_periods(fake_client):
    _seed_budget(fake_client)
    ctx = build_budget_context(fake_client, 59)
    fake_client.search_responses["account.analytic.line"] = [
        {"id": 1, "date": "2025-10-03", "amount": -210500000.0,
         "unit_amount": 890.0, "employee_id": [155, "A"],
         "task_id": [8554, "Build X"]},
        # credit line REDUCES cost (positive amount)
        {"id": 2, "date": "2025-10-20", "amount": 500000.0,
         "unit_amount": 0.0, "employee_id": [155, "A"],
         "task_id": [8554, "Build X"]},
    ]
    detail = build_budget_detail(fake_client, 59, ctx, None, 7)
    assert detail["selected_budget_ids"] == [12]
    assert detail["planned"] == 1593314320.0     # abs of negative planned
    assert detail["practical"] == 1735766746.0
    assert detail["date_from"] == "2025-03-01"
    assert detail["date_to"] == "2026-07-31"
    assert detail["valid_cost"] == 210000000.0   # 210.5M - 0.5M credit
    assert detail["valid_hours"] == 890.0
    assert detail["by_month"] == [{"month": "2025-10",
                                   "cost": 210000000.0, "hours": 890.0}]
    assert detail["by_employee"][0]["employee_id"] == 155
    assert detail["by_task"][0]["task_id"] == 8554
    # domain: task-linked lines only, plain-date period bounds
    call = fake_client.last("search_read")
    assert ("task_id", "!=", False) in call["domain"]
    assert ("date", ">=", "2025-03-01") in call["domain"]
    assert ("date", "<=", "2026-07-31") in call["domain"]


def test_budget_detail_empty_selection_all_time_cost(fake_client):
    _seed_budget(fake_client)
    ctx = build_budget_context(fake_client, 59)
    fake_client.search_responses["account.analytic.line"] = [
        {"id": 1, "date": "2020-01-01", "amount": -100.0,
         "unit_amount": 1.0, "employee_id": False, "task_id": [9, "T"]},
    ]
    detail = build_budget_detail(fake_client, 59, ctx, [], 7)
    assert detail["selected_budget_ids"] == []
    assert detail["planned"] == 0.0
    assert detail["valid_cost"] == 100.0         # no period filter
    call = fake_client.last("search_read")
    assert not any(leaf[0] == "date" for leaf in call["domain"]
                   if isinstance(leaf, tuple))
    assert "unknown_budget_ids" not in detail    # nothing stale to report


def test_budget_detail_surfaces_unknown_budget_ids(fake_client):
    _seed_budget(fake_client)
    ctx = build_budget_context(fake_client, 59)
    fake_client.search_responses["account.analytic.line"] = []
    detail = build_budget_detail(fake_client, 59, ctx, [12, 999], 7)
    assert detail["selected_budget_ids"] == [12]
    assert detail["unknown_budget_ids"] == [999]


def _seed_dashboard(fake):
    _seed_core(fake)
    _seed_budget(fake)          # overwrites project.project rows: re-seed
    fake.search_responses["project.project"] = [
        {"id": 59, "name": "The Body Shop", "user_id": [7, "Minh"],
         "partner_id": False, "date": "2026-07-31", "task_count": 744,
         "last_update_status": "off_track", "delivery_hours": 1500.0,
         "account_id": [5, "AA TBS"]},
    ]
    fake.fields_responses["project.task"] = dict(_TASK_SCHEMA)
    fake.search_responses["project.task"] = [
        {"id": 1, "user_ids": [11], "date_end": "2025-10-05 10:00:00",
         "delivery_hours": 10.0, "allocated_hours": 8.0,
         "effective_hours": 9.5},
    ]


def test_dashboard_full_load_all_sections(fake_client):
    _seed_dashboard(fake_client)
    # analytic aggregates consumed in fixed order:
    # core.finance (cost, revenue), hours (by_employee, by_task)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"account_id": [5, "AA TBS"], "amount:sum": -1000.0}],
        [{"account_id": [5, "AA TBS"], "amount:sum": 200.0}],
        [{"employee_id": [155, "A"], "unit_amount:sum": 320.5}],
        [{"task_id": [8554, "T"], "unit_amount:sum": 84.0}],
    ]
    out = json.loads(project_dashboard(project_id=59))
    assert out["tool"] == "project_dashboard"
    for key in ("project", "milestones", "finance", "weekly_logged",
                "hours", "budgets", "budget_detail", "delivery_monthly"):
        assert key in out, key
    assert "errors" not in out
    assert out["project"]["id"] == 59
    assert out["budgets"][0]["id"] == 12
    assert out["budget_detail"]["selected_budget_ids"] == [12]
    # core's project.project row is reused by build_budget_context instead of
    # being fetched a second time (finding #8).
    proj_reads = [c for c in fake_client.calls
                  if c["method"] == "search_read"
                  and c["model"] == "project.project"]
    assert len(proj_reads) == 1


def test_dashboard_include_subset_only_requested_sections(fake_client):
    _seed_dashboard(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"employee_id": [155, "A"], "unit_amount:sum": 320.5}],
        [{"task_id": [8554, "T"], "unit_amount:sum": 84.0}],
    ]
    out = json.loads(project_dashboard(
        project_id=59, include=["hours", "delivery_monthly"]))
    assert "hours" in out and "delivery_monthly" in out
    assert "project" not in out and "budget_detail" not in out
    assert "finance" not in out


def test_dashboard_unknown_include_is_clean_error(fake_client):
    out = json.loads(project_dashboard(project_id=59,
                                       include=["bogus"]))
    assert "error" in out and "bogus" in out["error"]


def test_dashboard_section_soft_fail(fake_client):
    _seed_dashboard(fake_client)
    # core fails BEFORE its finance aggregates run (milestone fetch
    # raises), so the queue below is consumed by the hours section only.
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"employee_id": [155, "A"], "unit_amount:sum": 320.5}],
        [{"task_id": [8554, "T"], "unit_amount:sum": 84.0}],
    ]
    fake_client.error_models.add("project.milestone")
    out = json.loads(project_dashboard(project_id=59))
    assert "core" in out["errors"]
    assert "hours" in out            # other sections still present
    assert "budgets" in out


def test_dashboard_delivery_monthly_respects_selected_budget_periods(
        fake_client):
    # NOTE: this test previously asserted a date_end domain leaf on the
    # project.task search_read. As of the shared-subtask-fetch refactor
    # (finding #6), delivery_monthly filters by period in Python
    # (filter_subtasks_by_periods) instead of via a fetch_subtasks(periods=)
    # domain, so it can share one unfiltered fetch with the hours section.
    # This test now asserts the filtered RESULT and the single-fetch
    # guarantee instead of the (now nonexistent) domain leaf.
    _seed_dashboard(fake_client)
    fake_client.search_responses["project.task"] = [
        {"id": 1, "user_ids": [11], "date_end": "2025-10-05 10:00:00",
         "delivery_hours": 10.0, "allocated_hours": 8.0,
         "effective_hours": 9.5},
        {"id": 2, "user_ids": [11], "date_end": "2024-01-01 10:00:00",
         "delivery_hours": 3.0, "allocated_hours": 2.0,
         "effective_hours": 2.5},   # before the PASX TBS period: excluded
    ]
    fake_client.aggregate_responses_seq["account.analytic.line"] = []
    out = json.loads(project_dashboard(
        project_id=59, include=["budgets", "delivery_monthly"]))
    # PASX TBS period is 2025-03-01..2026-07-31 (+7): only the in-period
    # task contributes.
    assert out["delivery_monthly"] == [
        {"month": "2025-10", "delivery_hours": 10.0}]
    task_reads = [c for c in fake_client.calls
                  if c["method"] == "search_read"
                  and c["model"] == "project.task"]
    assert len(task_reads) == 1          # one shared fetch, not re-fetched
    assert not any(leaf[0] == "date_end" for leaf in task_reads[0]["domain"]
                   if isinstance(leaf, tuple))


def test_dashboard_shared_subtask_fetch_fails_both_sections(fake_client):
    _seed_dashboard(fake_client)
    fake_client.error_models.add("project.task")
    out = json.loads(project_dashboard(
        project_id=59, include=["hours", "delivery_monthly"]))
    assert "hours" not in out and "delivery_monthly" not in out
    assert out["errors"]["hours"] == out["errors"]["delivery_monthly"]
    assert out["errors"]["hours"] == "Object project.task doesn't exist"


def test_dashboard_hours_and_delivery_monthly_share_one_fetch(fake_client):
    _seed_dashboard(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"account_id": [5, "AA TBS"], "amount:sum": -1000.0}],
        [{"account_id": [5, "AA TBS"], "amount:sum": 200.0}],
        [{"employee_id": [155, "A"], "unit_amount:sum": 320.5}],
        [{"task_id": [8554, "T"], "unit_amount:sum": 84.0}],
    ]
    json.loads(project_dashboard(
        project_id=59, include=["core", "hours", "delivery_monthly"]))
    task_reads = [c for c in fake_client.calls
                  if c["method"] == "search_read"
                  and c["model"] == "project.task"]
    assert len(task_reads) == 1


def test_dashboard_only_closed_stages_uses_state_domain_shared_fetch(
        fake_client):
    _seed_dashboard(fake_client)
    fake_client.fields_responses["project.task"] = {
        **_TASK_SCHEMA, "state": {"type": "selection"}}
    fake_client.search_responses["project.task"] = [
        {"id": 1, "user_ids": [11], "date_end": "2025-10-05 10:00:00",
         "state": "1_done",
         "delivery_hours": 10.0, "allocated_hours": 8.0,
         "effective_hours": 9.5},
    ]
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"employee_id": [155, "A"], "unit_amount:sum": 320.5}],
        [{"task_id": [8554, "T"], "unit_amount:sum": 84.0}],
    ]
    json.loads(project_dashboard(
        project_id=59, only_closed_stages=True,
        include=["hours", "delivery_monthly"]))
    task_reads = [c for c in fake_client.calls
                  if c["method"] == "search_read"
                  and c["model"] == "project.task"]
    assert len(task_reads) == 1          # hours + delivery share one fetch
    assert ("state", "in", ["1_done", "1_canceled"]) \
        in task_reads[0]["domain"]


def test_dashboard_warns_on_unknown_budget_ids(fake_client):
    _seed_dashboard(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"account_id": [5, "AA TBS"], "amount:sum": -1000.0}],
        [{"account_id": [5, "AA TBS"], "amount:sum": 200.0}],
        [{"employee_id": [155, "A"], "unit_amount:sum": 320.5}],
        [{"task_id": [8554, "T"], "unit_amount:sum": 84.0}],
    ]
    out = json.loads(project_dashboard(project_id=59, budget_ids=[12, 999]))
    assert out["budget_detail"]["unknown_budget_ids"] == [999]
    assert any("999" in w for w in out["warnings"])


def test_dashboard_warns_on_unknown_budget_ids_without_budget_detail(
        fake_client):
    # The warning must fire regardless of which budget_ids-consuming
    # section was requested -- a stale id should not go unnoticed just
    # because budget_detail wasn't in `include` this call.
    _seed_dashboard(fake_client)
    fake_client.aggregate_responses_seq["account.analytic.line"] = []
    out = json.loads(project_dashboard(
        project_id=59, budget_ids=[12, 999],
        include=["budgets", "delivery_monthly"]))
    assert "budget_detail" not in out
    assert any("999" in w for w in out["warnings"])


def test_dashboard_budget_context_failure_lands_on_every_budget_section(
        fake_client):
    # build_budget_context feeds budgets, budget_detail AND delivery_monthly;
    # when it fails, every requested one must land in errors -- a
    # requested section must never vanish from both the report and
    # errors (same fan-out contract as the shared sub-task fetch).
    _seed_dashboard(fake_client)
    # no core in include -> build_budget_context self-fetches project.project,
    # which is the call made to fail here.
    fake_client.error_models.add("project.project")
    out = json.loads(project_dashboard(
        project_id=59,
        include=["budgets", "budget_detail", "delivery_monthly"]))
    for section in ("budgets", "budget_detail", "delivery_monthly"):
        assert section not in out
        assert out["errors"][section] == \
            "Object project.project doesn't exist"


def test_dashboard_prefixes_non_odoo_errors_as_internal(fake_client):
    _seed_dashboard(fake_client)
    fake_client.search_responses["project.milestone"] = [
        {"id": 1, "name": "Bad", "deadline": "not-a-date",
         "is_reached": False},
    ]
    out = json.loads(project_dashboard(project_id=59, include=["core"]))
    assert out["errors"]["core"].startswith("internal error: ValueError")


def test_dashboard_core_finance_and_weekly_logged_fail_independently(
        fake_client):
    _seed_dashboard(fake_client)
    fake_client.error_models.add("account.analytic.line")
    out = json.loads(project_dashboard(project_id=59, include=["core"]))
    # project + milestones still return: the project itself was found
    assert out["project"]["id"] == 59
    assert "milestones" in out
    assert "weekly_logged" not in out
    # finance also reads account.analytic.line via aggregate_records, which
    # now honors error_models too (matching real Odoo: an uninstalled
    # module's model fails read_group/formatted_read_group the same as
    # search_read) -- so it soft-fails alongside weekly_logged.
    assert "finance" not in out
    assert "core" not in out["errors"]
    assert out["errors"]["weekly_logged"] == \
        "Object account.analytic.line doesn't exist"
    assert out["errors"]["finance"] == \
        "Object account.analytic.line doesn't exist"


def test_portfolio_health_joins_by_id_two_projects_same_name(fake_client):
    fake_client.fields_responses["project.project"] = dict(_PROJECT_SCHEMA)
    fake_client.search_responses["project.project"] = [
        {"id": 1, "name": "Internal", "user_id": [7, "PM A"],
         "partner_id": False, "date": False, "task_count": 5,
         "last_update_status": "on_track", "delivery_hours": 0.0,
         "account_id": [101, "AA-1"]},
        {"id": 2, "name": "Internal", "user_id": [8, "PM B"],
         "partner_id": False, "date": False, "task_count": 9,
         "last_update_status": "on_track", "delivery_hours": 0.0,
         "account_id": [102, "AA-2"]},
    ]
    fake_client.search_responses["project.milestone"] = []
    # order: hours by project, then analytic_money (cost, revenue)
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"project_id": [1, "Internal"], "unit_amount:sum": 10.0},
         {"project_id": [2, "Internal"], "unit_amount:sum": 20.0}],
        [{"account_id": [101, "AA-1"], "amount:sum": -500.0}],
        [{"account_id": [102, "AA-2"], "amount:sum": 700.0}],
    ]
    # no usable budget model
    fake_client.error_models.add("budget.line")
    fake_client.error_models.add("crossovered.budget.lines")
    out = json.loads(portfolio_health())
    rows = out["projects"]
    assert len(rows) == 2                       # NOT merged by name
    assert {r["project_id"] for r in rows} == {1, 2}
    assert all(r["project"] == "Internal" for r in rows)
    by_id = {r["project_id"]: r for r in rows}
    assert by_id[1]["cost"] == 500.0            # positive cost
    assert by_id[2]["revenue"] == 700.0
    assert by_id[1]["budget"] is None           # budgets unavailable
    assert out["tool"] == "portfolio_health"


def test_portfolio_health_budget_excludes_revenue_lines(fake_client):
    # Same crossovered.budget.lines revenue-exclusion rule as
    # project_dashboard/project_budget must hold for portfolio_health's
    # budget_burn_pct (budget_by_project) -- one shared candidate list,
    # one shared bug surface.
    fake_client.fields_responses["project.project"] = dict(_PROJECT_SCHEMA)
    fake_client.search_responses["project.project"] = [
        {"id": 1, "name": "Alpha", "user_id": False, "partner_id": False,
         "date": False, "task_count": 1, "last_update_status": "on_track",
         "account_id": [101, "AA-1"]},
    ]
    fake_client.search_responses["project.milestone"] = []
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [], [], [],
    ]
    fake_client.error_models.add("budget.line")
    fake_client.fields_responses["crossovered.budget.lines"] = {
        "analytic_account_id": {"type": "many2one"},
        "planned_amount": {"type": "float"},
    }
    json.loads(portfolio_health())
    call = next(c for c in fake_client.calls
                if c["method"] == "aggregate_records"
                and c["model"] == "crossovered.budget.lines")
    assert ("planned_amount", "<=", 0) in call["domain"]


def test_portfolio_health_sorts_riskiest_first_and_filters(fake_client):
    fake_client.fields_responses["project.project"] = dict(_PROJECT_SCHEMA)
    fake_client.search_responses["project.project"] = [
        {"id": 1, "name": "Alpha", "user_id": False, "partner_id": False,
         "date": False, "task_count": 1,
         "last_update_status": "on_track", "account_id": False},
        {"id": 2, "name": "Beta", "user_id": False, "partner_id": False,
         "date": False, "task_count": 1,
         "last_update_status": "on_track", "account_id": False},
    ]
    fake_client.search_responses["project.milestone"] = [
        {"id": 9, "name": "Late", "deadline": "2020-01-01",
         "is_reached": False, "project_id": [2, "Beta"]},
    ]
    fake_client.aggregate_responses_seq["account.analytic.line"] = [[]]
    fake_client.error_models.add("budget.line")
    fake_client.error_models.add("crossovered.budget.lines")
    out = json.loads(portfolio_health(manager="PM", include_done=False))
    rows = out["projects"]
    assert rows[0]["project_id"] == 2           # off_track first
    assert rows[0]["derived_health"] == "off_track"
    proj_call = next(c for c in fake_client.calls
                     if c["method"] == "search_read"
                     and c["model"] == "project.project")
    assert ("user_id.name", "ilike", "PM") in proj_call["domain"]
    assert ("last_update_status", "!=", "done") in proj_call["domain"]
    assert any(r["code"] == "overdue_milestones" for r in out["risks"])


def test_portfolio_health_degrades_on_milestone_truncation(fake_client):
    fake_client.fields_responses["project.project"] = dict(_PROJECT_SCHEMA)
    fake_client.search_responses["project.project"] = [
        {"id": 1, "name": "Alpha", "user_id": False, "partner_id": False,
         "date": False, "task_count": 1,
         "last_update_status": "on_track", "account_id": False},
    ]
    fake_client.search_responses["project.milestone"] = [
        {"id": 100 + i, "name": f"M{i}", "deadline": "2026-12-01",
         "is_reached": True, "project_id": [1, "Alpha"]}
        for i in range(200)
    ]
    fake_client.search_count_responses["project.milestone"] = 205
    fake_client.aggregate_responses_seq["account.analytic.line"] = [[]]
    fake_client.error_models.add("budget.line")
    fake_client.error_models.add("crossovered.budget.lines")
    out = json.loads(portfolio_health())
    assert "error" not in out                   # degrades, does not fail
    assert len(out["projects"]) == 1
    codes = {r["code"]: r for r in out["risks"]}
    assert codes["truncated_milestone_data"]["count"] == 5

# tests/test_project_shared.py
import datetime as dt

import pytest

from odoo_pulse.odoo_client import OdooError
from odoo_pulse.project_shared import (
    DEFAULT_CLOSED_STAGES,
    account_field_of,
    account_id_of,
    account_ids_by_project,
    analytic_money,
    derive_project_health,
    fetch_subtasks,
    filter_subtasks_by_periods,
    periods_domain,
    subtasks_by_month,
    sum_hours,
)


# -- periods_domain ----------------------------------------------------------

def test_periods_domain_empty():
    assert periods_domain("date_end", None, 7) == []
    assert periods_domain("date_end", [], 7) == []


def test_periods_domain_single_range_datetime_bounds():
    dom = periods_domain(
        "date_end", [{"date_from": "2025-03-01", "date_to": "2026-07-31"}], 7)
    # local 2025-03-01 00:00:00 (+7) == 2025-02-28 17:00:00 UTC
    # local 2026-07-31 23:59:59 (+7) == 2026-07-31 16:59:59 UTC
    assert dom == [
        ("date_end", ">=", "2025-02-28 17:00:00"),
        ("date_end", "<=", "2026-07-31 16:59:59"),
    ]


def test_periods_domain_two_ranges_or_not_union():
    dom = periods_domain(
        "date_end",
        [{"date_from": "2025-01-01", "date_to": "2025-01-31"},
         {"date_from": "2025-06-01", "date_to": "2025-06-30"}],
        0)
    assert dom == [
        "|",
        "&", ("date_end", ">=", "2025-01-01 00:00:00"),
             ("date_end", "<=", "2025-01-31 23:59:59"),
        "&", ("date_end", ">=", "2025-06-01 00:00:00"),
             ("date_end", "<=", "2025-06-30 23:59:59"),
    ]


def test_periods_domain_date_mode_plain_strings():
    dom = periods_domain(
        "date", [{"date_from": "2025-03-01", "date_to": "2026-07-31"}], 7,
        as_datetime=False)
    assert dom == [("date", ">=", "2025-03-01"), ("date", "<=", "2026-07-31")]


def test_periods_domain_open_ended_side():
    dom = periods_domain("date", [{"date_from": "2025-03-01"}], 7,
                         as_datetime=False)
    assert dom == [("date", ">=", "2025-03-01")]


def test_periods_domain_rejects_garbage_and_empty_period():
    with pytest.raises(OdooError, match="date_from"):
        periods_domain("date", [{"date_from": "notadate"}], 7)
    with pytest.raises(OdooError, match="periods\\[0\\]"):
        periods_domain("date", [{}], 7)


def test_periods_domain_rejects_trailing_garbage_after_valid_date():
    # a valid date PREFIX followed by garbage must not silently truncate
    # to the valid part and pass.
    with pytest.raises(OdooError, match="date_from"):
        periods_domain(
            "date", [{"date_from": "2025-01-01xyz"}], 7)


# -- fetch_subtasks, sum_hours, subtasks_by_month ----------------------------

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
        {"id": 4, "user_ids": [13], "date_end": "2025-11-01 02:00:00",
         "delivery_hours": 7.0, "allocated_hours": 6.0,
         "effective_hours": 6.5},
    ]


def test_fetch_subtasks_domain_and_no_filters(fake_client):
    _seed_tasks(fake_client)
    tasks, available, warnings = fetch_subtasks(fake_client, 59)
    call = fake_client.last("search_read")
    assert call["model"] == "project.task"
    assert ("project_id", "=", 59) in call["domain"]
    assert ("parent_id", "!=", False) in call["domain"]
    assert len(tasks) == 4
    assert available == ["delivery_hours", "allocated_hours",
                         "effective_hours"]
    assert warnings == []


def test_fetch_subtasks_closed_stage_domain_default_and_custom(fake_client):
    _seed_tasks(fake_client)
    fetch_subtasks(fake_client, 59, only_closed_stages=True)
    call = fake_client.last("search_read")
    assert ("stage_id.name", "in", list(DEFAULT_CLOSED_STAGES)) \
        in call["domain"]
    fetch_subtasks(fake_client, 59, only_closed_stages=True,
                   closed_stage_names=["Hoàn thành"])
    call = fake_client.last("search_read")
    assert ("stage_id.name", "in", ["Hoàn thành"]) in call["domain"]


def test_fetch_subtasks_uses_state_for_localized_closed_stage(fake_client):
    fake_client.fields_responses["project.task"] = {
        **_TASK_SCHEMA, "state": {"type": "selection"}}
    fake_client.search_responses["project.task"] = [{
        "id": 1, "user_ids": [11], "stage_id": [9, "Hoàn tất"],
        "state": "1_done", "date_end": False,
        "delivery_hours": 2.0, "allocated_hours": 2.0,
        "effective_hours": 2.0,
    }]
    tasks, _, _ = fetch_subtasks(
        fake_client, 59, only_closed_stages=True)
    assert [task["id"] for task in tasks] == [1]
    assert ("state", "in", ["1_done", "1_canceled"]) \
        in fake_client.last("search_read")["domain"]


def test_fetch_subtasks_single_assignee_zero_one_two(fake_client):
    _seed_tasks(fake_client)
    tasks, _, _ = fetch_subtasks(fake_client, 59,
                                 single_assignee_only=True)
    # id=1 (one assignee) and id=4 kept; id=2 (two) and id=3 (zero) dropped
    assert [t["id"] for t in tasks] == [1, 4]


def test_fetch_subtasks_periods_land_on_date_end(fake_client):
    _seed_tasks(fake_client)
    fetch_subtasks(
        fake_client, 59,
        periods=[{"date_from": "2025-10-01", "date_to": "2025-10-31"}],
        timezone_offset=7)
    call = fake_client.last("search_read")
    assert ("date_end", ">=", "2025-09-30 17:00:00") in call["domain"]
    assert ("date_end", "<=", "2025-10-31 16:59:59") in call["domain"]


def test_fetch_subtasks_missing_delivery_hours_degrades(fake_client):
    schema = dict(_TASK_SCHEMA)
    del schema["delivery_hours"]
    _seed_tasks(fake_client, schema=schema)
    # canned rows still carry the key; availability is schema-driven
    tasks, available, warnings = fetch_subtasks(fake_client, 59)
    assert "delivery_hours" not in available
    assert warnings == \
        ["field delivery_hours does not exist on project.task"]
    totals = sum_hours(tasks, available)
    assert totals["delivery_hours"] is None
    assert totals["allocated_hours"] == 19.0


def test_sum_hours_totals(fake_client):
    _seed_tasks(fake_client)
    tasks, available, _ = fetch_subtasks(fake_client, 59)
    totals = sum_hours(tasks, available)
    assert totals == {"task_count": 4, "delivery_hours": 24.0,
                      "allocated_hours": 19.0, "effective_hours": 22.0}


def test_subtasks_by_month_buckets_and_no_date_end(fake_client):
    _seed_tasks(fake_client)
    tasks, available, _ = fetch_subtasks(fake_client, 59)
    by_month, no_date_end = subtasks_by_month(tasks, available, 7)
    assert [r["month"] for r in by_month] == ["2025-10", "2025-11"]
    oct_row = by_month[0]
    assert oct_row["task_count"] == 2
    assert oct_row["delivery_hours"] == 15.0
    # id=4 ends 2025-11-01 02:00 UTC -> 09:00 local (+7), stays November
    assert by_month[1]["task_count"] == 1
    # id=3 has no date_end -> excluded from months, reported separately
    assert no_date_end == {"task_count": 1, "delivery_hours": 2.0,
                           "allocated_hours": 1.0, "effective_hours": 1.5}


# -- filter_subtasks_by_periods -----------------------------------------------

def test_filter_subtasks_by_periods_no_periods_keeps_all(fake_client):
    _seed_tasks(fake_client)
    tasks, _, _ = fetch_subtasks(fake_client, 59)
    assert filter_subtasks_by_periods(tasks, None, 7) == tasks
    assert filter_subtasks_by_periods(tasks, [], 7) == tasks


def test_filter_subtasks_by_periods_excludes_falsy_date_end(fake_client):
    _seed_tasks(fake_client)
    tasks, _, _ = fetch_subtasks(fake_client, 59)
    out = filter_subtasks_by_periods(
        tasks, [{"date_from": "2025-01-01", "date_to": "2025-12-31"}], 7)
    # id=3 has date_end=False -> excluded once a period filter is active,
    # even though a server-side "no filter" would have kept it
    assert 3 not in {t["id"] for t in out}


def test_filter_subtasks_by_periods_or_not_union(fake_client):
    _seed_tasks(fake_client)
    tasks, _, _ = fetch_subtasks(fake_client, 59)
    # id=1: 2025-10-05, id=2: 2025-10-20, id=4: 2025-11-01 02:00 UTC (+7
    # -> 2025-11-01 local). Two non-adjacent periods: October only, and a
    # single day in December. Nothing in the gap (Nov) should survive, and
    # nothing matches the December-only period either.
    out = filter_subtasks_by_periods(
        tasks,
        [{"date_from": "2025-10-01", "date_to": "2025-10-31"},
         {"date_from": "2025-12-01", "date_to": "2025-12-31"}],
        7)
    assert {t["id"] for t in out} == {1, 2}   # id=4 (November) excluded


def test_filter_subtasks_by_periods_timezone_crossing_day_boundary():
    # date_end 2025-10-31 18:30:00 UTC crosses midnight at +7 -> local
    # 2025-11-01 01:30:00. The October-31 period must NOT match; the
    # November-1 period must -- this only holds if the UTC->local shift is
    # actually applied before comparing against the period bounds.
    tasks = [{"id": 4, "date_end": "2025-10-31 18:30:00"}]
    october_31 = filter_subtasks_by_periods(
        tasks, [{"date_from": "2025-10-31", "date_to": "2025-10-31"}], 7)
    assert october_31 == []
    november_1 = filter_subtasks_by_periods(
        tasks, [{"date_from": "2025-11-01", "date_to": "2025-11-01"}], 7)
    assert november_1 == tasks


def test_filter_subtasks_by_periods_utc_to_local_month_shift():
    # literal guardrail example: date_end 2025-03-31 18:30:00 UTC + tz 7 ->
    # local 2025-04-01 -> belongs to the April period, not March.
    tasks = [{"id": 1, "date_end": "2025-03-31 18:30:00"}]
    march = filter_subtasks_by_periods(
        tasks, [{"date_from": "2025-03-01", "date_to": "2025-03-31"}], 7)
    assert march == []
    april = filter_subtasks_by_periods(
        tasks, [{"date_from": "2025-04-01", "date_to": "2025-04-30"}], 7)
    assert april == tasks


# -- derive_project_health ----------------------------------------------------

def _ms(name, deadline, reached=False):
    return {"name": name, "deadline": deadline, "is_reached": reached}


def test_health_overdue_milestone_is_off_track_and_divergent():
    today = dt.date(2026, 7, 15)
    h = derive_project_health(
        {"last_update_status": "on_track", "date": False},
        [_ms("Go-live", "2026-01-16"), _ms("Kickoff", "2025-01-01", True)],
        today, today + dt.timedelta(days=7), 7)
    assert h["derived_health"] == "off_track"
    assert h["divergent"] is True
    assert h["overdue"] == 1
    assert h["reached"] == 1 and h["total"] == 2
    assert h["next_milestone"] == {"name": "Go-live",
                                   "deadline": "2026-01-16"}


def test_health_due_soon_is_at_risk():
    today = dt.date(2026, 7, 15)
    h = derive_project_health(
        {"last_update_status": "to_define", "date": False},
        [_ms("Demo", "2026-07-20")],
        today, today + dt.timedelta(days=7), 7)
    assert h["derived_health"] == "at_risk"
    assert h["soon"] == 1 and h["overdue"] == 0
    assert h["divergent"] is False


def test_health_past_end_date_off_track_unless_done():
    today = dt.date(2026, 7, 15)
    h = derive_project_health(
        {"last_update_status": "on_track", "date": "2026-06-30"}, [],
        today, today + dt.timedelta(days=7), 7)
    assert h["past_end"] is True and h["derived_health"] == "off_track"
    h2 = derive_project_health(
        {"last_update_status": "done", "date": "2026-06-30"}, [],
        today, today + dt.timedelta(days=7), 7)
    assert h2["past_end"] is False and h2["derived_health"] == "on_track"


def test_health_milestone_order_independent():
    today = dt.date(2026, 7, 15)
    # unsorted input: earliest unreached must still win next_milestone
    h = derive_project_health(
        {"last_update_status": "on_track", "date": False},
        [_ms("B", "2026-09-01"), _ms("A", "2026-08-01")],
        today, today + dt.timedelta(days=7), 7)
    assert h["next_milestone"]["name"] == "A"


# -- analytic_money -----------------------------------------------------------

def test_analytic_money_empty_accounts_no_rpc(fake_client):
    assert analytic_money(fake_client, []) == ({}, {})
    assert fake_client.calls == []


def test_analytic_money_signs_and_domains(fake_client):
    fake_client.aggregate_responses_seq["account.analytic.line"] = [
        [{"account_id": [5, "AA TBS"], "amount:sum": -1738006746.0}],
        [{"account_id": [5, "AA TBS"], "amount:sum": 120.0}],
    ]
    cost, revenue = analytic_money(fake_client, [5])
    assert cost == {5: 1738006746.0}     # positive cost
    assert revenue == {5: 120.0}
    aggs = [c for c in fake_client.calls
            if c["method"] == "aggregate_records"]
    assert ("amount", "<", 0) in aggs[0]["domain"]
    assert ("amount", ">", 0) in aggs[1]["domain"]


# -- account_field_of / account_id_of / account_ids_by_project ---------------

def test_account_field_of_prefers_account_id_over_analytic_account_id():
    assert account_field_of(["account_id", "analytic_account_id"]) \
        == "account_id"
    assert account_field_of(["analytic_account_id"]) == "analytic_account_id"
    assert account_field_of(["allocated_hours"]) is None


def test_account_id_of_single_row():
    row = {"id": 59, "account_id": [5, "AA TBS"]}
    assert account_id_of(row, ["account_id"]) == 5
    assert account_id_of({"id": 60}, ["account_id"]) is None
    assert account_id_of(row, ["allocated_hours"]) is None  # field absent


def test_account_ids_by_project_skips_projects_without_account():
    projects = [
        {"id": 1, "account_id": [5, "AA-1"]},
        {"id": 2, "account_id": False},
        {"id": 3},
    ]
    assert account_ids_by_project(projects, ["account_id"]) == {1: 5}

# tests/test_project_shared.py
import pytest

from odoo_pulse.odoo_client import OdooError
from odoo_pulse.project_shared import paged_search_read, periods_domain


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


# -- paged_search_read --------------------------------------------------------

def test_paged_search_read_single_short_page(fake_client):
    fake_client.search_responses["project.task"] = [{"id": 1}, {"id": 2}]
    rows = paged_search_read(fake_client, "project.task", [], ["id"])
    assert rows == [{"id": 1}, {"id": 2}]
    call = fake_client.last("search_read")
    assert call["limit"] == 200  # min(page=500, fake max_records=200)
    assert call["offset"] == 0


def test_paged_search_read_pages_until_short_page(fake_client):
    full = [{"id": i} for i in range(200)]
    fake_client.search_responses_seq["project.task"] = [full, [{"id": 999}]]
    rows = paged_search_read(fake_client, "project.task", [], ["id"])
    assert len(rows) == 201
    offsets = [c["offset"] for c in fake_client.calls
               if c["method"] == "search_read"]
    assert offsets == [0, 200]


def test_paged_search_read_runaway_guard(fake_client):
    full = [{"id": i} for i in range(200)]
    fake_client.search_responses_seq["project.task"] = [full] * 3
    with pytest.raises(OdooError, match="more than"):
        paged_search_read(fake_client, "project.task", [], ["id"],
                          max_pages=3)

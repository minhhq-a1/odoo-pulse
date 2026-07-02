# tests/test_tools_aggregate.py
import json

from odoo_pulse.tools_generic import aggregate_records


def test_aggregate_builds_parsed_measures(fake_client):
    fake_client.search_responses["sale.order"] = [
        {"state": "sale", "amount_total": 1000.0},
        {"state": "draft", "amount_total": 50.0},
    ]
    out = json.loads(
        aggregate_records("sale.order", ["state"], measures=["amount_total:sum"])
    )
    assert out["method"] == "read_group"
    assert out["major_version"] == 18
    assert out["model"] == "sale.order"
    assert out["group_by"] == ["state"]
    assert out["measures"] == ["amount_total:sum"]
    assert out["row_count"] == 2
    call = fake_client.last("aggregate_records")
    assert call["measures"] == [("amount_total", "sum")]


def test_bare_measure_defaults_to_sum(fake_client):
    json.loads(aggregate_records("sale.order", ["state"], measures=["amount_total"]))
    call = fake_client.last("aggregate_records")
    assert call["measures"] == [("amount_total", "sum")]


def test_no_measures_defaults_to_count(fake_client):
    json.loads(aggregate_records("sale.order", ["state"]))
    call = fake_client.last("aggregate_records")
    assert call["measures"] == [("id", "count")]


def test_invalid_aggregator_errors_without_client_call(fake_client):
    out = json.loads(
        aggregate_records("sale.order", ["state"], measures=["amount_total:median"])
    )
    assert "error" in out
    assert "median" in out["error"]
    assert all(c["method"] != "aggregate_records" for c in fake_client.calls)


def test_empty_group_by_errors_without_client_call(fake_client):
    out = json.loads(aggregate_records("sale.order", []))
    assert "error" in out
    assert all(c["method"] != "aggregate_records" for c in fake_client.calls)

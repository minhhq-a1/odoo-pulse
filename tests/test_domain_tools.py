"""Detailed tests for domain construction and the multi-step get_* tools."""

from __future__ import annotations

import json

import pytest

from odoo_pulse import domain_tools, tools_generic


# --- Generic tools ------------------------------------------------------------


def test_search_read_tool_forwards_args(fake_client):
    fake_client.search_responses["sale.order"] = [{"id": 1}]
    out = json.loads(
        tools_generic.search_read(
            "sale.order",
            domain=[("state", "=", "sale")],
            fields=["name"],
            limit=5,
            order="date_order desc",
        )
    )
    assert out == [{"id": 1}]
    call = fake_client.last("search_read")
    assert call["model"] == "sale.order"
    assert call["domain"] == [("state", "=", "sale")]
    assert call["fields"] == ["name"]
    assert call["order"] == "date_order desc"


def test_search_count_tool(fake_client):
    out = json.loads(tools_generic.search_count("res.partner"))
    assert out == {"count": 7}


def test_get_model_fields_filters(fake_client):
    out = json.loads(tools_generic.get_model_fields("res.partner", fields=["name"]))
    assert set(out) == {"name"}


def test_odoo_version_warns_below_18(fake_client):
    fake_client.major = 17
    out = json.loads(tools_generic.odoo_version())
    assert "warning" in out
    assert "Odoo 18+" in out["warning"]


def test_odoo_version_no_warning_on_18(fake_client):
    out = json.loads(tools_generic.odoo_version())
    assert "warning" not in out


# --- Filter construction ------------------------------------------------------


def test_find_partner_builds_or_domain(fake_client):
    domain_tools.find_partner("acme")
    domain = fake_client.last("search_read")["domain"]
    # OR across several fields, each an ilike on the query.
    assert ("name", "ilike", "acme") in domain
    assert ("email", "ilike", "acme") in domain
    assert domain.count("|") == 5  # six fields -> five OR operators


def test_list_invoices_defaults_to_posted_customer_invoices(fake_client):
    domain_tools.list_invoices()
    domain = fake_client.last("search_read")["domain"]
    assert ("move_type", "=", "out_invoice") in domain
    assert ("state", "=", "posted") in domain


def test_list_invoices_unpaid_and_filters(fake_client):
    domain_tools.list_invoices(
        customer="Acme", move_type="in_invoice", unpaid_only=True,
        date_from="2026-01-01", date_to="2026-06-30",
    )
    domain = fake_client.last("search_read")["domain"]
    assert ("move_type", "=", "in_invoice") in domain
    assert ("partner_id.name", "ilike", "Acme") in domain
    assert ("payment_state", "in", ("not_paid", "partial")) in domain
    assert ("invoice_date", ">=", "2026-01-01") in domain
    assert ("invoice_date", "<=", "2026-06-30") in domain


def test_list_sale_orders_ignores_invalid_state(fake_client):
    domain_tools.list_sale_orders(state="bogus")
    domain = fake_client.last("search_read")["domain"]
    assert all("state" != trip[0] for trip in domain if isinstance(trip, tuple))


def test_check_stock_filters_internal_locations(fake_client):
    domain_tools.check_stock("table")
    domain = fake_client.last("search_read")["domain"]
    assert ("location_id.usage", "=", "internal") in domain


# --- Multi-step get_* tools ---------------------------------------------------


def test_get_sale_order_by_name_reads_header_and_lines(fake_client):
    fake_client.search_responses["sale.order"] = [{"id": 5}]
    fake_client.read_responses["sale.order"] = [
        {"id": 5, "name": "S00005", "order_line": [10, 11]}
    ]
    fake_client.read_responses["sale.order.line"] = [
        {"id": 10, "name": "Line A"},
        {"id": 11, "name": "Line B"},
    ]
    out = json.loads(domain_tools.get_sale_order(order_name="S00005"))
    assert out["name"] == "S00005"
    assert "order_line" not in out  # replaced by expanded lines
    assert len(out["lines"]) == 2
    # Looked up the id, then read header + lines.
    assert fake_client.last("search_read")["model"] == "sale.order"
    read_models = [c["model"] for c in fake_client.calls if c["method"] == "read"]
    assert read_models == ["sale.order", "sale.order.line"]


def test_get_sale_order_requires_an_identifier(fake_client):
    out = json.loads(domain_tools.get_sale_order())
    assert "error" in out


def test_get_sale_order_not_found(fake_client):
    fake_client.search_responses["sale.order"] = []
    out = json.loads(domain_tools.get_sale_order(order_name="NOPE"))
    assert "error" in out


def test_get_invoice_expands_lines(fake_client):
    fake_client.read_responses["account.move"] = [
        {"id": 3, "name": "INV/1", "invoice_line_ids": [7]}
    ]
    fake_client.read_responses["account.move.line"] = [{"id": 7, "name": "Item"}]
    out = json.loads(domain_tools.get_invoice(move_id=3))
    assert out["name"] == "INV/1"
    assert out["lines"] == [{"id": 7, "name": "Item"}]
    assert "invoice_line_ids" not in out


def test_find_partner_omits_mobile_when_absent_from_schema(fake_client):
    import json
    from odoo_pulse import domain_tools

    # Odoo 19: mobile removed from res.partner
    fake_client.fields_responses["res.partner"] = {"name": {"type": "char"}}
    fake_client.search_responses["res.partner"] = []
    out = json.loads(domain_tools.find_partner("acme"))
    assert out == []
    call = fake_client.last("search_read")
    assert "mobile" not in call["fields"]
    assert not any(
        isinstance(t, (list, tuple)) and t and t[0] == "mobile"
        for t in call["domain"]
    )


def test_find_partner_includes_mobile_when_present(fake_client):
    import json
    from odoo_pulse import domain_tools

    fake_client.search_responses["res.partner"] = []
    json.loads(domain_tools.find_partner("acme"))
    call = fake_client.last("search_read")
    assert "mobile" in call["fields"]
    assert any(
        isinstance(t, (list, tuple)) and t and t[0] == "mobile"
        for t in call["domain"]
    )


@pytest.mark.parametrize(
    "func,kwargs",
    [
        (domain_tools.get_sale_order, {"order_id": 1}),
        (domain_tools.get_invoice, {"move_id": 1}),
        (domain_tools.get_purchase_order, {"order_id": 1}),
    ],
)
def test_document_tool_serialises_client_construction_error(
    monkeypatch, func, kwargs
):
    from odoo_pulse.odoo_client import OdooConfigError

    def fail_client():
        raise OdooConfigError("Missing required environment variables: ODOO_API_KEY")

    monkeypatch.setattr(domain_tools, "get_client", fail_client)
    out = json.loads(func(**kwargs))
    assert out == {
        "error": "Missing required environment variables: ODOO_API_KEY"}


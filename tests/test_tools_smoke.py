"""Smoke test: every list_* domain tool targets the expected model, returns
valid JSON, and respects the injected (fake) client. This guards against
typos in model names and regressions when modules are refactored.
"""

from __future__ import annotations

import json

import pytest

from odoo_pulse import (
    domain_tools,
    tools_engagement,
    tools_hr,
    tools_niche,
    tools_operations,
    tools_projects,
)

# (callable, kwargs, expected_model)
CASES = [
    # Contacts / CRM / Sales / Purchase / Inventory / Accounting
    (domain_tools.find_partner, {"query": "acme"}, "res.partner"),
    (domain_tools.list_opportunities, {}, "crm.lead"),
    (domain_tools.list_sale_orders, {}, "sale.order"),
    (domain_tools.list_purchase_orders, {}, "purchase.order"),
    (domain_tools.find_products, {}, "product.product"),
    (domain_tools.check_stock, {"product_query": "table"}, "stock.quant"),
    (domain_tools.list_invoices, {}, "account.move"),
    (domain_tools.list_payments, {}, "account.payment"),
    (domain_tools.list_pickings, {}, "stock.picking"),
    # HR
    (tools_hr.list_employees, {}, "hr.employee"),
    (tools_hr.list_departments, {}, "hr.department"),
    (tools_hr.list_time_off, {}, "hr.leave"),
    (tools_hr.list_expenses, {}, "hr.expense"),
    (tools_hr.list_job_positions, {}, "hr.job"),
    (tools_hr.list_applicants, {}, "hr.applicant"),
    (tools_hr.list_attendances, {}, "hr.attendance"),
    # Project
    (tools_projects.list_projects, {}, "project.project"),
    (tools_projects.list_tasks, {}, "project.task"),
    (tools_projects.list_timesheets, {}, "account.analytic.line"),
    # Operations
    (tools_operations.list_manufacturing_orders, {}, "mrp.production"),
    (tools_operations.list_boms, {}, "mrp.bom"),
    (tools_operations.list_pos_orders, {}, "pos.order"),
    (tools_operations.list_pos_sessions, {}, "pos.session"),
    (tools_operations.list_repair_orders, {}, "repair.order"),
    (tools_operations.list_maintenance_requests, {}, "maintenance.request"),
    (tools_operations.list_equipment, {}, "maintenance.equipment"),
    (tools_operations.list_helpdesk_tickets, {}, "helpdesk.ticket"),
    (tools_operations.list_vehicles, {}, "fleet.vehicle"),
    # Engagement
    (tools_engagement.list_events, {}, "event.event"),
    (tools_engagement.list_event_registrations, {}, "event.registration"),
    (tools_engagement.list_calendar_events, {}, "calendar.event"),
    (tools_engagement.list_activities, {}, "mail.activity"),
    (tools_engagement.list_surveys, {}, "survey.survey"),
    (tools_engagement.list_email_campaigns, {}, "mailing.mailing"),
    # Niche
    (tools_niche.list_subscriptions, {}, "sale.subscription"),
    (tools_niche.list_sign_requests, {}, "sign.request"),
    (tools_niche.list_documents, {}, "documents.document"),
    (tools_niche.list_knowledge_articles, {}, "knowledge.article"),
    (tools_niche.list_approval_requests, {}, "approval.request"),
    (tools_niche.list_lunch_orders, {}, "lunch.order"),
    (tools_niche.list_quality_checks, {}, "quality.check"),
    (tools_niche.list_quality_alerts, {}, "quality.alert"),
    (tools_niche.list_planning_slots, {}, "planning.slot"),
    (tools_niche.list_courses, {}, "slide.channel"),
    (tools_niche.list_loyalty_programs, {}, "loyalty.program"),
    (tools_niche.list_loyalty_cards, {}, "loyalty.card"),
    (tools_niche.list_memberships, {}, "membership.membership_line"),
    (tools_niche.list_payslips, {}, "hr.payslip"),
    (tools_niche.list_appraisals, {}, "hr.appraisal"),
    (tools_niche.list_social_posts, {}, "social.post"),
    (tools_niche.list_website_visitors, {}, "website.visitor"),
    (tools_niche.list_engineering_changes, {}, "mrp.eco"),
    (tools_niche.list_iot_devices, {}, "iot.device"),
    (tools_niche.list_notes, {}, "note.note"),
]


@pytest.mark.parametrize(
    "func,kwargs,model", CASES, ids=[f.__name__ for f, _, _ in CASES]
)
def test_list_tool_targets_expected_model(fake_client, func, kwargs, model):
    out = func(**kwargs)
    # Tool always returns a JSON string.
    json.loads(out)
    call = fake_client.last("search_read")
    assert call["model"] == model


def test_every_tool_passes_a_limit(fake_client):
    """All list tools should forward a limit so result size stays bounded."""
    for func, kwargs, _ in CASES:
        fake_client.calls.clear()
        func(**kwargs)
        assert fake_client.last("search_read")["limit"] is not None


def test_friendly_error_when_model_missing(fake_client):
    """If Odoo raises (e.g. uninstalled app), the tool returns an error dict."""
    fake_client.raise_error = "Object helpdesk.ticket doesn't exist"
    out = json.loads(tools_operations.list_helpdesk_tickets())
    assert "error" in out

"""Read-only domain tools for niche / specialised Odoo modules.

Many of these belong to Odoo Enterprise or optional apps that may not be
installed on a given database. When the underlying model is absent, the call
returns a friendly error (via ``safe``) rather than crashing.

Default ordering uses ``create_date`` because it exists on every model, which
keeps these tools robust across Odoo versions where other field names vary.

Covered models:
  - sale.subscription          (Subscriptions)
  - sign.request               (Sign)
  - documents.document         (Documents)
  - knowledge.article          (Knowledge)
  - approval.request           (Approvals)
  - lunch.order                (Lunch)
  - quality.check              (Quality checks)
  - quality.alert              (Quality alerts)
  - planning.slot              (Planning / shifts)
  - slide.channel              (eLearning courses)
  - loyalty.program            (Loyalty / coupons / gift cards)
  - loyalty.card               (Loyalty cards)
  - membership.membership_line (Memberships)
  - hr.payslip                 (Payroll)
  - hr.appraisal               (Appraisals)
  - social.post                (Social marketing)
  - website.visitor            (Website visitors)
  - mrp.eco                    (PLM engineering change orders)
  - iot.device                 (IoT devices)
  - note.note                  (Notes)
"""

from __future__ import annotations

from .runtime import get_client, mcp, name_domain, safe


# --- Subscriptions ------------------------------------------------------------


@mcp.tool()
def list_subscriptions(
    customer: str | None = None, stage: str | None = None, limit: int = 20
) -> str:
    """List subscriptions (sale.subscription).

    Args:
        customer: Filter by customer name.
        stage: Filter by subscription stage name (e.g. 'In Progress', 'Closed').
        limit: Max results.
    """
    domain: list = []
    if customer:
        domain.append(("partner_id.name", "ilike", customer))
    if stage:
        domain.append(("stage_id.name", "ilike", stage))
    return safe(
        lambda: get_client().search_read(
            "sale.subscription",
            domain=domain,
            fields=["name", "partner_id", "stage_id", "recurring_monthly", "date_start"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- Sign ---------------------------------------------------------------------


@mcp.tool()
def list_sign_requests(state: str | None = None, limit: int = 20) -> str:
    """List electronic signature requests (sign.request).

    Args:
        state: sent, signed, refused, canceled or expired.
        limit: Max results.
    """
    domain: list = []
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "sign.request",
            domain=domain,
            fields=["reference", "state", "create_date"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- Documents ----------------------------------------------------------------


@mcp.tool()
def list_documents(query: str | None = None, limit: int = 20) -> str:
    """List documents from the Documents app (documents.document).

    Args:
        query: Free text matched against the document name.
        limit: Max results.
    """
    domain = name_domain(query, ["name"])
    return safe(
        lambda: get_client().search_read(
            "documents.document",
            domain=domain,
            fields=["name", "folder_id", "owner_id", "mimetype", "create_date"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- Knowledge ----------------------------------------------------------------


@mcp.tool()
def list_knowledge_articles(query: str | None = None, limit: int = 20) -> str:
    """List Knowledge articles (knowledge.article).

    Args:
        query: Free text matched against the article name.
        limit: Max results.
    """
    domain = name_domain(query, ["name"])
    return safe(
        lambda: get_client().search_read(
            "knowledge.article",
            domain=domain,
            fields=["name", "parent_id", "is_published", "write_date"],
            limit=limit,
            order="write_date desc",
        )
    )


# --- Approvals ----------------------------------------------------------------


@mcp.tool()
def list_approval_requests(
    status: str | None = None, category: str | None = None, limit: int = 20
) -> str:
    """List approval requests (approval.request).

    Args:
        status: new, pending, approved, refused or cancel.
        category: Filter by approval category name (e.g. 'Business Trip').
        limit: Max results.
    """
    domain: list = []
    if status:
        domain.append(("request_status", "=", status))
    if category:
        domain.append(("category_id.name", "ilike", category))
    return safe(
        lambda: get_client().search_read(
            "approval.request",
            domain=domain,
            fields=["name", "request_owner_id", "category_id", "request_status"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- Lunch --------------------------------------------------------------------


@mcp.tool()
def list_lunch_orders(state: str | None = None, limit: int = 20) -> str:
    """List lunch orders (lunch.order).

    Args:
        state: new, ordered, confirmed or cancelled.
        limit: Max results.
    """
    domain: list = []
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "lunch.order",
            domain=domain,
            fields=["product_id", "user_id", "date", "price", "state"],
            limit=limit,
            order="date desc",
        )
    )


# --- Quality ------------------------------------------------------------------


@mcp.tool()
def list_quality_checks(
    product: str | None = None, quality_state: str | None = None, limit: int = 20
) -> str:
    """List quality checks (quality.check).

    Args:
        product: Filter by product (name or reference).
        quality_state: none, pass or fail.
        limit: Max results.
    """
    domain = name_domain(product, ["product_id.name", "product_id.default_code"])
    if quality_state:
        domain.append(("quality_state", "=", quality_state))
    return safe(
        lambda: get_client().search_read(
            "quality.check",
            domain=domain,
            fields=["name", "product_id", "quality_state", "control_date", "team_id"],
            limit=limit,
            order="create_date desc",
        )
    )


@mcp.tool()
def list_quality_alerts(stage: str | None = None, limit: int = 20) -> str:
    """List quality alerts (quality.alert).

    Args:
        stage: Filter by stage name.
        limit: Max results.
    """
    domain: list = []
    if stage:
        domain.append(("stage_id.name", "ilike", stage))
    return safe(
        lambda: get_client().search_read(
            "quality.alert",
            domain=domain,
            fields=["name", "product_id", "stage_id", "team_id"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- Planning -----------------------------------------------------------------


@mcp.tool()
def list_planning_slots(
    resource: str | None = None, role: str | None = None, limit: int = 20
) -> str:
    """List planning shifts / slots (planning.slot).

    Args:
        resource: Filter by the assigned resource (employee/material) name.
        role: Filter by role name.
        limit: Max results.
    """
    domain: list = []
    if resource:
        domain.append(("resource_id.name", "ilike", resource))
    if role:
        domain.append(("role_id.name", "ilike", role))
    return safe(
        lambda: get_client().search_read(
            "planning.slot",
            domain=domain,
            fields=["resource_id", "role_id", "start_datetime", "end_datetime", "allocated_hours"],
            limit=limit,
            order="start_datetime desc",
        )
    )


# --- eLearning ----------------------------------------------------------------


@mcp.tool()
def list_courses(query: str | None = None, limit: int = 20) -> str:
    """List eLearning courses (slide.channel).

    Args:
        query: Free text matched against the course name.
        limit: Max results.
    """
    domain = name_domain(query, ["name"])
    return safe(
        lambda: get_client().search_read(
            "slide.channel",
            domain=domain,
            fields=["name", "total_slides", "members_count", "user_id"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- Loyalty ------------------------------------------------------------------


@mcp.tool()
def list_loyalty_programs(query: str | None = None, limit: int = 20) -> str:
    """List loyalty programs / coupons / gift cards (loyalty.program).

    Args:
        query: Free text matched against the program name.
        limit: Max results.
    """
    domain = name_domain(query, ["name"])
    return safe(
        lambda: get_client().search_read(
            "loyalty.program",
            domain=domain,
            fields=["name", "program_type", "active"],
            limit=limit,
            order="create_date desc",
        )
    )


@mcp.tool()
def list_loyalty_cards(partner: str | None = None, limit: int = 20) -> str:
    """List loyalty / gift cards (loyalty.card).

    Args:
        partner: Filter by the card holder's name.
        limit: Max results.
    """
    domain: list = []
    if partner:
        domain.append(("partner_id.name", "ilike", partner))
    return safe(
        lambda: get_client().search_read(
            "loyalty.card",
            domain=domain,
            fields=["code", "program_id", "partner_id", "points"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- Memberships --------------------------------------------------------------


@mcp.tool()
def list_memberships(
    partner: str | None = None, state: str | None = None, limit: int = 20
) -> str:
    """List membership lines (membership.membership_line).

    Args:
        partner: Filter by member name.
        state: none, canceled, old, waiting, invoiced, free or paid.
        limit: Max results.
    """
    domain: list = []
    if partner:
        domain.append(("partner.name", "ilike", partner))
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "membership.membership_line",
            domain=domain,
            fields=["partner", "membership_id", "date_from", "date_to", "state"],
            limit=limit,
            order="date_from desc",
        )
    )


# --- Payroll ------------------------------------------------------------------


@mcp.tool()
def list_payslips(
    employee: str | None = None, state: str | None = None, limit: int = 20
) -> str:
    """List payroll payslips (hr.payslip).

    Args:
        employee: Filter by employee name.
        state: draft, verify, done or cancel.
        limit: Max results.
    """
    domain: list = []
    if employee:
        domain.append(("employee_id.name", "ilike", employee))
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "hr.payslip",
            domain=domain,
            fields=["number", "employee_id", "date_from", "date_to", "state"],
            limit=limit,
            order="date_from desc",
        )
    )


# --- Appraisals ---------------------------------------------------------------


@mcp.tool()
def list_appraisals(
    employee: str | None = None, state: str | None = None, limit: int = 20
) -> str:
    """List employee appraisals (hr.appraisal).

    Args:
        employee: Filter by employee name.
        state: new, pending, done or cancel.
        limit: Max results.
    """
    domain: list = []
    if employee:
        domain.append(("employee_id.name", "ilike", employee))
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "hr.appraisal",
            domain=domain,
            fields=["employee_id", "state", "date_close"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- Social marketing ---------------------------------------------------------


@mcp.tool()
def list_social_posts(state: str | None = None, limit: int = 20) -> str:
    """List social media posts (social.post).

    Args:
        state: draft, scheduled, posting, posted or failed.
        limit: Max results.
    """
    domain: list = []
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "social.post",
            domain=domain,
            fields=["message", "state", "create_date"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- Website ------------------------------------------------------------------


@mcp.tool()
def list_website_visitors(limit: int = 20) -> str:
    """List website visitors (website.visitor) with visit counts."""
    return safe(
        lambda: get_client().search_read(
            "website.visitor",
            domain=[],
            fields=["display_name", "partner_id", "country_id", "visit_count"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- PLM ----------------------------------------------------------------------


@mcp.tool()
def list_engineering_changes(
    product: str | None = None, state: str | None = None, limit: int = 20
) -> str:
    """List PLM engineering change orders (mrp.eco).

    Args:
        product: Filter by the affected product template name.
        state: Filter by state code.
        limit: Max results.
    """
    domain = name_domain(product, ["product_tmpl_id.name"])
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "mrp.eco",
            domain=domain,
            fields=["name", "product_tmpl_id", "stage_id", "state"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- IoT ----------------------------------------------------------------------


@mcp.tool()
def list_iot_devices(query: str | None = None, limit: int = 20) -> str:
    """List IoT devices (iot.device).

    Args:
        query: Free text matched against the device name.
        limit: Max results.
    """
    domain = name_domain(query, ["name"])
    return safe(
        lambda: get_client().search_read(
            "iot.device",
            domain=domain,
            fields=["name", "type", "connection"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- Notes --------------------------------------------------------------------


@mcp.tool()
def list_notes(query: str | None = None, limit: int = 20) -> str:
    """List notes (note.note).

    Args:
        query: Free text matched against the note content.
        limit: Max results.
    """
    domain = name_domain(query, ["name"])
    return safe(
        lambda: get_client().search_read(
            "note.note",
            domain=domain,
            fields=["name", "stage_id", "write_date"],
            limit=limit,
            order="write_date desc",
        )
    )

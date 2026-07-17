"""Read-only domain tools for operational modules.

Covered models:
  - mrp.production        (Manufacturing orders)
  - mrp.bom              (Bills of materials)
  - pos.order            (Point of Sale orders)
  - pos.session          (PoS sessions)
  - repair.order         (Repairs)
  - maintenance.request  (Maintenance)
  - maintenance.equipment(Equipment)
  - helpdesk.ticket      (Helpdesk - enterprise)
  - fleet.vehicle        (Fleet)

Models belonging to apps that are not installed surface as a friendly error.
"""

from __future__ import annotations

from .runtime import date_domain, get_client, mcp, name_domain, safe


# --- Manufacturing (MRP) ------------------------------------------------------


@mcp.tool()
def list_manufacturing_orders(
    product: str | None = None, state: str | None = None, limit: int = 20
) -> str:
    """List manufacturing orders (mrp.production).

    Args:
        product: Filter by the product being manufactured (name or reference).
        state: draft, confirmed, progress, to_close, done or cancel.
        limit: Max results.
    """
    domain = name_domain(product, ["product_id.name", "product_id.default_code"])
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "mrp.production",
            domain=domain,
            fields=[
                "name",
                "product_id",
                "product_qty",
                "state",
                "date_start",
                "date_finished",
            ],
            limit=limit,
            order="date_start desc",
        )
    )


@mcp.tool()
def list_boms(product: str | None = None, limit: int = 20) -> str:
    """List bills of materials (mrp.bom).

    Args:
        product: Filter by the produced product (name or reference).
        limit: Max results.
    """
    domain = name_domain(
        product, ["product_tmpl_id.name", "product_tmpl_id.default_code", "code"]
    )
    return safe(
        lambda: get_client().search_read(
            "mrp.bom",
            domain=domain,
            fields=["code", "product_tmpl_id", "product_qty", "type"],
            limit=limit,
            order="code",
        )
    )


# --- Point of Sale ------------------------------------------------------------


@mcp.tool()
def list_pos_orders(
    date_from: str | None = None,
    date_to: str | None = None,
    state: str | None = None,
    limit: int = 20,
) -> str:
    """List Point of Sale orders (pos.order).

    Args:
        date_from: Inclusive lower bound on order date (YYYY-MM-DD).
        date_to: Inclusive upper bound on order date (YYYY-MM-DD).
        state: draft, paid, done, invoiced or cancel.
        limit: Max results.
    """
    def run():
        domain: list = []
        if state:
            domain.append(("state", "=", state))
        domain.extend(date_domain("date_order", date_from, date_to, as_datetime=True))
        return get_client().search_read(
            "pos.order",
            domain=domain,
            fields=["name", "partner_id", "date_order", "amount_total", "state", "session_id"],
            limit=limit,
            order="date_order desc",
        )

    return safe(run)


@mcp.tool()
def list_pos_sessions(state: str | None = None, limit: int = 20) -> str:
    """List Point of Sale sessions (pos.session).

    Args:
        state: opening_control, opened, closing_control or closed.
        limit: Max results.
    """
    domain: list = []
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "pos.session",
            domain=domain,
            fields=["name", "config_id", "user_id", "start_at", "stop_at", "state"],
            limit=limit,
            order="start_at desc",
        )
    )


# --- Repair -------------------------------------------------------------------


@mcp.tool()
def list_repair_orders(
    product: str | None = None, state: str | None = None, limit: int = 20
) -> str:
    """List repair orders (repair.order).

    Args:
        product: Filter by the product under repair (name or reference).
        state: draft, confirmed, under_repair, ready, done or cancel.
        limit: Max results.
    """
    domain = name_domain(product, ["product_id.name", "product_id.default_code"])
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "repair.order",
            domain=domain,
            fields=["name", "product_id", "partner_id", "state", "schedule_date"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- Maintenance --------------------------------------------------------------


@mcp.tool()
def list_maintenance_requests(
    equipment: str | None = None, stage: str | None = None, limit: int = 20
) -> str:
    """List maintenance requests (maintenance.request).

    Args:
        equipment: Filter by equipment name.
        stage: Filter by stage name (e.g. 'New Request', 'In Progress', 'Repaired').
        limit: Max results.
    """
    domain: list = []
    if equipment:
        domain.append(("equipment_id.name", "ilike", equipment))
    if stage:
        domain.append(("stage_id.name", "ilike", stage))
    return safe(
        lambda: get_client().search_read(
            "maintenance.request",
            domain=domain,
            fields=[
                "name",
                "equipment_id",
                "stage_id",
                "maintenance_type",
                "request_date",
                "schedule_date",
            ],
            limit=limit,
            order="request_date desc",
        )
    )


@mcp.tool()
def list_equipment(query: str | None = None, limit: int = 20) -> str:
    """List maintenance equipment / assets (maintenance.equipment)."""
    domain = name_domain(query, ["name", "serial_no"])
    return safe(
        lambda: get_client().search_read(
            "maintenance.equipment",
            domain=domain,
            fields=["name", "category_id", "serial_no", "employee_id", "location"],
            limit=limit,
            order="name",
        )
    )


# --- Helpdesk (enterprise) ----------------------------------------------------


@mcp.tool()
def list_helpdesk_tickets(
    query: str | None = None,
    team: str | None = None,
    stage: str | None = None,
    limit: int = 20,
) -> str:
    """List helpdesk tickets (helpdesk.ticket - Odoo Enterprise).

    Args:
        query: Free text matched against ticket name or customer.
        team: Filter by helpdesk team name.
        stage: Filter by stage name (e.g. 'New', 'In Progress', 'Solved').
        limit: Max results.
    """
    domain = name_domain(query, ["name", "partner_name"])
    if team:
        domain.append(("team_id.name", "ilike", team))
    if stage:
        domain.append(("stage_id.name", "ilike", stage))
    return safe(
        lambda: get_client().search_read(
            "helpdesk.ticket",
            domain=domain,
            fields=["name", "partner_id", "team_id", "stage_id", "user_id", "priority"],
            limit=limit,
            order="priority desc, create_date desc",
        )
    )


# --- Fleet --------------------------------------------------------------------


@mcp.tool()
def list_vehicles(query: str | None = None, limit: int = 20) -> str:
    """List fleet vehicles (fleet.vehicle).

    Args:
        query: Free text matched against vehicle name or license plate.
        limit: Max results.
    """
    domain = name_domain(query, ["name", "license_plate"])
    return safe(
        lambda: get_client().search_read(
            "fleet.vehicle",
            domain=domain,
            fields=["name", "license_plate", "driver_id", "model_id", "state_id"],
            limit=limit,
            order="name",
        )
    )

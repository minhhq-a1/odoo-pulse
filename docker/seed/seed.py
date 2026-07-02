#!/usr/bin/env python3
"""One-shot seeder for the odoo-pulse playground.

Waits for Odoo, writes a curated "story" so every hero report tool has
something interesting to say, then records a marker so re-runs are no-ops.
Standard library only (xmlrpc.client) — no dependencies, no image build.
"""
from __future__ import annotations

import os
import sys
import time
import xmlrpc.client
from datetime import date, datetime, timedelta, timezone

MARKER_KEY = "playground.seeded"
TZ_OFFSET_HOURS = 7  # matches the report tools' default timezone_offset=7


class Seeder:
    def __init__(self) -> None:
        self.url = os.environ.get("ODOO_URL", "http://localhost:8069").rstrip("/")
        self.db = os.environ.get("ODOO_DB", "playground")
        self.user = os.environ.get("ODOO_USERNAME", "admin")
        self.key = os.environ.get("ODOO_API_KEY", "admin")
        self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        self.uid: int | None = None

    def wait_for_odoo(self, timeout: int = 300) -> None:
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            try:
                uid = self._common.authenticate(self.db, self.user, self.key, {})
                if uid:
                    self.uid = uid
                    print(f"[seed] connected, uid={uid}")
                    return
            except Exception as exc:  # noqa: BLE001 - Odoo not ready yet
                last = str(exc)
            print("[seed] waiting for Odoo...")
            time.sleep(5)
        raise SystemExit(f"[seed] Odoo not ready after {timeout}s: {last}")

    def call(self, model: str, method: str, args: list, kwargs: dict | None = None):
        return self._models.execute_kw(
            self.db, self.uid, self.key, model, method, args, kwargs or {})

    def create(self, model: str, vals: dict) -> int:
        rec_id = self.call(model, "create", [vals])
        print(f"[seed] created {model} #{rec_id}")
        return rec_id

    def write(self, model: str, ids: list[int], vals: dict) -> bool:
        return self.call(model, "write", [ids, vals])

    def search(self, model: str, domain: list, limit: int | None = None) -> list[int]:
        kwargs = {"limit": limit} if limit else {}
        return self.call(model, "search", [domain], kwargs)

    def already_seeded(self) -> bool:
        rows = self.call("ir.config_parameter", "search_read",
                         [[("key", "=", MARKER_KEY)]], {"fields": ["value"]})
        return bool(rows)

    def mark_seeded(self) -> None:
        self.create("ir.config_parameter", {"key": MARKER_KEY, "value": "1"})
        print("[seed] marker set — future runs are no-ops")

    # --- relative-date helpers (offset matches report tools) ---
    def today(self) -> date:
        return (datetime.now(timezone.utc) + timedelta(hours=TZ_OFFSET_HOURS)).date()

    def d(self, delta_days: int) -> str:
        return (self.today() + timedelta(days=delta_days)).strftime("%Y-%m-%d")

    def dt(self, delta_days: int) -> str:
        base = datetime.combine(self.today(), datetime.min.time()) + timedelta(hours=9)
        return (base + timedelta(days=delta_days)).strftime("%Y-%m-%d %H:%M:%S")



S = Seeder()


def _backdate(model: str, rec_id: int, delta_days: int) -> None:
    """Backdate create_date via a one-shot server action's SQL cursor.

    create_date is a protected log field Odoo's ORM ignores on write()/
    create(); this uses only the standard XML-RPC surface (ir.actions.server
    running server-side code, same as any other model call) so it works
    identically on the host and inside the containerized seed service.
    """
    table = model.replace(".", "_")
    model_id = S.search("ir.model", [("model", "=", model)], limit=1)[0]
    action_id = S.create("ir.actions.server", {
        "name": f"PLAYGROUND backdate {model}#{rec_id}",
        "model_id": model_id,
        "state": "code",
        "code": (
            f"env.cr.execute(\"UPDATE {table} SET create_date = "
            f"create_date - INTERVAL '{abs(delta_days)} days' WHERE id = {rec_id}\")"
        ),
    })
    S.call("ir.actions.server", "run", [[action_id]])
    S.call("ir.actions.server", "unlink", [[action_id]])
    print(f"[seed] backdated {model} #{rec_id} create_date via ir.actions.server")


def seed_crm() -> None:
    print("[seed] CRM pipeline...")
    stage_ids = S.search("crm.stage", [], limit=4)
    if not stage_ids:
        raise SystemExit("[seed] no crm.stage found — is CRM installed with demo data?")
    first_stage, mid_stage = stage_ids[0], stage_ids[min(1, len(stage_ids) - 1)]

    # A high-value deal that has not moved stage in 40 days => stalled.
    stalled = S.create("crm.lead", {
        "name": "PLAYGROUND: ACME platform rollout",
        "type": "opportunity",
        "stage_id": mid_stage,
        "expected_revenue": 120000.0,
        "probability": 40.0,
        "date_deadline": S.d(20),
    })
    # date_last_stage_update is a stored computed field; write it after create
    # so Odoo does not reset it to "now". (Drift note: field name is stable in 18.)
    S.write("crm.lead", [stalled], {"date_last_stage_update": S.dt(-40)})

    # An open deal already past its expected close date => overdue_close.
    S.create("crm.lead", {
        "name": "PLAYGROUND: Globex renewal",
        "type": "opportunity",
        "stage_id": first_stage,
        "expected_revenue": 30000.0,
        "probability": 20.0,
        "date_deadline": S.d(-5),
    })
    # A couple of healthy open deals for funnel breadth.
    for name, rev, prob in [("Initech expansion", 45000.0, 60.0),
                            ("Umbrella pilot", 15000.0, 30.0)]:
        S.create("crm.lead", {
            "name": f"PLAYGROUND: {name}", "type": "opportunity",
            "stage_id": mid_stage, "expected_revenue": rev, "probability": prob,
            "date_deadline": S.d(25),
        })

    # Win/loss history in the last 90 days => non-null win_rate_pct.
    for name in ["Wonka supply won", "Stark contract won"]:
        won = S.create("crm.lead", {
            "name": f"PLAYGROUND: {name}", "type": "opportunity",
            "stage_id": stage_ids[-1], "expected_revenue": 20000.0,
            "probability": 100.0,
        })
        S.write("crm.lead", [won], {"date_closed": S.dt(-10)})
    lost = S.create("crm.lead", {
        "name": "PLAYGROUND: Hooli deal lost", "type": "opportunity",
        "stage_id": first_stage, "expected_revenue": 18000.0, "probability": 0.0,
    })
    S.write("crm.lead", [lost], {"date_closed": S.dt(-8), "active": False})


def _service_product(name: str, price: float) -> int:
    """A service product avoids stock plumbing for revenue-only orders."""
    ids = S.search("product.product", [("name", "=", name)], limit=1)
    if ids:
        return ids[0]
    return S.create("product.product", {
        "name": name, "type": "service", "list_price": price, "standard_price": price,
    })


def _partner(name: str) -> int:
    ids = S.search("res.partner", [("name", "=", name)], limit=1)
    return ids[0] if ids else S.create("res.partner", {"name": name})


def _confirmed_order(partner_id: int, product_id: int, qty: float,
                     price: float, order_date_delta: int) -> int:
    """Create an order with one line, force it to a confirmed state and
    backdate date_order. Direct state write avoids stock/invoice side effects
    for revenue-only demo orders (sales_snapshot only reads state/amount/date)."""
    oid = S.create("sale.order", {
        "partner_id": partner_id,
        "order_line": [(0, 0, {"product_id": product_id,
                               "product_uom_qty": qty, "price_unit": price})],
    })
    S.write("sale.order", [oid], {"state": "sale", "date_order": S.dt(order_date_delta)})
    return oid


def seed_sales() -> None:
    print("[seed] Sales snapshot...")
    prod = _service_product("PLAYGROUND Consulting Hours", 150.0)
    big = _partner("PLAYGROUND Big Customer Co")
    small = _partner("PLAYGROUND Small Shop")

    # Current window (last 7 days): higher revenue, clear top customer.
    _confirmed_order(big, prod, 40, 150.0, -2)     # 6000
    _confirmed_order(big, prod, 20, 150.0, -5)     # 3000
    _confirmed_order(small, prod, 5, 150.0, -3)    # 750
    # Previous window (8–14 days ago): lower revenue, so delta_pct is positive.
    _confirmed_order(small, prod, 8, 150.0, -10)   # 1200

    # A quotation left sitting => stale_quotations.
    stale = S.create("sale.order", {
        "partner_id": small,
        "order_line": [(0, 0, {"product_id": prod, "product_uom_qty": 3,
                               "price_unit": 150.0})],
    })
    S.write("sale.order", [stale], {"state": "draft", "create_date": S.dt(-20)})
    # Field-drift: create_date is readonly in Odoo, so S.write() above doesn't set it.
    # Workaround: update via ir.actions.server server-side SQL (works on host and containerized).
    _backdate("sale.order", stale, -20)


def _storable_product(name: str, cost: float) -> int:
    ids = S.search("product.product", [("name", "=", name), ("is_storable", "=", True)], limit=1)
    if ids:
        return ids[0]
    # If an old non-storable product with the same name exists, it has stock moves
    # that prevent direct updates. Create a fresh storable product instead.
    # Drift note: Odoo 18 requires is_storable=True to allow stock operations.
    # type="consu" (Goods) + is_storable=True allows stock.quant creation.
    return S.create("product.product", {
        "name": name, "type": "consu", "is_storable": True,
        "list_price": cost * 1.5, "standard_price": cost,
    })


def seed_inventory() -> None:
    print("[seed] Inventory risk...")
    # Shortage: storable product, no stock, a confirmed delivery pulls the
    # forecast negative.
    short = _storable_product("PLAYGROUND Widget A (shortage)", 20.0)
    cust = _partner("PLAYGROUND Big Customer Co")
    so = S.create("sale.order", {
        "partner_id": cust,
        "order_line": [(0, 0, {"product_id": short, "product_uom_qty": 25,
                               "price_unit": 30.0})],
    })
    # Real confirmation so a delivery/outgoing stock.move is created =>
    # virtual_available goes negative. (Not a direct state write here.)
    S.call("sale.order", "action_confirm", [[so]])

    # Dead stock: on-hand quantity created directly as a quant (no dated
    # stock.move), so it counts as unmoved for 90+ days.
    dead = _storable_product("PLAYGROUND Widget B (dead stock)", 50.0)
    loc = S.search("stock.location", [("usage", "=", "internal")], limit=1)
    if not loc:
        raise SystemExit("[seed] no internal stock.location found")
    S.create("stock.quant", {
        "product_id": dead, "location_id": loc[0], "quantity": 100.0,
    })


def main() -> int:
    S.wait_for_odoo()
    if S.already_seeded():
        print("[seed] already seeded — nothing to do")
        return 0
    # Section functions are appended by later tasks and called here:
    #   seed_crm(); seed_sales(); seed_inventory();
    #   seed_receivables(); seed_hr(); seed_projects()
    seed_crm()
    seed_sales()
    seed_inventory()
    S.mark_seeded()
    print("[seed] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

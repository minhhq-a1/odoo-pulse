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


def main() -> int:
    S.wait_for_odoo()
    if S.already_seeded():
        print("[seed] already seeded — nothing to do")
        return 0
    # Section functions are appended by later tasks and called here:
    #   seed_crm(); seed_sales(); seed_inventory();
    #   seed_receivables(); seed_hr(); seed_projects()
    seed_crm()
    S.mark_seeded()
    print("[seed] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

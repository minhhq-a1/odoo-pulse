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


def main() -> int:
    S.wait_for_odoo()
    if S.already_seeded():
        print("[seed] already seeded — nothing to do")
        return 0
    # Section functions are appended by later tasks and called here:
    #   seed_crm(); seed_sales(); seed_inventory();
    #   seed_receivables(); seed_hr(); seed_projects()
    S.mark_seeded()
    print("[seed] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

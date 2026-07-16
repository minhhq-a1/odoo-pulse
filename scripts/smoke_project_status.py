#!/usr/bin/env python3
"""Read-only live baseline for the Project Status tool family.

Prints the numbers the spec pins for The Body Shop (project_id=59,
budget "PASX TBS", planned 1,593,314,320 / practical 1,735,766,746 —
verified 2026-07-15) so they can be eyeballed against the artifact.
Never writes. Requires the usual ODOO_* env vars (see scripts/smoke_live.py).

Usage: python scripts/smoke_project_status.py [PROJECT_ID]
"""

from __future__ import annotations

import json
import sys

from odoo_pulse.tools_project_detail import (
    portfolio_health,
    project_dashboard,
    project_subtask_hours,
)

PROJECT_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 59


def show(label: str, payload: str) -> dict:
    data = json.loads(payload)
    print(f"\n=== {label} ===")
    if "error" in data:
        print("ERROR:", data["error"])
        return data
    return data


def main() -> None:
    data = show("project_subtask_hours (both filters ON)",
                project_subtask_hours(
                    project_id=PROJECT_ID, only_closed_stages=True,
                    single_assignee_only=True, group_by_month=True))
    if "totals" in data:
        print("totals:", data["totals"])
        print("months:", len(data.get("by_month", [])),
              "| no_date_end:", data.get("no_date_end"))
        print("warnings:", data.get("warnings", []))

    data = show("project_dashboard (full load)",
                project_dashboard(project_id=PROJECT_ID))
    if "project" in data:
        print("project:", data["project"]["name"],
              "| health:", data["project"]["derived_health"])
        print("finance:", data.get("finance"))
        print("budgets:", [(b["id"], b["name"])
                           for b in data.get("budgets", [])])
        bd = data.get("budget_detail") or {}
        print("planned:", bd.get("planned"),
              "| practical:", bd.get("practical"),
              "| valid_cost:", bd.get("valid_cost"),
              "| valid_hours:", bd.get("valid_hours"))
        print("errors:", data.get("errors", {}))

    data = show("portfolio_health", portfolio_health())
    if "projects" in data:
        print("projects:", len(data["projects"]))
        for row in data["projects"][:5]:
            print(" ", row["project_id"], row["project"],
                  row["derived_health"], "burn:",
                  row["budget_burn_pct"])


if __name__ == "__main__":
    main()

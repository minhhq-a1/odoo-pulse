#!/usr/bin/env bash
# End-to-end playground check: boot the stack, wait for the seed to finish,
# assert every hero report tells its story, then tear everything down.
set -euo pipefail

COMPOSE="docker compose -f docker-compose.playground.yml"
export ODOO_URL=http://localhost:8069 ODOO_DB=playground \
       ODOO_USERNAME=admin ODOO_API_KEY=admin ODOO_READ_ONLY=true

cleanup() { $COMPOSE down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> Booting playground (fresh)"
$COMPOSE down -v >/dev/null 2>&1 || true
$COMPOSE up -d

echo "==> Waiting for the seed to complete (max ~10 min)"
for _ in $(seq 1 120); do
  state=$($COMPOSE ps -a --format '{{.Service}} {{.State}} {{.ExitCode}}' | awk '$1=="seed"{print $2, $3}')
  case "$state" in
    "exited 0") echo "    seed finished"; break ;;
    "exited "*) echo "    seed failed: $state"; $COMPOSE logs seed; exit 1 ;;
    *) sleep 5 ;;
  esac
done

echo "==> Verifying report tools"
python3 - <<'PY'
import json, sys
from odoo_pulse.tools_reports import (
    pipeline_review, sales_snapshot, receivables_health,
    inventory_risk, absence_overview, business_pulse,
)
checks = {
    "pipeline_review": lambda r: r["summary"]["verdict"] in ("at_risk", "off_track"),
    "sales_snapshot": lambda r: r["summary"]["stale_quotations"] >= 1,
    "receivables_health": lambda r: any(x["code"] == "aged_over_90" for x in r["risks"]),
    "inventory_risk": lambda r: r["summary"]["shortages"] >= 1 and r["summary"]["dead_stock_items"] >= 1,
    "absence_overview": lambda r: r["summary"]["off_today"] >= 1 and r["summary"]["pending_approvals"] >= 1,
    "business_pulse": lambda r: r["summary"]["verdict"] == "attention",
}
tools = {f.__name__: f for f in (pipeline_review, sales_snapshot, receivables_health,
                                 inventory_risk, absence_overview, business_pulse)}
failed = []
for name, ok in checks.items():
    r = json.loads(tools[name]())
    passed = ok(r)
    print(f"  {'OK  ' if passed else 'FAIL'} {name}: verdict={r['summary'].get('verdict')}")
    if not passed:
        failed.append(name)
sys.exit(1 if failed else 0)
PY

echo "==> Playground smoke PASSED"

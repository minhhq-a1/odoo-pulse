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

# Company-scoped paths: proves hr.leave.company_id exists live and the
# allowed_company_ids context plumbing works end-to-end (spec C1+C2).
r = json.loads(business_pulse(company=1))
ok_hr = "hr" not in r["summary"]["sections_unavailable"] \
    and r["breakdown"]["sections"]["hr"]["off_today"] >= 1
print(f"  {'OK  ' if ok_hr else 'FAIL'} business_pulse(company=1): hr section")
r = json.loads(inventory_risk(company=1))
ok_inv = r["summary"]["shortages"] >= 1
print(f"  {'OK  ' if ok_inv else 'FAIL'} inventory_risk(company=1): shortages")
if not (ok_hr and ok_inv):
    failed.append("company_scoped")
sys.exit(1 if failed else 0)
PY

echo "==> Playground smoke PASSED"

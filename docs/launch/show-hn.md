# Show HN post

**Title (79 chars max, no emoji):**
Show HN: Odoo-pulse – an AI business analyst for Odoo ERP, over MCP

**URL:** https://github.com/minhhq-a1/odoo-pulse

**First comment (post immediately after submitting):**

Hi HN — I work at an Odoo partner, and the question I get most from
managers isn't "update this record", it's "how are we actually doing?"
Answering it means opening six dashboards: CRM, Sales, Invoicing,
Inventory, Timesheets, Time Off.

MCP servers for Odoo already exist and do CRUD well (tuanle96/mcp-odoo,
ivnvxd/mcp-server-odoo — both good). So I built the layer on top instead:
every tool answers one management question in one call and returns
numbers + highlights + risks + a verdict (on-track / at-risk / off-track).

`business_pulse` is the hero: one call = yesterday's sales, new leads,
overdue invoices, late tasks, who's off today, with a company-wide verdict.
Also: pipeline_review, receivables_health (AR/AP aging), inventory_risk,
sales_snapshot, absence_overview, project_status_report...

Design choices that mattered:
- Read-only by default; writes need four independent opt-ins
  (env switch + model allow-list + delete flag + per-call confirm).
- Nothing to install inside Odoo — plain XML-RPC external API, works on
  Odoo Online / Odoo.sh / on-premise (18+). CI boots a real Odoo 18 and
  19 nightly and asserts every report tells its story on both.
- Mixed currencies are never silently summed — you get a by_currency
  breakdown and a risk flag instead of a wrong total.
- No live Odoo needed to try it: `docker compose -f
  docker-compose.playground.yml up -d` boots a seeded demo with a story
  (stalled deal, 90-day overdue invoice, stock shortage, someone off).

Would love feedback on the report design — especially what "one-call
questions" you'd want next.

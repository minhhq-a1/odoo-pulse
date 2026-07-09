# r/Odoo post

**Title:** I built an open-source "AI business analyst" for Odoo — ask
"how's the company doing?" and get one report with a verdict (MIT, works
on Online/sh/on-premise)

**Body:**

Author here (I work at an Odoo partner). This is an MCP server, meaning it
plugs Odoo into Claude / Cursor / VS Code — but unlike the existing
CRUD-style connectors, every tool answers a whole management question in
one call:

- business_pulse — morning briefing: yesterday's sales, new leads, overdue
  invoices, late tasks, who's off — with an on-track/at-risk verdict
- receivables_health — AR/AP aging buckets, % overdue, top debtors
- pipeline_review — funnel by stage, stalled deals, weighted revenue
- inventory_risk, sales_snapshot, absence_overview, project_status_report, ...

Nothing to install inside Odoo — it's the standard XML-RPC external API
with an API key, so it works on Odoo Online too. Read-only by default
(writes need four separate opt-ins). Odoo 18+ for the report tools.

There's a docker-compose playground with seeded demo data if you want to
try it without touching a real database. Repo (MIT):
https://github.com/minhhq-a1/odoo-pulse

What one-call questions would you want? That's the roadmap.

# odoo-pulse

[![CI](https://github.com/minhhq-a1/odoo-pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/minhhq-a1/odoo-pulse/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/odoo-pulse)](https://pypi.org/project/odoo-pulse/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

<!-- mcp-name: io.github.minhhq-a1/odoo-pulse -->

**An AI business analyst for your [Odoo](https://www.odoo.com) ERP.** Ask one
question, get one answer — numbers, highlights, risks, and a verdict
(on-track / at-risk / off-track) — over the [Model Context
Protocol](https://modelcontextprotocol.io). CRUD bridges to Odoo already exist;
this is the analytics layer that sits on top.

![business_pulse — a one-call company briefing](assets/business_pulse.gif)

## The analyst tools

Each tool answers a whole management question in a single call, returning a
structured report with a verdict — not a raw dump you have to interpret.

| Tool | Answers |
| --- | --- |
| `business_pulse` ⭐ | The morning briefing: yesterday's sales, new leads, overdue invoices, late tasks, who's off — with a company-wide verdict |
| `pipeline_review` | CRM funnel by stage, stalled deals, weighted revenue, recent win rate |
| `sales_snapshot` | Revenue this period vs last (Δ%), top customers/products, stale quotations |
| `receivables_health` | AR/AP aging buckets, % overdue, top debtors |
| `inventory_risk` | Shortages (negative forecast) and dead stock |
| `absence_overview` | Who's off this week, pending approvals, thin-coverage departments |
| `procurement_watch` | Purchasing: late receipts, stale RFQs, open spend per vendor |
| `production_health` | Manufacturing: orders behind their planned start, stuck WIP |
| `team_workload` · `project_status_report` · `standup_digest` | Project delivery: overloaded members, at-risk projects, and a daily stand-up digest |

Every money-reporting tool takes an optional
`company=` filter and flags
mixed-currency totals instead of silently summing them; verdict cut-offs
(stalled %, overdue %, growth %) are parameters, so you can calibrate them
to your business.

### Timezone semantics

All report tools take `timezone_offset` (default `7`). Odoo stores datetime
fields in UTC; the tools shift them by `timezone_offset` hours before
bucketing by calendar day, and day windows in domains are expressed as UTC
datetime boundaries. Date-only fields (e.g. `project.milestone.deadline`,
`invoice_date_due`, `project.task.date_deadline`) are compared as-is.

### Version-dependent fields

`find_partner` searches `mobile` only on instances that still have it (removed in Odoo 19), and `list_timesheets` reports an actionable error when `hr_timesheet` is not installed.

Under the hood it's the standard Odoo XML-RPC external API — nothing to install
inside Odoo, works on Odoo Online, Odoo.sh, and on-premise. **Requires
Odoo 18+**: the generic tools (`search_read`, `read_records`, …) still run on
older versions, but the report tools are not guaranteed there.

## Try the playground

No Odoo account? Boot a demo Odoo pre-seeded with a story to tell (a stalled
deal, a 90-day-overdue invoice, a stock shortage, someone off today):

```bash
docker compose -f docker-compose.playground.yml up -d
```

First boot pulls ~4 GB of images (Odoo + Postgres) and seeds the demo data —
allow 5-10 minutes depending on your connection. Then point Claude at it and
ask it to **`run business_pulse`**. Full walkthrough:
[docs/playground.md](docs/playground.md).

## Install & connect

Add it to Claude Code (no install step — `uvx` fetches it):

```bash
claude mcp add odoo-pulse \
  --env ODOO_URL=https://acme.odoo.com \
  --env ODOO_DB=acme \
  --env ODOO_USERNAME=you@example.com \
  --env ODOO_API_KEY=your-api-key \
  --env ODOO_READ_ONLY=true \
  -- uvx odoo-pulse
```

Generate the API key in Odoo under **Settings → Users → (your user) → Account
Security → New API Key**. Config for **Claude Desktop** and **Cursor**, plus pip
and Docker alternatives: [docs/install.md](docs/install.md).

Or one-click:

[![Install in Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/en/install-mcp?name=odoo-pulse&config=eyJjb21tYW5kIjogInV2eCIsICJhcmdzIjogWyJvZG9vLXB1bHNlIl0sICJlbnYiOiB7Ik9ET09fVVJMIjogImh0dHBzOi8vYWNtZS5vZG9vLmNvbSIsICJPRE9PX0RCIjogImFjbWUiLCAiT0RPT19VU0VSTkFNRSI6ICJ5b3VAZXhhbXBsZS5jb20iLCAiT0RPT19BUElfS0VZIjogInlvdXItYXBpLWtleSIsICJPRE9PX1JFQURfT05MWSI6ICJ0cnVlIn19)
[![Install in VS Code](https://img.shields.io/badge/VS%20Code-Install%20odoo--pulse-0098FF?logo=githubcopilot&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=odoo-pulse&config=%7B%22name%22%3A%20%22odoo-pulse%22%2C%20%22command%22%3A%20%22uvx%22%2C%20%22args%22%3A%20%5B%22odoo-pulse%22%5D%2C%20%22env%22%3A%20%7B%22ODOO_URL%22%3A%20%22https%3A%2F%2Facme.odoo.com%22%2C%20%22ODOO_DB%22%3A%20%22acme%22%2C%20%22ODOO_USERNAME%22%3A%20%22you%40example.com%22%2C%20%22ODOO_API_KEY%22%3A%20%22your-api-key%22%2C%20%22ODOO_READ_ONLY%22%3A%20%22true%22%7D%7D)

## Read-only by default, safe writes when you want them

The server is read-only out of the box. Writes require four independent controls
to line up (`ODOO_READ_ONLY=false`, a model allow-list, a delete flag, and a
per-call `confirm=true` after a dry-run preview); system models are never
writable. Details: [docs/tools.md#write-operations](docs/tools.md#write-operations).

## More tools

Beyond the analyst reports, there are ~60 model-aware query tools spanning CRM,
Sales, Inventory, Accounting, HR, Project, Manufacturing, PoS, and Enterprise
apps — opt in via `ODOO_TOOL_GROUPS`. Full catalogue and configuration:
[docs/tools.md](docs/tools.md).

## Testing

The suite mocks the XML-RPC layer, so **no real Odoo or network is needed**:

```bash
pip install -e ".[dev]"
pytest
```

For a live check against a real Odoo (read-only), see
[docs/tools.md#live-smoke-test-against-a-real-odoo](docs/tools.md#live-smoke-test-against-a-real-odoo).

## License

[MIT](LICENSE)

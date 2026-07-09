# Tool catalogue

`odoo-pulse` exposes tools in groups, selected via `ODOO_TOOL_GROUPS`
(default `core,reports`). The **analyst report tools** — the reason to use this
server — are listed with one-line summaries in the
[README](../README.md#the-analyst-tools); full parameters are in
[Analyst reports](#analyst-reports) below. This page is the full reference for
everything else too.

## Tool groups

Set `ODOO_TOOL_GROUPS` (comma-separated) to choose what the server exposes:

| Group | Contents |
| --- | --- |
| `core` | Generic model-agnostic tools (below) + write tools |
| `reports` | The analyst report tools (see README) |
| `business` | Contacts / CRM / Sales / Purchase / Inventory / Accounting wrappers |
| `hr` | HR tools |
| `projects` | Project tools |
| `operations` | Manufacturing / PoS / Repair / Maintenance / Fleet / Helpdesk |
| `engagement` | Events / Calendar / Activities / Surveys / Marketing |
| `niche` | Enterprise & specialised apps |
| `all` | Everything |

Default (`core,reports`) is 26 tools — reports are the front door, the domain
wrappers below are "power user mode".

## Analyst reports

Full parameter reference for the `reports` group. Every tool is read-only,
takes `timezone_offset` (default `7` = Asia/Ho_Chi_Minh) to anchor "today",
and returns the standard report envelope (`summary`, `breakdown`,
`highlights`, `risks`) described in the README.

### `business_pulse`

One-call company briefing: sales, leads, receivables, tasks, absences.

- `timezone_offset` (default `7`): UTC offset for "today".
- `company`: Optional company name (ilike) or id; scopes every section.

### `pipeline_review`

Report the health of the CRM pipeline, in one call.

- `salesperson`: Optional filter on `user_id.name` (ilike).
- `team`: Optional filter on `team_id.name` (ilike).
- `stalled_days` (default `14`): Days without a stage change before a deal
  counts as stalled.
- `lookahead_days` (default `30`): Days ahead that count as "closing soon".
- `win_rate_days` (default `90`): Look-back window for the won/lost ratio.
- `top_n` (default `5`): Max stalled deals listed in the breakdown.
- `timezone_offset` (default `7`): UTC offset for "today".
- `company`: Optional company name (ilike) or id; scopes every count and
  total to that company.
- `stalled_pct_at_risk` (default `25`): Stalled share (%) at which the
  verdict drops to `at_risk`.
- `stalled_pct_off_track` (default `50`): Stalled share (%) at which the
  verdict drops to `off_track`.

### `sales_snapshot`

Report how sales are going versus the previous period, in one call.

- `period_days` (default `7`): Length of the comparison window in days.
- `stale_quote_days` (default `7`): Age in days after which a draft/sent
  quotation counts as stale.
- `top_n` (default `5`): Rows in the top-customers / top-products lists.
- `timezone_offset` (default `7`): UTC offset for "today".
- `growth_threshold_pct` (default `10`): Delta (%) beyond which the verdict
  is growing / declining.
- `company`: Optional company name (ilike) or id to scope the report.
- `trend_weeks` (default `8`): Weeks of history bucketed into the
  `weekly_revenue` trend series; `0` disables the extra query.

### `receivables_health`

Report AR/AP aging and who owes what, in one call.

- `top_n` (default `5`): Rows in the top-overdue-customers list.
- `timezone_offset` (default `7`): UTC offset for "today".
- `company`: Optional company name (ilike) or id to scope the report.
- `overdue_pct_at_risk` (default `25`): Overdue AR share (%) that drops the
  verdict to `at_risk`.
- `overdue_pct_off_track` (default `50`): Overdue AR share (%) that drops the
  verdict to `off_track`.

### `inventory_risk`

Report stock at risk — shortages and dead stock — in one call.

- `dead_stock_days` (default `90`): No-movement window for dead stock.
- `top_n` (default `10`): Rows listed per breakdown section.
- `timezone_offset` (default `7`): UTC offset for "today".
- `company`: Optional company name (ilike) or id to scope the report.

### `absence_overview`

Report who is off and where coverage is thin, in one call.

- `days` (default `14`): Look-ahead window in days.
- `coverage_threshold` (default `0.3`): Department share off in the window
  that counts as a coverage risk.
- `timezone_offset` (default `7`): UTC offset for "today".

### `procurement_watch`

Report purchasing health — late receipts and stale RFQs — in one call.

- `late_grace_days` (default `0`): Days past `date_planned` before a receipt
  counts as late.
- `rfq_stale_days` (default `7`): Age in days after which a draft/sent RFQ
  counts as stale.
- `top_n` (default `5`): Rows in the late-receipts / top-vendors lists.
- `timezone_offset` (default `7`): UTC offset for "today".
- `company`: Optional company name (ilike) or id to scope the report.

### `production_health`

Report manufacturing health — late starts and stuck orders — in one call.

- `stuck_days` (default `14`): Days an order may run (progress/to_close)
  before it counts as stuck.
- `top_n` (default `5`): Rows in the behind-start / stuck lists.
- `timezone_offset` (default `7`): UTC offset for "today".
- `company`: Optional company name (ilike) or id to scope the report.

### `team_workload` · `project_status_report` · `standup_digest`

Project delivery reports — per-assignee workload, portfolio-wide project health, and a daily stand-up digest. Same composition style as the reports above (filters, thresholds, `timezone_offset`); see the docstrings in `odoo_pulse/tools_workflows.py` for the full argument list.

### Multi-company / multi-currency

Reports never convert currencies. When the rows behind a total span more
than one currency, the report adds a `by_currency` breakdown to `summary`
and a `mixed_currencies` (or `mixed_companies` / `multi_company_totals`)
entry to `risks`. Pass `company=<name or id>` to scope a report to one
company.

## Generic (model-agnostic)

| Tool | Purpose |
| --- | --- |
| `odoo_version` | Connectivity / version check |
| `list_models` | Discover available models (optionally filtered) |
| `get_model_fields` | Inspect a model's schema (`fields_get`) |
| `search_read` | Query records with an Odoo domain filter |
| `search_count` | Count records matching a domain |
| `read_records` | Fetch specific records by id |
| `aggregate_records` | Group and aggregate server-side (`read_group` ≤18, `formatted_read_group` 19+) |
| `read_attachment` | Read an `ir.attachment`'s metadata and base64 data under a size cap |

## Domain convenience wrappers

Pre-built filters and field sets for common business objects, so the LLM doesn't
need to know technical model/field names. Tools whose Odoo app is not installed
return a friendly error instead of failing.

### Contacts / CRM / Sales / Purchase (`business`)

| Tool | Module | Purpose |
| --- | --- | --- |
| `find_partner` | Contacts | Find contacts/companies by name, email, phone, ref, VAT |
| `list_opportunities` | CRM | List opportunities, filter by stage / salesperson |
| `list_sale_orders` | Sales | List sales orders by customer / state / date range |
| `get_sale_order` | Sales | One order with its line items |
| `list_purchase_orders` | Purchase | List purchase orders by vendor / state |
| `get_purchase_order` | Purchase | One purchase order with its line items |

### Inventory / Accounting (`business`)

| Tool | Module | Purpose |
| --- | --- | --- |
| `find_products` | Inventory | Products with on-hand & forecasted qty |
| `check_stock` | Inventory | On-hand stock per location (`stock.quant`) |
| `list_pickings` | Inventory | Transfers: deliveries / receipts / internal |
| `list_invoices` | Accounting | Invoices/bills, filter unpaid / type / date |
| `get_invoice` | Accounting | One invoice/bill with its line items |
| `list_payments` | Accounting | Customer/vendor payments |

### HR (`hr`)

| Tool | Purpose |
| --- | --- |
| `list_employees` | Employees, filter by department |
| `list_departments` | Departments with headcount |
| `list_time_off` | Leave / time-off requests |
| `list_expenses` | Employee expenses |
| `list_job_positions` | Recruitment job positions |
| `list_applicants` | Recruitment applicants |
| `list_attendances` | Check in/out records |

### Project (`projects`)

| Tool | Purpose |
| --- | --- |
| `list_projects` | Projects |
| `list_tasks` | Tasks by project / assignee / stage |
| `list_timesheets` | Timesheet entries |

(The composed project analysts — `team_workload`, `project_status_report`, `standup_digest` — are in the `reports` group; see the README.)

### Operations (`operations`)

| Tool | Purpose |
| --- | --- |
| `list_manufacturing_orders` | Manufacturing orders (MRP) |
| `list_boms` | Bills of materials |
| `list_pos_orders` | Point of Sale orders |
| `list_pos_sessions` | PoS sessions |
| `list_repair_orders` | Repair orders |
| `list_maintenance_requests` | Maintenance requests |
| `list_equipment` | Maintenance equipment / assets |
| `list_helpdesk_tickets` | Helpdesk tickets (Enterprise) |
| `list_vehicles` | Fleet vehicles |

### Engagement (`engagement`)

| Tool | Purpose |
| --- | --- |
| `list_events` | Events |
| `list_event_registrations` | Event attendees |
| `list_calendar_events` | Calendar meetings |
| `list_activities` | Scheduled activities / to-dos |
| `list_surveys` | Surveys with response counts |
| `list_email_campaigns` | Email marketing mailings |

### Niche / specialised (`niche`)

Mostly Enterprise apps — return a friendly error if not installed.

| Tool | Module | Purpose |
| --- | --- | --- |
| `list_subscriptions` | Subscriptions | Recurring subscriptions |
| `list_sign_requests` | Sign | E-signature requests |
| `list_documents` | Documents | Document files |
| `list_knowledge_articles` | Knowledge | Knowledge articles |
| `list_approval_requests` | Approvals | Approval requests |
| `list_lunch_orders` | Lunch | Lunch orders |
| `list_quality_checks` | Quality | Quality checks |
| `list_quality_alerts` | Quality | Quality alerts |
| `list_planning_slots` | Planning | Shifts / slots |
| `list_courses` | eLearning | Courses |
| `list_loyalty_programs` | Loyalty | Programs / coupons / gift cards |
| `list_loyalty_cards` | Loyalty | Loyalty / gift cards |
| `list_memberships` | Membership | Membership lines |
| `list_payslips` | Payroll | Payslips |
| `list_appraisals` | Appraisal | Employee appraisals |
| `list_social_posts` | Social | Social media posts |
| `list_website_visitors` | Website | Website visitors |
| `list_engineering_changes` | PLM | Engineering change orders (`mrp.eco`) |
| `list_iot_devices` | IoT | IoT devices |
| `list_notes` | Notes | Notes |

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `ODOO_URL` | yes | — | Base URL, e.g. `https://acme.odoo.com` |
| `ODOO_DB` | yes | — | Database name |
| `ODOO_USERNAME` | yes | — | Login email |
| `ODOO_API_KEY` | yes | — | API key (used as password) |
| `ODOO_READ_ONLY` | no | `true` | Block write methods when true |
| `ODOO_MAX_RECORDS` | no | `200` | Cap on records per query |
| `ODOO_VERIFY_SSL` | no | `true` | Set false for self-signed / private-CA certs |
| `ODOO_TIMEOUT` | no | `30` | Socket timeout (seconds) per XML-RPC call |
| `ODOO_WRITABLE_MODELS` | no | *(empty)* | Comma-separated models allowed for writes |
| `ODOO_ALLOW_DELETE` | no | `false` | Set true to allow record deletion |
| `ODOO_SCHEMA_CACHE_TTL` | no | `300` | Seconds to cache `fields_get`. `0` disables |
| `ODOO_SCHEMA_CACHE_MAX` | no | `64` | Max cached schema entries (LRU eviction) |
| `ODOO_MAX_ATTACHMENT_BYTES` | no | `1048576` | Max attachment bytes returned by `read_attachment` |
| `ODOO_TOOL_GROUPS` | no | `core,reports` | Tool groups to expose (see top of this page) |

## Write operations

Writes are **off by default**. Four independent controls must line up before any
record can change:

| Control | Default | Effect |
|---|---|---|
| `ODOO_READ_ONLY` | `true` | Master switch. Must be `false` to write at all. |
| `ODOO_WRITABLE_MODELS` | *(empty)* | Comma-separated allow-list. Only listed models are writable. |
| `ODOO_ALLOW_DELETE` | `false` | Must be `true` to allow `delete_records`. |
| `confirm` (tool arg) | `false` | Each write tool returns a dry-run preview until called with `confirm=true`. |

System models (`ir.*`, `base*`, `res.users`, `res.groups`, `res.company`,
`ir.config_parameter`, `ir.model`, …) are **never** writable, even if listed in
`ODOO_WRITABLE_MODELS`.

Write tools: `create_record`, `update_records`, `delete_records`, plus helpers
`create_lead`, `create_contact`, `create_task`, `confirm_sale_order`.

Example — enable leads and create one:

```bash
ODOO_READ_ONLY=false
ODOO_WRITABLE_MODELS=crm.lead
```

```text
create_lead(name="ACME deal", email="a@b.com")                # -> preview, no write
create_lead(name="ACME deal", email="a@b.com", confirm=true)  # -> {"created_id": 42}
```

The `create_*` helpers accept an `extra_values` dict for fields they don't model
directly — useful when an instance adds custom mandatory fields. Keys in
`extra_values` override the helper's own mapping:

```text
create_lead(name="ACME deal", extra_values={"presales_id": 5}, confirm=true)
```

## Running & debugging

```bash
# stdio transport (for MCP clients)
odoo-pulse
```

### MCP Inspector

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) lets you
browse and call tools interactively in a web UI.

```bash
npx @modelcontextprotocol/inspector odoo-pulse
```

Open `http://localhost:5173`, click **Connect**, then call `odoo_version`. The
server loads `.env` automatically from the working directory.

### Live smoke test (against a real Odoo)

`scripts/smoke_live.py` connects with your `.env` credentials and calls every
read-only list tool once — staying read-only, never writing:

```bash
cp .env.example .env      # fill in your ODOO_* credentials
python scripts/smoke_live.py
```

Each tool reports `ok` (works, with record count), `skip` (app not installed —
expected), or `CHECK` (model exists but a field differs on your version — adjust
the field list in the matching tool). Options: `--env <path>` (default `.env`),
`--limit <n>` (default 1), `--no-color`.

## Example queries

Once connected, you can ask things like:

- "List the 10 most recent unpaid customer invoices this month."
- "What fields does `sale.order` have?"
- "How many leads are in the 'New' stage?"
- "Show contact details for partner id 42."

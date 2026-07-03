# Tool catalogue

`odoo-pulse` exposes tools in groups, selected via `ODOO_TOOL_GROUPS`
(default `core,reports`). The **analyst report tools** — the reason to use this
server — are documented in the [README](../README.md#the-analyst-tools). This
page is the full reference for everything else.

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

Default (`core,reports`) is ~20 tools — reports are the front door, the domain
wrappers below are "power user mode".

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

(The composed project analysts — `sprint_health`, `team_workload`,
`project_status_report` — are in the `reports` group; see the README.)

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

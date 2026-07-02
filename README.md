# odoo-mcp

[![CI](https://github.com/minhhq-a1/odoo-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/minhhq-a1/odoo-mcp/actions/workflows/ci.yml)

An [MCP](https://modelcontextprotocol.io) server that gives an MCP client
(e.g. Claude) **read-only** access to an [Odoo](https://www.odoo.com) instance
over the standard XML-RPC external API.

It exposes generic, model-agnostic tools so the LLM can discover schema and
query any Odoo model — `res.partner`, `sale.order`, `account.move`,
`stock.quant`, etc. — without a custom Odoo addon.

## Why XML-RPC

The XML-RPC external API works against any Odoo deployment (Odoo Online/SaaS,
Odoo.sh, on-premise) using just a URL + database + username + API key. Nothing
needs to be installed inside Odoo.

## Tools

### Generic (model-agnostic)

| Tool | Purpose |
| --- | --- |
| `odoo_version` | Connectivity / version check |
| `list_models` | Discover available models (optionally filtered) |
| `get_model_fields` | Inspect a model's schema (`fields_get`) |
| `search_read` | Query records with an Odoo domain filter |
| `search_count` | Count records matching a domain |
| `read_records` | Fetch specific records by id |
| `aggregate_records` | Group and aggregate records server-side (`read_group` on <=18, `formatted_read_group` on 19+) |
| `read_attachment` | Read an `ir.attachment` metadata and base64 data under size cap |

### Domain (convenience wrappers)

Pre-built filters and field sets for common business objects, so the LLM
doesn't need to know technical model/field names. Tools whose Odoo app is not
installed return a friendly error instead of failing.

**Contacts / CRM / Sales / Purchase**

| Tool | Module | Purpose |
| --- | --- | --- |
| `find_partner` | Contacts | Find contacts/companies by name, email, phone, ref, VAT |
| `list_opportunities` | CRM | List opportunities, filter by stage / salesperson |
| `list_sale_orders` | Sales | List sales orders by customer / state / date range |
| `get_sale_order` | Sales | One order with its line items |
| `list_purchase_orders` | Purchase | List purchase orders by vendor / state |
| `get_purchase_order` | Purchase | One purchase order with its line items |

**Inventory / Accounting**

| Tool | Module | Purpose |
| --- | --- | --- |
| `find_products` | Inventory | Products with on-hand & forecasted qty |
| `check_stock` | Inventory | On-hand stock per location (`stock.quant`) |
| `list_pickings` | Inventory | Transfers: deliveries / receipts / internal |
| `list_invoices` | Accounting | Invoices/bills, filter unpaid / type / date |
| `get_invoice` | Accounting | One invoice/bill with its line items |
| `list_payments` | Accounting | Customer/vendor payments |

**HR**

| Tool | Purpose |
| --- | --- |
| `list_employees` | Employees, filter by department |
| `list_departments` | Departments with headcount |
| `list_time_off` | Leave / time-off requests |
| `list_expenses` | Employee expenses |
| `list_job_positions` | Recruitment job positions |
| `list_applicants` | Recruitment applicants |
| `list_attendances` | Check in/out records |

**Project**

| Tool | Purpose |
| --- | --- |
| `list_projects` | Projects |
| `list_tasks` | Tasks by project / assignee / stage |
| `list_timesheets` | Timesheet entries |
| `sprint_health` | One-call sprint status: completion %, overdue/upcoming buckets, per-stage & per-assignee breakdown, risks, and an on-track / at-risk / off-track verdict. |
| `team_workload` | One-call load picture: open tasks per assignee with overdue / due-soon / high-priority / no-deadline tallies, overloaded-member and unassigned-work flags, and a balanced / action-needed verdict. |
| `project_status_report` | One-call portfolio health: each project's derived verdict (off-track / at-risk / on-track) from overdue milestones and end date, shown against the PM's declared status with a divergence flag, ranked by risk. |

**Operations**

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

**Engagement**

| Tool | Purpose |
| --- | --- |
| `list_events` | Events |
| `list_event_registrations` | Event attendees |
| `list_calendar_events` | Calendar meetings |
| `list_activities` | Scheduled activities / to-dos |
| `list_surveys` | Surveys with response counts |
| `list_email_campaigns` | Email marketing mailings |

**Niche / specialised** (mostly Enterprise apps — return a friendly error if not installed)

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

Write operations (`create`/`write`/`unlink`) are supported but gated by multiple safety controls. See the [Write operations](#write-operations) section below.

## Setup

```bash
# 1. Install (editable, with the MCP runtime)
pip install -e .

# 2. Configure credentials
cp .env.example .env
# edit .env with your Odoo URL, db, username and API key
```

Generate an API key in Odoo under
**Settings → Users → (your user) → Account Security → New API Key**.

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `ODOO_URL` | yes | — | Base URL, e.g. `https://acme.odoo.com` |
| `ODOO_DB` | yes | — | Database name |
| `ODOO_USERNAME` | yes | — | Login email |
| `ODOO_API_KEY` | yes | — | API key (used as password) |
| `ODOO_READ_ONLY` | no | `true` | Block write methods when true |
| `ODOO_MAX_RECORDS` | no | `200` | Cap on records per query |
| `ODOO_VERIFY_SSL` | no | `true` | Set to false for self-signed / private-CA certificates |
| `ODOO_TIMEOUT` | no | `30` | Socket timeout (seconds) per XML-RPC call |
| `ODOO_WRITABLE_MODELS` | no | *(empty)* | Comma-separated list of models allowed for writes |
| `ODOO_ALLOW_DELETE` | no | `false` | Set to true to allow record deletion |
| `ODOO_SCHEMA_CACHE_TTL` | no | `300` | Seconds to cache `fields_get` results. `0` disables. |
| `ODOO_SCHEMA_CACHE_MAX` | no | `64` | Max cached schema entries (LRU eviction). |
| `ODOO_MAX_ATTACHMENT_BYTES` | no | `1048576` | Max attachment size returned as base64 by `read_attachment`. |
| `ODOO_TOOL_GROUPS` | no | `core,reports` | Tool groups to expose: `core`, `reports`, `business`, `hr`, `projects`, `operations`, `engagement`, `niche`, or `all` |

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
create_lead(name="ACME deal", email="a@b.com")          # -> preview, no write
create_lead(name="ACME deal", email="a@b.com", confirm=true)  # -> {"created_id": 42}
```

The `create_*` helpers accept an `extra_values` dict for fields they don't model
directly — useful when an instance adds custom mandatory fields. Keys in
`extra_values` override the helper's own mapping:

```text
create_lead(name="ACME deal", extra_values={"presales_id": 5}, confirm=true)
```

## Running

```bash
# stdio transport (for MCP clients)
odoo-mcp
```

### MCP Inspector

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) lets you browse and call tools interactively in a web UI — useful for exploring the server or debugging tool calls without a full MCP client.

```bash
npx @modelcontextprotocol/inspector odoo-mcp
```

Open `http://localhost:5173`, click **Connect**, then call `odoo_version` to verify the connection. The server loads `.env` automatically from the working directory, so run the command from the project root.

### Claude Desktop / Claude Code config

Add to your MCP client config (env vars can be passed inline instead of `.env`):

```json
{
  "mcpServers": {
    "odoo": {
      "command": "odoo-mcp",
      "env": {
        "ODOO_URL": "https://acme.odoo.com",
        "ODOO_DB": "acme",
        "ODOO_USERNAME": "you@example.com",
        "ODOO_API_KEY": "your-api-key",
        "ODOO_READ_ONLY": "true"
      }
    }
  }
}
```

## Example queries

Once connected, you can ask things like:

- "List the 10 most recent unpaid customer invoices this month."
- "What fields does `sale.order` have?"
- "How many leads are in the 'New' stage?"
- "Show contact details for partner id 42."

## Testing

The suite mocks the XML-RPC layer, so **no real Odoo instance or network is
needed**. It covers config parsing, the client (read-only guard, limit
capping, argument forwarding, fault handling), the domain helpers, and every
domain tool (correct model + domain construction).

```bash
pip install -e ".[dev]"
pytest
```

### Live smoke test (against a real Odoo)

To verify a real connection and catch field-name mismatches on your specific
Odoo version, run the live smoke script. It connects with your `.env`
credentials and calls every read-only list tool once — staying read-only and
never writing anything:

```bash
cp .env.example .env      # fill in your ODOO_* credentials
python scripts/smoke_live.py
```

Each tool is reported as:

- `ok` — works, with the number of records returned
- `skip` — the app/model is not installed (expected, harmless)
- `CHECK` — the model exists but a field differs on your version; adjust the
  field list in the matching tool

Options: `--env <path>` (default `.env`), `--limit <n>` (records per tool,
default 1), `--no-color`.

## Roadmap

- [x] Domain-specific convenience tools across all major + niche Odoo modules
- [x] Automated test suite (mocked XML-RPC, no live instance needed)
- [x] CI on GitHub Actions (pytest on Python 3.10–3.12)
- [x] Write tools (`create` / `write` / `unlink`) behind a confirmation flow
- [x] Model allow/deny lists for finer access control
- [ ] Optional JSON-RPC transport

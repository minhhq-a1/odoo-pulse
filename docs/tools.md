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
| `core` | Generic model-agnostic tools (below) + write tools + the `odoo://{model}/{id}` record resource |
| `reports` | The analyst report tools (see README) |
| `business` | Contacts / CRM / Sales / Purchase / Inventory / Accounting wrappers |
| `hr` | HR tools |
| `projects` | Project tools |
| `operations` | Manufacturing / PoS / Repair / Maintenance / Fleet / Helpdesk |
| `engagement` | Events / Calendar / Activities / Surveys / Marketing |
| `niche` | Enterprise & specialised apps |
| `all` | Everything |

Default (`core,reports`) is 31 tools plus the `odoo://{model}/{id}` MCP
resource (one record as JSON, all stored fields) — reports are the front
door, the domain wrappers below are "power user mode".

## Analyst reports

Full parameter reference for the `reports` group. Every tool is read-only,
takes `timezone_offset` (default `7` = Asia/Ho_Chi_Minh) to anchor "today",
and returns the standard report envelope (`summary`, `breakdown`,
`highlights`, `risks`) described in the README.

### `business_pulse`

One-call company briefing: sales, leads, receivables, tasks, absences.

- `timezone_offset` (default `7`): UTC offset for "today".
- `company`: Optional company name (ilike) or id; scopes every section.

The `sales` and `receivables` sections report a scalar `revenue` /
`overdue_amount` plus either a single `currency` (all rows share one
currency) or a `by_currency` breakdown with `mixed_currencies: true` and
`totals_comparable: false` on the section — and a top-level `mixed_currencies`
risk entry — when rows span more than one currency; see "Multi-company /
multi-currency" below. `hr.off_today` counts
unique employees with an approved leave covering today, not leave-request
rows. `projects.overdue_tasks` compares `project.task.date_deadline` as a UTC
datetime bound when that field is a `datetime` on this instance, or as a
plain date otherwise (schema-aware).

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

`summary.receipt_tracking_available` reports whether either receipt-tracking
signal exists on this instance (`purchase.order.receipt_status`, or
`qty_received` on `purchase.order.line`). `summary.remaining_value_available`
reports specifically whether the line-level `qty_received` signal is
available, which lets `open_value` reflect only the undelivered remainder of
a partially received PO instead of its full order total. When only
`receipt_status` is available (no line-level quantities), `risks` includes a
`partial_receipt_value_estimated` entry — partially received POs are valued
at their full order total. When neither signal is available, `risks`
includes a `receipt_tracking_unavailable` entry — the confirmed-PO
population and `open_value` may include goods already received.

### `production_health`

Report manufacturing health — late starts and stuck orders — in one call.

- `stuck_days` (default `14`): Days an order may run (progress/to_close)
  before it counts as stuck.
- `top_n` (default `5`): Rows in the behind-start / stuck lists.
- `timezone_offset` (default `7`): UTC offset for "today".
- `company`: Optional company name (ilike) or id to scope the report.

### `project_profitability`

Report delivery hours, money and budget burn per project in one call.

- `project`: Optional project-name filter (ilike). Exactly one match adds
  per-employee / per-task drill-down breakdowns.
- `manager`: Optional project-manager filter (`user_id.name` ilike).
- `customer`: Optional customer filter (`partner_id.name` ilike).
- `date_from` / `date_to`: Optional `YYYY-MM-DD` bounds on logged hours and
  analytic amounts. Allocated hours and budgets stay lifetime totals, so any
  date filter disables the burn verdicts (`verdict: "n/a"`).
- `top_n` (default `5`): Rows in the drill-down breakdowns.
- `burn_pct_at_risk` (default `80`) / `burn_pct_off_track` (default `100`):
  Worst burn % thresholds for the per-project verdict.
- `timezone_offset` (default `7`): UTC offset for "today".

### `project_budget`

Report planned vs actual budget per project, line by line (Budgets app).
Matches budget lines to projects by a line-level `project_id` m2o when the
instance has one, else through the project's analytic account, and flags
analytic spend the budget lines do not capture.

- `project`: Optional project-name filter (ilike). Exactly one match adds a
  per-line breakdown (planned / practical / theoretical / burn %).
- `manager`: Optional project-manager filter (`user_id.name` ilike).
- `customer`: Optional customer filter (`partner_id.name` ilike).
- `top_n` (default `10`): Rows in the per-line breakdown.
- `burn_pct_at_risk` (default `80`) / `burn_pct_off_track` (default `100`):
  Burn % thresholds for the per-project verdict.
- `timezone_offset` (default `7`): UTC offset for "today".

### `project_subtask_hours`

Total sub-task hours for one project, filtered server-side, in one call.
Sums delivery/allocated/effective hours over the project's sub-tasks
(`project.task` with `parent_id` set) instead of paginating `search_read`
client-side — especially useful for the "exactly one assignee" condition,
which Odoo domains cannot express.

- `project_id`: `project.project` id (required).
- `only_closed_stages` (default `false`): Count only tasks the schema
  considers closed. State is primary: on instances with
  `project.task.state`, "closed" means `state` in the stable closed set
  (done/cancelled); with no `state` field, `is_closed` is used if present;
  only when neither exists does it fall back to matching `stage_id.name`
  against `closed_stage_names`. Cancelled tasks still count toward delivery
  hours (business decision, not a bug).
- `closed_stage_names` (default `["Done", "Cancelled", "Delivered"]`): Stage
  names treated as closed. This is the sole filter on schemas with neither
  `state` nor `is_closed` (the stage-name fallback above). On schemas that DO
  have `state`/`is_closed`, explicitly passing `closed_stage_names` narrows
  the result further: it becomes an additional AND condition on top of the
  stable closed-state filter, so a task must be both state-closed AND have a
  matching stage name — a deliberate narrowing versus the previous
  stage-name-only population. Omit it (or rely on the default) to use only
  the stable state filter on those schemas.
- `single_assignee_only` (default `false`): Count only tasks with exactly
  one user in `user_ids`.
- `group_by_month` (default `false`): Also bucket totals by the local-time
  month of `date_end`; tasks without `date_end` are excluded from the
  buckets and summarised separately under `no_date_end`.
- `periods`: Optional list of `{"date_from": "YYYY-MM-DD", "date_to":
  "YYYY-MM-DD"}` ranges applied to `date_end`, OR-combined (matching
  per-budget-period filtering, not a union). Omitted = no date filter.
- `timezone_offset` (default `7`): UTC offset for dates.

### `project_dashboard`

Everything a project-detail page needs in one call: status, milestones,
finance, weekly logged hours, budgets, budget-line detail, and delivery by
month. Replaces ~12 separate calls. Output is the spec's free-form schema,
**not** the standard report envelope — this tool feeds a dashboard, not a
reader. Sections run sequentially and fail soft: a broken section's error
message lands under `errors` while the rest of the report still returns.
Within `core`, `finance` and `weekly_logged` each fail independently —
a fault in one (e.g. a missing app) drops just that key into `errors`
without discarding `project`/`milestones`, which return whenever the
project itself was found. `core` as a whole only fails if the project id
doesn't exist.

- `project_id`: `project.project` id (required).
- `only_closed_stages` / `closed_stage_names` / `single_assignee_only`:
  sub-task filters, same as `project_subtask_hours`; shape the `hours` and
  `delivery_monthly` sections.
- `budget_ids`: `crossovered.budget` / `budget.analytic` ids to select for
  the `budget_detail` section. **Omit (`null`) to select ALL budgets** of
  the project; **pass `[]` to select NONE** — `budget_detail` then reports
  all-time cost only, unscoped to any budget period. These two states are
  deliberately distinct; do not send `[]` to mean "all". Any id that
  matches no budget of the project is dropped and reported back —
  `budget_detail.unknown_budget_ids` lists it, and a `warnings` entry
  flags it — regardless of which budget section was requested, so a
  stale/typo'd id is never silently indistinguishable from "select none".
- `include`: Subset of `["core", "hours", "budgets", "budget_detail",
  "delivery_monthly"]`; omitted = all. Use it to re-fetch only what
  changed — a checkbox toggle needs `["hours", "delivery_monthly"]`; a
  budget chip change needs `["budget_detail", "delivery_monthly"]`.
  `core` covers project, milestones, finance and weekly_logged.
- `lookahead_days` (default `7`): "due soon" window for derived health.
- `timezone_offset` (default `7`): UTC offset for dates.

### `portfolio_health`

Portfolio overview: one row per project, joined by id server-side.
Replaces the `project_status_report` + `project_profitability` pair the
overview tab used to join by name client-side, which broke on duplicate
project names. Returns raw signals only — the client computes its own
health score from user-configured thresholds. If the portfolio's
milestones exceed the fetch cap, the report still returns (never a hard
error) with a `truncated_milestone_data` risk entry — same pattern as
`project_status_report`.

- `manager`: Optional project-manager filter (`user_id.name` ilike).
- `customer`: Optional customer filter (`partner_id.name` ilike).
- `include_on_hold` (default `true`): Keep on_hold projects.
- `include_done` (default `false`): Keep done projects.
- `lookahead_days` (default `7`): "due soon" window for derived health.
- `timezone_offset` (default `7`): UTC offset for dates.

### `team_workload` · `project_status_report` · `standup_digest`

Project delivery reports — per-assignee workload, portfolio-wide project health, and a daily stand-up digest. Same composition style as the reports above (filters, thresholds, `timezone_offset`); see the docstrings in `odoo_pulse/tools_workflows.py` for the full argument list.

`team_workload`'s `done_stages` and `standup_digest`'s `exclude_stages`
classify a task as closed the same schema-aware way as
`project_subtask_hours`'s `only_closed_stages` above: `project.task.state`
is checked first (the stable closed set), then `is_closed`, and only then
the stage-name list itself. The stage-name parameter remains a compatible
fallback/exclusion filter on every schema — it just stops being the sole
signal once a stabler field exists. Unlike `project_subtask_hours` /
`project_dashboard`'s `closed_stage_names`, these two parameters are not
additionally ANDed onto the state-based filter; they only narrow via the
stage-name path itself.

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

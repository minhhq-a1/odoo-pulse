# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests (no live Odoo needed)
pytest

# Run a single test file
pytest tests/test_client.py

# Run a single test by name
pytest tests/test_tools_write.py::test_create_record_preview

# Live smoke test against a real Odoo instance (reads only, never writes)
python scripts/smoke_live.py

# Playground: boot a real Odoo in Docker, seed a demo story, assert reports
make playground          # boot + seed (follows the seed logs)
make playground-smoke    # end-to-end: boot, seed, assert reports, tear down
make playground-reset    # wipe the playground (drops the database)
```

## Architecture

This is an MCP server that exposes Odoo's XML-RPC external API as MCP tools. The entry point is `odoo_pulse/server.py`, which imports all tool modules as side effects — each import registers `@mcp.tool()` (and, for `resources.py`, `@mcp.resource()`) functions with the shared FastMCP instance.

**Module responsibilities:**

- `runtime.py` — shared singleton: holds the `mcp` (FastMCP) instance, the lazy `OdooClient` (created on first tool call), and shared helpers used by every tool: `safe()` (runs a lambda and serialises result/error to JSON), `name_domain()`, `date_domain()`, `preview()` (dry-run struct).
- `odoo_client.py` — thin XML-RPC wrapper. `OdooConfig.from_env()` reads all env vars. `OdooClient._check_write()` enforces the four-layer write safety guard. All XML-RPC faults become `OdooError`. `fields_get` results are cached via a process-local TTL+LRU cache (`cache.py`); `aggregate_records` dispatches between `read_group` (Odoo ≤18) and `formatted_read_group` (19+) based on `major_version()`. Aggregate rows are normalised so both dispatch paths return spec-keyed aggregates (`amount_total:sum`) plus `__count`; XML-RPC proxies are built per call for thread safety.
- `tools_generic.py` — model-agnostic tools: `search_read`, `search_count`, `read_records`, `get_model_fields`, `list_models`, `odoo_version`, `aggregate_records`, `read_attachment`.
- `tools_write.py` — write tools (`create_record`, `update_records`, `delete_records`) plus domain-specific helpers (`create_lead`, `create_contact`, `create_task`, `confirm_sale_order`). Every tool returns a dry-run preview unless `confirm=True`.
- `resources.py` — the `odoo://{model}/{id}` MCP resource template (the only MCP Resource; everything else is a tool): one live record as JSON with all stored fields, `safe()`-wrapped like every tool; not-found returns the `{"error": ...}` envelope. Loaded as part of the `core` group.
- `workflow_helpers.py` — shared building blocks for composed workflow tools: `today_in_tz`, `parse_when` (UTC-datetime-aware date parsing), `utc_bound` (local-midnight domain boundaries), `ensure_field`, `optional_fields` (schema-filtered field candidates), archived-aware `resolve_user_names`, `build_report` (the standard report envelope: `tool`, `as_of`, tool-specific keys, `summary`, `breakdown`, `highlights`, `risks`), and `gather`/`gather_strict` (thread-per-thunk concurrency for independent RPCs; calls that share a model+method must stay ordered inside one thunk so the FakeClient's per-model response queues remain deterministic). Used by `tools_workflows.py` and `standup_digest`.
- `tools_workflows.py` — composed, opinionated workflow tools that answer a business question in one call (e.g. `sprint_health`, `team_workload`, `project_status_report`, `standup_digest`). Read-only; compose `search_read`/aggregates server-side and return the `build_report` envelope.
- `tools_reports_sales.py` (`pipeline_review`, `sales_snapshot`), `tools_reports_finance.py` (`receivables_health`), `tools_reports_inventory.py` (`inventory_risk`), `tools_reports_hr.py` (`absence_overview`), `tools_reports_pulse.py` (`business_pulse`) — cross-department report tools, one domain per module. Same envelope and composition style as `tools_workflows.py`.
- `tools_reports_ops.py` — operations report tools (`procurement_watch`, `production_health`): purchasing and manufacturing health. Same `build_report` envelope and composition style; loaded as part of the `reports` group alongside `tools_workflows` and the other `tools_reports_*` modules.
- `project_shared.py` — non-tool shared helpers for the project-status family: budget-model abstraction (`_budget_sources`, `_budget_by_project`, moved from `tools_reports_projects`), `derive_project_health` (THE single source of truth for derived health verdicts), `analytic_money` (positive-cost convention), `paged_search_read` (server-side offset pagination), `periods_domain` (OR-of-ranges domains), and the sub-task hour helpers (`fetch_subtasks`/`sum_hours`/`subtasks_by_month`).
- `tools_project_detail.py` — dashboard-backing tools (`project_subtask_hours`, `project_dashboard`, `portfolio_health`) for the "Project Status" artifact. Free-form output schema per the spec (NOT the `build_report` envelope — intentional deviation; these feed a dashboard, not a reader). Sections of `project_dashboard` run sequentially with per-section soft-fail (`errors` key). Loaded in the `reports` group.
- `tool_groups.py` — maps `ODOO_TOOL_GROUPS` (default `core,reports`) to the tool/resource modules `server.py` imports; unknown group names fail at startup.
- `domain_tools.py`, `tools_hr.py`, `tools_projects.py`, `tools_operations.py`, `tools_engagement.py`, `tools_niche.py` — domain-specific read tools wrapping `search_read` with hard-coded fields and domains for common Odoo models.

**Write safety chain** (all four must pass for any write to execute):
1. `ODOO_READ_ONLY=false` — master switch (default: `true`, blocking all writes)
2. `ODOO_WRITABLE_MODELS` — comma-separated allow-list; model must be in it
3. `ODOO_ALLOW_DELETE=true` — required for `delete_records` (default: `false`)
4. `confirm=True` on the tool call — all write tools return a preview struct by default

System models (`ir.*`, `base*`, `res.users`, `res.groups`, etc.) are permanently blocked regardless of `ODOO_WRITABLE_MODELS`.

**Testing pattern:** Tests inject a `FakeClient` directly into `runtime._client` (see `conftest.py`). The fake records every call in `fake_client.calls` and returns canned data from `search_responses`/`read_responses` dicts. No real Odoo or network is needed. Tests assert on the model name and domain that a tool built, not on Odoo's actual response.

**Adding a new tool module:** Create `odoo_pulse/tools_foo.py`, import `mcp` and `get_client` from `.runtime`, decorate functions with `@mcp.tool()`, then add the module to a group in `tool_groups.GROUP_MODULES` (server.py imports modules per enabled group).

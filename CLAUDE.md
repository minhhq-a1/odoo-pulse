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

This is an MCP server that exposes Odoo's XML-RPC external API as MCP tools. The entry point is `src/odoo_pulse/server.py`, which calls `mcp.registry.load_enabled_modules()` to import the tool modules selected by `ODOO_TOOL_GROUPS` as side effects — each import registers `@mcp.tool()` (and, for `mcp.resources`, `@mcp.resource()`) functions with the shared FastMCP instance.

As of this refactor the package is split into layered subpackages (`core`, `mcp`, `common`, `services`) plus the transitional flat tool modules that hold thin decorated adapters. All report business logic is consolidated under `services/` (`report_context.py`, `pulse.py`, `crm/`, `sales/`, `finance/`, `hr/`, `inventory/`, `operations/`, and `projects/`).

**Module responsibilities:**

- `src/odoo_pulse/core/` — config, errors, cache, timeout transports, XML-RPC client, write guards
- `src/odoo_pulse/mcp/` — FastMCP app, lazy client runtime, JSON result boundary, registry, resource adapter
- `src/odoo_pulse/common/` — dates/domains, paging, schema, money, reporting, concurrency; no MCP/global client
- `src/odoo_pulse/services/report_context.py` — immutable context (client, today, timezone_offset, company_id) and company domain helper
- `src/odoo_pulse/services/records.py` — record read service for the MCP resource
- `src/odoo_pulse/services/writes.py` — dry-run preview shaping
- `src/odoo_pulse/services/pulse.py` — cross-department business pulse report orchestrating domain metrics
- `src/odoo_pulse/services/crm/` — CRM metrics (`new_leads`) and pipeline review service
- `src/odoo_pulse/services/sales/` — Sales metrics (`confirmed_sales`) and sales snapshot service
- `src/odoo_pulse/services/finance/` — Finance metrics (`overdue_receivables`) and receivables health service
- `src/odoo_pulse/services/hr/` — HR metrics (`employees_off`) and absence overview service
- `src/odoo_pulse/services/inventory/` — Inventory risk report service
- `src/odoo_pulse/services/operations/` — Procurement watch and production health report services
- `src/odoo_pulse/services/projects/` — Project queries, subtask metrics, health, finance, budget, profitability, dashboard, workload, standup, and overdue metrics
- `src/odoo_pulse/tools_*.py` — explicit decorated adapters; their physical reorganization into tool subpackages remains Plan 5

**Write safety chain** (all four must pass for any write to execute):
1. `ODOO_READ_ONLY=false` — master switch (default: `true`, blocking all writes)
2. `ODOO_WRITABLE_MODELS` — comma-separated allow-list; model must be in it
3. `ODOO_ALLOW_DELETE=true` — required for `delete_records` (default: `false`)
4. `confirm=True` on the tool call — all write tools return a preview struct by default

System models (`ir.*`, `base*`, `res.users`, `res.groups`, etc.) are permanently blocked regardless of `ODOO_WRITABLE_MODELS`.

**Testing pattern:** Tests inject a `FakeClient` directly into `odoo_pulse.mcp.runtime._client` (see `conftest.py`). The fake records every call in `fake_client.calls` and returns canned data from `search_responses`/`read_responses` dicts. No real Odoo or network is needed. Tests assert on the model name and domain that a tool built, not on Odoo's actual response.

**Adding a new tool module:** Create `src/odoo_pulse/tools_foo.py`, import `mcp` from `.mcp.app` and `get_client` from `.mcp.runtime`, decorate functions with `@mcp.tool()`, then add the module to a group in `src/odoo_pulse/mcp/registry.py`'s `GROUP_MODULES` (server.py imports modules per enabled group).

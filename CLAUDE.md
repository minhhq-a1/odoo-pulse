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
```

## Architecture

This is an MCP server that exposes Odoo's XML-RPC external API as MCP tools. The entry point is `odoo_mcp/server.py`, which imports all tool modules as side effects — each import registers `@mcp.tool()` functions with the shared FastMCP instance.

**Module responsibilities:**

- `runtime.py` — shared singleton: holds the `mcp` (FastMCP) instance, the lazy `OdooClient` (created on first tool call), and shared helpers used by every tool: `safe()` (runs a lambda and serialises result/error to JSON), `name_domain()`, `date_domain()`, `preview()` (dry-run struct).
- `odoo_client.py` — thin XML-RPC wrapper. `OdooConfig.from_env()` reads all env vars. `OdooClient._check_write()` enforces the four-layer write safety guard. All XML-RPC faults become `OdooError`.
- `tools_generic.py` — model-agnostic tools: `search_read`, `search_count`, `read_records`, `get_model_fields`, `list_models`, `odoo_version`.
- `tools_write.py` — write tools (`create_record`, `update_records`, `delete_records`) plus domain-specific helpers (`create_lead`, `create_contact`, `create_task`, `confirm_sale_order`). Every tool returns a dry-run preview unless `confirm=True`.
- `domain_tools.py`, `tools_hr.py`, `tools_projects.py`, `tools_operations.py`, `tools_engagement.py`, `tools_niche.py` — domain-specific read tools wrapping `search_read` with hard-coded fields and domains for common Odoo models.

**Write safety chain** (all four must pass for any write to execute):
1. `ODOO_READ_ONLY=false` — master switch (default: `true`, blocking all writes)
2. `ODOO_WRITABLE_MODELS` — comma-separated allow-list; model must be in it
3. `ODOO_ALLOW_DELETE=true` — required for `delete_records` (default: `false`)
4. `confirm=True` on the tool call — all write tools return a preview struct by default

System models (`ir.*`, `base*`, `res.users`, `res.groups`, etc.) are permanently blocked regardless of `ODOO_WRITABLE_MODELS`.

**Testing pattern:** Tests inject a `FakeClient` directly into `runtime._client` (see `conftest.py`). The fake records every call in `fake_client.calls` and returns canned data from `search_responses`/`read_responses` dicts. No real Odoo or network is needed. Tests assert on the model name and domain that a tool built, not on Odoo's actual response.

**Adding a new tool module:** Create `odoo_mcp/tools_foo.py`, import `mcp` and `get_client` from `.runtime`, decorate functions with `@mcp.tool()`, then add `from . import tools_foo  # noqa: F401` in `server.py`.

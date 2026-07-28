# Contributing to odoo-pulse

Thanks for helping make Odoo more conversational. Issues and PRs welcome.

## Dev setup

```bash
git clone https://github.com/minhhq-a1/odoo-pulse
cd odoo-pulse
pip install -e ".[dev]"
pytest   # no Odoo or network needed
```

## How the tests work

Tests inject a `FakeClient` into `odoo_pulse.mcp.runtime._client` (see `tests/conftest.py`).
The fake records every XML-RPC call in `fake_client.calls` and serves canned
rows from `search_responses` / `read_responses`. Assert on the **model and
domain a tool built**, not on Odoo's response. No live Odoo is ever required;
`scripts/smoke/live.py` exists for optional read-only checks against a real
instance.

## Adding a tool

1. Pick the right module (see the module map in `AGENTS.md`), or create
   `src/odoo_pulse/tools/subpackage/foo.py` importing `mcp` from `...mcp.app` and
   `get_client` from `...mcp.runtime`.
2. Decorate with `@mcp.tool()`; wrap the body in `safe(lambda: ...)`.
3. Report-style tools return the `build_report` envelope
   (`src/odoo_pulse/common/reporting.py`) — numbers + `highlights` + `risks` + a verdict.
4. New modules must be added to a group in `src/odoo_pulse/mcp/registry.py`'s
   `GROUP_MODULES`.
5. Write the FakeClient test first (TDD is the house style).

## Ground rules

- Read tools must stay read-only; anything that writes goes through the
  four-layer guard in `core.client.OdooClient._check_write` and returns a
  dry-run preview unless `confirm=True`.
- Odoo-version differences are handled by schema checks
  (`optional_fields` / `ensure_field`), never by guessing.
- Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`).

## Releasing (maintainers)

Follow [docs/guides/releasing.md](docs/guides/releasing.md). It is the canonical
procedure — this section is only a pointer.

Two rules before you start. Any change to the release machinery itself
(workflows, `scripts/release/`, their tests) must be merged and green on `main`
*before* a release candidate is tagged; the version bump is a separate step. And
every tag push or remote publish command needs explicit authorization
immediately beforehand.

The order is always: release candidate → at least a 48-hour soak → stable
release → MCP Registry.

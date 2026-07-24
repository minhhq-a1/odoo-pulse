# Architecture Overview

## Runtime Flow

`server.py` loads `.env`, asks `mcp.registry` for enabled module paths, imports
explicit adapters for registration side effects, and starts the shared FastMCP
application. Client construction stays lazy until a tool/resource is called.

## Layers

- `core/`: configuration, errors, cache, transport, XML-RPC client, write guards.
- `common/`: dates/domains, paging, schema, money, reporting, concurrency.
- `services/`: Python-valued business and record/write behavior with explicit clients.
- `mcp/`: application, runtime, registry, resource, JSON/text boundaries.
- `tools/`: explicit public MCP signatures and descriptions.

Dependency direction: `server -> registry -> tools -> services -> common/core`.
Services never import MCP/tools; tools never import other tool modules.

## Tool Hierarchy

Generic and write adapters live directly under `tools/`; breadth wrappers live
under `tools/lists/`; composed reports and workflows live under `tools/reports/`.
`mcp.registry.GROUP_MODULES` is the canonical group/module map.

## Write Safety

Services shape previews and invoke public client methods. `core.client` alone
enforces read-only mode, writable-model allow-list, permanent system-model
blocks, and delete opt-in; every public write also defaults `confirm=False`.

## Testing

`tests/support/FakeClient` records deterministic calls. Unit tests mirror source
layers; contract tests freeze 88 tools/31 defaults/one resource and architecture;
integration tests install and probe clean wheels, including MCP 1.3.0.

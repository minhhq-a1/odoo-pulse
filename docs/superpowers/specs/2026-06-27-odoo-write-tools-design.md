# Design: Controlled write tools for the Odoo MCP server

Date: 2026-06-27
Status: Approved (pending spec review)

## Goal

Extend the read-only Odoo MCP server with the ability to **create, update and
delete** records, while keeping the server safe by default. Writes must be
impossible to trigger by accident: they require an explicit master switch, an
explicit per-model opt-in, an explicit confirmation on each call, and a separate
gate for deletes.

## Non-goals

- No bulk migration / import tooling.
- No workflow engine; the only "action" methods exposed are the ones already in
  `WRITE_METHODS` (`action_confirm`, `action_post`).
- No write access to system models (see hard deny-list) under any configuration.

## Safety model

Four independent controls, all defaulting to the safe value so the server ships
read-only:

| Env var | Default | Role |
|---|---|---|
| `ODOO_READ_ONLY` | `true` | Master switch. While `true`, every write method is blocked (current behaviour, unchanged). |
| `ODOO_WRITABLE_MODELS` | *(empty)* | Comma-separated allow-list. A model can be written only if it appears here. Empty means nothing is writable even when `ODOO_READ_ONLY=false`. |
| `ODOO_ALLOW_DELETE` | `false` | Separate gate for `unlink`. `create`/`write` may be enabled while deletes stay blocked. |
| confirm (per-call param) | `false` | Each write tool requires `confirm=true`. Without it the tool returns a dry-run preview and performs no write. |

**Hard deny-list (non-overridable).** Even if listed in `ODOO_WRITABLE_MODELS`,
these are always blocked:

- Exact models: `res.users`, `res.groups`, `res.company`, `ir.config_parameter`,
  `ir.model`, `ir.model.fields`, `ir.rule`, `ir.cron`, `ir.actions.server`.
- Prefix: any model starting with `ir.` or `base`.

The deny-list is a constant in code, not configurable, so a misconfigured env
cannot expose system tables.

## Enforcement point

All writes funnel through `OdooClient.execute_kw`, so the guard lives there and
no tool can bypass it. Order of checks for a write method:

1. If `read_only` -> raise `OdooError` ("read-only mode").
2. If model matches the hard deny-list -> raise `OdooError` ("system model").
3. If model not in `writable_models` -> raise `OdooError` ("not in allow-list").
4. If method is `unlink` and not `allow_delete` -> raise `OdooError` ("deletes disabled").

`OdooError` is caught by `runtime.safe()` and returned as
`{"error": "..."}`, so violations are reported to the model, never crash the
server.

### Config changes (`OdooConfig`)

Add three fields, all parsed in `from_env()`:

- `writable_models: frozenset[str]` — split `ODOO_WRITABLE_MODELS` on commas,
  strip, drop empties.
- `allow_delete: bool` — same truthy parsing as `read_only`.
- (`read_only` already exists.)

### Client helpers (`OdooClient`)

Thin wrappers over `execute_kw` (which enforces the guard):

- `create(model, values: dict) -> int`
- `write(model, ids: list[int], values: dict) -> bool`
- `unlink(model, ids: list[int]) -> bool`

## Confirmation (dry-run) mechanism

A helper in `runtime.py`:

```python
def preview(action: str, model: str, *, values=None, ids=None, affected=None) -> str:
    """JSON describing a write that WOULD happen, with confirm_required=True."""
```

Each write tool:

```python
def create_record(model, values, confirm=False):
    if not confirm:
        return preview("create", model, values=values)
    return safe(lambda: {"created_id": get_client().create(model, values)})
```

- For `create`, the preview echoes the values (no DB call).
- For `update`/`delete`, the preview first reads the `display_name` of the target
  ids (a read, always allowed) so the user sees which records are affected, then
  reports the count and — for update — the new values.

The preview path must never reach a write method. Tests assert the FakeClient
records zero write calls when `confirm=false`.

## Tools (`odoo_mcp/tools_write.py`)

A new module, imported for side-effect registration in `server.py` like the
other tool modules.

### Generic

- `create_record(model: str, values: dict, confirm: bool = False)`
- `update_records(model: str, ids: list[int], values: dict, confirm: bool = False)`
- `delete_records(model: str, ids: list[int], confirm: bool = False)`

### Domain helpers (MVP)

Convenience wrappers that build the values dict for common cases. Each still
requires its target model in the allow-list (same guard).

- `create_lead(name, contact_name=None, email=None, phone=None, description=None, confirm=False)` -> `crm.lead`
- `create_contact(name, email=None, phone=None, is_company=False, parent_id=None, confirm=False)` -> `res.partner`
- `create_task(name, project_id, user_id=None, description=None, date_deadline=None, confirm=False)` -> `project.task`
- `confirm_sale_order(order_id, confirm=False)` -> `sale.order` `action_confirm`

`create_task` takes `project_id` (int) directly to avoid ambiguous name
resolution; the existing read tool `list_projects` lets the caller find the id
first.

## Error handling

- Guard violations -> `OdooError` -> `{"error": ...}` via `safe()`.
- Odoo XML-RPC faults (e.g. required field missing) -> already wrapped as
  `OdooError` in `execute_kw` -> `{"error": ...}`.
- Invalid/empty `ids` for update/delete -> tool returns `{"error": ...}` without
  calling the server.

## Testing

New tests, reusing the existing `FakeClient` / `FakeProxy` harness:

1. **Guard matrix** (`test_client.py` or new `test_write_guard.py`):
   - `read_only=true` blocks create/write/unlink.
   - model not in allow-list blocks even when `read_only=false`.
   - hard deny-list (`res.users`, `ir.model`, `ir.*`, `base`) blocks even if
     listed in `writable_models`.
   - `unlink` blocked when `allow_delete=false`, allowed when `true`.
   - allowed model + create/write succeeds and forwards correct args to
     `execute_kw`.
2. **Confirm gate** (`test_tools_write.py`):
   - `confirm=false` returns a preview dict and produces **zero** write calls on
     the FakeClient.
   - `confirm=true` performs exactly one write call with the expected
     model/method/args.
   - domain helpers build the expected values dict.
3. **Regression:** the existing 96 tests stay green because all new controls
   default to the safe value.

## Docs

- `README.md`: new "Write operations" section — the four controls, the hard
  deny-list, a worked example (enable `crm.lead`, create a lead with
  `confirm=false` then `confirm=true`), and a safety note.
- `.env.example`: add `ODOO_WRITABLE_MODELS=` and `ODOO_ALLOW_DELETE=false` with
  comments.

## Rollout / safety defaults

Shipping this change does **not** enable any write: `ODOO_READ_ONLY=true`,
`ODOO_WRITABLE_MODELS` empty, `ODOO_ALLOW_DELETE=false`. A user must consciously
flip all the relevant switches. The PR is verifiable against a live Odoo via the
existing `scripts/smoke_live.py` (which only exercises read tools and is
unaffected).

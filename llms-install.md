# odoo-pulse — installation guide for AI assistants

This file helps an AI coding assistant install and configure the `odoo-pulse`
MCP server for a user. Follow these steps.

## What this server does

`odoo-pulse` gives an MCP client read-only (by default) access to an Odoo ERP
over its XML-RPC external API, plus one-call "business analyst" report tools
(`business_pulse`, `pipeline_review`, `receivables_health`, `inventory_risk`,
`sales_snapshot`, `absence_overview`).

## Step 1 — collect connection details

Ask the user for these, and set them as environment variables on the server:

- `ODOO_URL` — e.g. `https://acme.odoo.com` (required)
- `ODOO_DB` — database name (required)
- `ODOO_USERNAME` — login/email (required)
- `ODOO_API_KEY` — an Odoo API key: Settings → Users → (user) → Account
  Security → New API Key (required)
- `ODOO_READ_ONLY` — keep `true` (default) unless the user explicitly wants
  writes; writes also require further opt-in (see the repo README).
- `ODOO_TOOL_GROUPS` — optional; default `core,reports` exposes the generic
  query tools plus the report tools. Only set this if the user wants the ~60
  domain-specific tools: add groups (`hr`, `projects`, `operations`,
  `engagement`, `niche`) or set `all` for everything.

If the user has no Odoo instance, they can run the bundled demo:
`docker compose -f docker-compose.playground.yml up -d` (database `playground`,
login `admin`/`admin` at `http://localhost:8069`).

## Step 2 — add the server to the MCP client config

Use `uvx odoo-pulse` as the launch command (no install step needed). Example
config block:

```json
{
  "mcpServers": {
    "odoo-pulse": {
      "command": "uvx",
      "args": ["odoo-pulse"],
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

If `uvx` is unavailable, use `pip install odoo-pulse` and set `command` to
`odoo-pulse`.

## Step 3 — verify

Have the client call the `odoo_version` tool. A successful response with the
server version confirms the connection. Then try `business_pulse` for a one-call
company briefing.

## Notes

- The server is read-only by default; it will not modify Odoo data unless the
  user enables writes via `ODOO_READ_ONLY=false` plus `ODOO_WRITABLE_MODELS`
  (a comma-separated model allow-list), and additionally
  `ODOO_ALLOW_DELETE=true` for deletes. Even then, every write tool returns a
  dry-run preview unless called with `confirm=true`.
- Full tool catalogue and configuration: see `README.md` and `docs/tools.md`.

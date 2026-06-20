# odoo-mcp

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

| Tool | Purpose |
| --- | --- |
| `odoo_version` | Connectivity / version check |
| `list_models` | Discover available models (optionally filtered) |
| `get_model_fields` | Inspect a model's schema (`fields_get`) |
| `search_read` | Query records with an Odoo domain filter |
| `search_count` | Count records matching a domain |
| `read_records` | Fetch specific records by id |

Write operations (`create`/`write`/`unlink`) are **not** exposed in this
read-only MVP, and the underlying client blocks them while
`ODOO_READ_ONLY=true`.

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

## Running

```bash
# stdio transport (for MCP clients)
odoo-mcp
```

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

## Roadmap

- [ ] Write tools (`create` / `write` / `unlink`) behind a confirmation flow
- [ ] Domain-specific convenience tools (CRM, Sales, Inventory, Accounting)
- [ ] Model allow/deny lists for finer access control
- [ ] Optional JSON-RPC transport

# Installing odoo-pulse

`odoo-pulse` is an MCP server. You point an MCP client (Claude Desktop, Claude
Code, Cursor, …) at it and give it your Odoo connection details as environment
variables.

## What you need

| Variable | Required | Example | Notes |
| --- | --- | --- | --- |
| `ODOO_URL` | yes | `https://acme.odoo.com` | Base URL of your Odoo |
| `ODOO_DB` | yes | `acme` | Database name |
| `ODOO_USERNAME` | yes | `you@example.com` | Login |
| `ODOO_API_KEY` | yes | `1a2b3c…` | Settings → Users → Account Security → New API Key |
| `ODOO_READ_ONLY` | no | `true` | `true` (default) blocks all writes |

No Odoo account? See the [5-minute playground](playground.md) — it boots a demo
Odoo for you.

## Claude Code

```bash
claude mcp add odoo-pulse \
  --env ODOO_URL=https://acme.odoo.com \
  --env ODOO_DB=acme \
  --env ODOO_USERNAME=you@example.com \
  --env ODOO_API_KEY=your-api-key \
  --env ODOO_READ_ONLY=true \
  -- uvx odoo-pulse
```

### Claude Code (plugin)

```
/plugin marketplace add minhhq-a1/odoo-pulse
/plugin install odoo-pulse@odoo-pulse
```

The plugin launches `uvx odoo-pulse` and reads `ODOO_URL`, `ODOO_DB`,
`ODOO_USERNAME`, `ODOO_API_KEY`, `ODOO_READ_ONLY` from your environment.

## Claude Desktop

Edit `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

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

## Cursor

Edit `.cursor/mcp.json` in your project (or the global `~/.cursor/mcp.json`) —
same shape as Claude Desktop:

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

## Alternatives to `uvx`

- **pip:** `pip install odoo-pulse`, then use `odoo-pulse` as the `command`.
- **Docker (no host install):** use
  `docker run -i --rm ghcr.io/minhhq-a1/odoo-pulse` as the command, passing the
  same env vars with `-e`.

## Enabling more tools

By default the server exposes the report tools plus generic query tools
(`ODOO_TOOL_GROUPS=core,reports`). Add groups — `hr`, `projects`, `operations`,
`engagement`, `niche`, or `all` — to expose the ~60 domain tools. See
[tools.md](tools.md) for the full catalogue and
[Write operations](tools.md#write-operations) to enable writes.

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
| `ODOO_WRITABLE_MODELS` | no | *(empty)* | Comma-separated allow-list of models writable when `ODOO_READ_ONLY=false` |
| `ODOO_ALLOW_DELETE` | no | `false` | Additionally required (`true`) for `delete_records` |

Writes are off by default. Even with all three write variables set, every write
tool returns a dry-run preview unless called with `confirm=true` — details in
[Write operations](tools.md#write-operations).

### If an API key may have been exposed

1. Revoke or rotate the key in Odoo.
2. Put the replacement only in your ignored local MCP configuration.
3. Use the secure `ODOO_VERIFY_SSL=true` default. For a self-signed
   certificate, install its trusted private CA on the MCP host (or expose its
   CA bundle through the host's Python trust configuration) instead of
   disabling verification. Keep verification disabled only as an explicitly
   documented, network-restricted exception after accepting the interception
   risk.
4. Verify the new key over TLS, then confirm the old key no longer authenticates.
5. Before release, scan tracked and reachable history with redacted output:

   ```bash
   gitleaks git --redact --log-opts="--all" .
   ```

6. Extract unreachable Git blobs to a dedicated temporary directory, scan
   them without printing their contents, then remove only that directory:

   ```bash
   audit_blob_dir="$(mktemp -d)"
   git fsck --full --no-reflogs --unreachable |
     awk '$1 == "unreachable" && $2 == "blob" {print $3}' |
     while read -r object_id; do
       git cat-file blob "$object_id" >"$audit_blob_dir/$object_id"
     done
   gitleaks dir --redact "$audit_blob_dir"
   find "$audit_blob_dir" -type f -delete
   rmdir "$audit_blob_dir"
   ```

Both Gitleaks commands must exit `0` with no findings. Install Gitleaks as a
release-workstation tool if necessary; do not add it to Python dependencies or
skip the gate. Never paste a key into a command line or log.

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

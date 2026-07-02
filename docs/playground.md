# Try odoo-pulse in 5 minutes (no Odoo account needed)

This spins up a throwaway Odoo 18 pre-loaded with a demo "story" — a stalled
deal, a 90-day-overdue invoice, a stock shortage, someone off today, an overdue
task — so the report tools have something real to say.

## 1. Boot the playground

```bash
docker compose -f docker-compose.playground.yml up -d
```

First boot installs Odoo apps and demo data, then seeds the story — allow a few
minutes. Follow along with:

```bash
docker compose -f docker-compose.playground.yml logs -f seed
```

When you see `[seed] done`, Odoo is ready at http://localhost:8069
(login `admin` / `admin`, database `playground`).

## 2. Connect Claude

**Primary — `uvx` (nothing to install globally):**

```bash
claude mcp add odoo-pulse \
  --env ODOO_URL=http://localhost:8069 \
  --env ODOO_DB=playground \
  --env ODOO_USERNAME=admin \
  --env ODOO_API_KEY=admin \
  --env ODOO_READ_ONLY=true \
  -- uvx odoo-pulse
```

**No-install fallback — Docker image:**

```bash
claude mcp add odoo-pulse \
  --env ODOO_URL=http://host.docker.internal:8069 \
  --env ODOO_DB=playground \
  --env ODOO_USERNAME=admin \
  --env ODOO_API_KEY=admin \
  --env ODOO_READ_ONLY=true \
  -- docker run -i --rm --add-host=host.docker.internal:host-gateway \
  ghcr.io/minhhq-a1/odoo-pulse
```

(`uvx odoo-pulse` needs the PyPI release; the Docker recipe needs the GHCR image.
If neither is published yet, install locally with `pip install -e .` and use
`-- odoo-pulse` as the command.)

## 3. Ask Claude

> **Run `business_pulse`.**

You should get a one-call company briefing with an `attention` verdict:
yesterday's orders, overdue invoices, overdue tasks, and who's off today. Then
try `pipeline_review`, `receivables_health`, or `inventory_risk`.

## Reset / tear down

```bash
docker compose -f docker-compose.playground.yml down -v
```

`-v` drops the database so the next `up` re-seeds from scratch.

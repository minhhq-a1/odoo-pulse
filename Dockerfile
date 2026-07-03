# MCP server image for odoo-pulse.
# Backs the `docker run -i ghcr.io/minhhq-a1/odoo-pulse` install recipe and lets
# registries (e.g. Glama) build and introspect the server.
FROM python:3.12-slim

WORKDIR /app

# Install the package from source so the image always matches this repo.
COPY pyproject.toml README.md LICENSE ./
COPY odoo_pulse ./odoo_pulse
RUN pip install --no-cache-dir .

# The server speaks MCP over stdio; connection details come from ODOO_* env vars.
ENV ODOO_READ_ONLY=true
ENTRYPOINT ["odoo-pulse"]

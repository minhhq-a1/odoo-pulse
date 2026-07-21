"""The shared FastMCP application instance.

Kept in its own module so every tool module can import ``mcp`` without
creating an import cycle through ``server``.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "odoo-pulse",
    instructions=(
        "Live business data from the user's own Odoo instance: records, "
        "reports, KPIs — read via tools (search_read, one-call reports) or "
        "the odoo://{model}/{id} resource. NOT for Odoo source-code or "
        "module-structure questions; use a code-index server for those."
    ),
)

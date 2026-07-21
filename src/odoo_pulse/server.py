"""MCP server: an AI business analyst for Odoo over XML-RPC.

Tool modules are grouped (see mcp.registry.GROUP_MODULES) and selected via
the ODOO_TOOL_GROUPS env var. The default surface is "core,reports":
generic model-agnostic tools, gated write tools, and the composed report
tools that answer a business question in one call. The breadth wrappers
(business/hr/projects/operations/engagement/niche) are opt-in.

Write tools stay gated by ODOO_READ_ONLY / ODOO_WRITABLE_MODELS /
ODOO_ALLOW_DELETE / per-call confirm regardless of tool groups.
"""

from __future__ import annotations

from dotenv import load_dotenv

# .env must be loaded before tool-group selection and tool registration,
# both of which happen at import time right below.
load_dotenv()

from .mcp.app import mcp  # noqa: E402
from .mcp.registry import load_enabled_modules  # noqa: E402

load_enabled_modules()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

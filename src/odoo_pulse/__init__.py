"""odoo-pulse: an MCP server for read-only access to Odoo via XML-RPC."""

from __future__ import annotations

from . import common, core, mcp as mcp_pkg, services, tools
from .core.errors import OdooConfigError, OdooError
from .mcp.app import mcp
from .mcp.runtime import get_client

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "common",
    "core",
    "get_client",
    "mcp",
    "mcp_pkg",
    "services",
    "tools",
    "OdooConfigError",
    "OdooError",
]

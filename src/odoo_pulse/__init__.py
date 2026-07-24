"""odoo-pulse: an MCP server for read-only access to Odoo via XML-RPC."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from . import common, core, mcp, services, tools
from .core.errors import OdooConfigError, OdooError
from .mcp.runtime import get_client

try:
    __version__ = version("odoo-pulse")
except PackageNotFoundError:
    __version__ = "1.8.2"

__all__ = [
    "__version__",
    "common",
    "core",
    "get_client",
    "mcp",
    "services",
    "tools",
    "OdooConfigError",
    "OdooError",
]

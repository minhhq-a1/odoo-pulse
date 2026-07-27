"""odoo-pulse: an MCP server for read-only access to Odoo via XML-RPC."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("odoo-pulse")
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = ["__version__"]

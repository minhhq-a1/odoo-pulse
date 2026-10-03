"""odoo-pulse: an MCP server for read-only access to Odoo via XML-RPC."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("odoo-pulse")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0+unknown"

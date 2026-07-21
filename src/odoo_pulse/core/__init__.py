"""Odoo configuration, transport, cache, errors, and XML-RPC client."""

from .client import OdooClient
from .config import OdooConfig
from .errors import OdooConfigError, OdooError

__all__ = ["OdooClient", "OdooConfig", "OdooConfigError", "OdooError"]

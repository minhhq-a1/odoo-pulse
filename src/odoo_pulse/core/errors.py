"""Odoo-specific configuration and RPC errors."""


class OdooConfigError(RuntimeError):
    """Raised when required connection settings are missing or invalid."""


class OdooError(RuntimeError):
    """Raised when Odoo returns a fault or authentication fails."""

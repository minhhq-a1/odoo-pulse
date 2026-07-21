"""Lazy singleton provisioning for the shared ``OdooClient``.

Kept separate from ``app.py`` so tests can monkeypatch the client
construction without touching the FastMCP instance.
"""

from __future__ import annotations

import threading

from ..core.client import OdooClient
from ..core.config import OdooConfig

_client: OdooClient | None = None
_client_lock = threading.Lock()


def get_client() -> OdooClient:
    """Lazily build the Odoo client so the server can start without creds
    being validated until the first tool call. Safe under concurrent calls."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = OdooClient(OdooConfig.from_env())
    return _client

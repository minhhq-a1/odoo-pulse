"""Timeout-aware XML-RPC transports."""

from __future__ import annotations

import xmlrpc.client


class _TimeoutTransport(xmlrpc.client.Transport):
    """Plain-HTTP transport that enforces a socket timeout.

    ``xmlrpc.client.ServerProxy`` has no built-in timeout, so a hung/unreachable
    Odoo would otherwise block a tool call forever. Overriding
    ``make_connection`` lets us set ``timeout`` on the underlying
    ``http.client.HTTPConnection`` before it's used.
    """

    def __init__(self, timeout: float, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    """HTTPS variant of :class:`_TimeoutTransport`; still honours ``context=``
    so ``ODOO_VERIFY_SSL=false`` (self-signed certs) keeps working."""

    def __init__(self, timeout: float, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn

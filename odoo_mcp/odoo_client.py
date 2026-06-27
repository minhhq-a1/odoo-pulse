"""Thin XML-RPC client for Odoo's external API.

Wraps the two standard endpoints exposed by every Odoo instance:
  - /xmlrpc/2/common  -> authentication / version info
  - /xmlrpc/2/object  -> execute_kw for model access (ORM over the wire)

The client is intentionally read-only friendly: it exposes generic helpers
(search_read, read, search_count, fields_get) and a guarded execute_kw that
blocks write methods unless explicitly allowed. This keeps the MCP surface
safe by default.
"""

from __future__ import annotations

import os
import ssl
import xmlrpc.client
from dataclasses import dataclass
from functools import cached_property
from typing import Any

# Methods that mutate data. Blocked while the server runs in read-only mode.
WRITE_METHODS = frozenset(
    {"create", "write", "unlink", "copy", "action_confirm", "action_post"}
)

# Models that must never be writable, regardless of ODOO_WRITABLE_MODELS.
BLOCKED_MODELS = frozenset(
    {
        "res.users",
        "res.groups",
        "res.company",
        "ir.config_parameter",
        "ir.model",
        "ir.model.fields",
        "ir.rule",
        "ir.cron",
        "ir.actions.server",
    }
)
BLOCKED_PREFIXES = ("ir.", "base")


class OdooConfigError(RuntimeError):
    """Raised when required connection settings are missing."""


class OdooError(RuntimeError):
    """Raised when Odoo returns a fault or authentication fails."""


@dataclass(frozen=True)
class OdooConfig:
    url: str
    db: str
    username: str
    api_key: str
    read_only: bool = True
    max_records: int = 200
    verify_ssl: bool = True
    writable_models: frozenset[str] = frozenset()
    allow_delete: bool = False

    @classmethod
    def from_env(cls) -> "OdooConfig":
        url = os.environ.get("ODOO_URL", "").strip().rstrip("/")
        db = os.environ.get("ODOO_DB", "").strip()
        username = os.environ.get("ODOO_USERNAME", "").strip()
        api_key = os.environ.get("ODOO_API_KEY", "").strip()

        missing = [
            name
            for name, value in (
                ("ODOO_URL", url),
                ("ODOO_DB", db),
                ("ODOO_USERNAME", username),
                ("ODOO_API_KEY", api_key),
            )
            if not value
        ]
        if missing:
            raise OdooConfigError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        read_only = os.environ.get("ODOO_READ_ONLY", "true").lower() not in (
            "false",
            "0",
            "no",
        )
        try:
            max_records = int(os.environ.get("ODOO_MAX_RECORDS", "200"))
        except ValueError:
            max_records = 200

        verify_ssl = os.environ.get("ODOO_VERIFY_SSL", "true").lower() not in (
            "false",
            "0",
            "no",
        )
        writable_models = frozenset(
            m.strip()
            for m in os.environ.get("ODOO_WRITABLE_MODELS", "").split(",")
            if m.strip()
        )
        allow_delete = os.environ.get("ODOO_ALLOW_DELETE", "false").lower() not in (
            "false",
            "0",
            "no",
            "",
        )

        return cls(
            url=url,
            db=db,
            username=username,
            api_key=api_key,
            read_only=read_only,
            max_records=max_records,
            verify_ssl=verify_ssl,
            writable_models=writable_models,
            allow_delete=allow_delete,
        )


class OdooClient:
    def __init__(self, config: OdooConfig):
        self.config = config

    @cached_property
    def _ssl_context(self) -> ssl.SSLContext | None:
        # Only relevant for https endpoints. When verification is disabled we
        # build an unverified context so self-signed certs are accepted.
        if self.config.verify_ssl:
            return None
        return ssl._create_unverified_context()

    @cached_property
    def _common(self) -> xmlrpc.client.ServerProxy:
        return xmlrpc.client.ServerProxy(
            f"{self.config.url}/xmlrpc/2/common",
            allow_none=True,
            context=self._ssl_context,
        )

    @cached_property
    def _models(self) -> xmlrpc.client.ServerProxy:
        return xmlrpc.client.ServerProxy(
            f"{self.config.url}/xmlrpc/2/object",
            allow_none=True,
            context=self._ssl_context,
        )

    @cached_property
    def uid(self) -> int:
        try:
            uid = self._common.authenticate(
                self.config.db, self.config.username, self.config.api_key, {}
            )
        except xmlrpc.client.Fault as exc:  # pragma: no cover - network dependent
            raise OdooError(f"Authentication failed: {exc.faultString}") from exc
        if not uid:
            raise OdooError(
                "Authentication failed: invalid credentials or database name."
            )
        return uid

    def version(self) -> dict[str, Any]:
        return self._common.version()

    def _check_write(self, model: str, method: str) -> None:
        if self.config.read_only:
            raise OdooError(
                f"Method '{method}' is blocked: server is running in read-only mode. "
                "Set ODOO_READ_ONLY=false to enable write operations."
            )
        if model in BLOCKED_MODELS or model.startswith(BLOCKED_PREFIXES):
            raise OdooError(
                f"Model '{model}' is a protected system model and can never be written."
            )
        if model not in self.config.writable_models:
            raise OdooError(
                f"Model '{model}' is not in ODOO_WRITABLE_MODELS; writes are not permitted."
            )
        if method == "unlink" and not self.config.allow_delete:
            raise OdooError(
                "Deletes are disabled. Set ODOO_ALLOW_DELETE=true to enable unlink."
            )

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list | None = None,
        kwargs: dict | None = None,
    ) -> Any:
        if method in WRITE_METHODS:
            self._check_write(model, method)
        try:
            return self._models.execute_kw(
                self.config.db,
                self.uid,
                self.config.api_key,
                model,
                method,
                args or [],
                kwargs or {},
            )
        except xmlrpc.client.Fault as exc:
            raise OdooError(exc.faultString) from exc

    # --- Convenience read helpers -------------------------------------------------

    def _cap_limit(self, limit: int | None) -> int:
        if limit is None or limit <= 0 or limit > self.config.max_records:
            return self.config.max_records
        return limit

    def search_read(
        self,
        model: str,
        domain: list | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {
            "fields": fields or [],
            "limit": self._cap_limit(limit),
            "offset": offset,
        }
        if order:
            kwargs["order"] = order
        return self.execute_kw(model, "search_read", [domain or []], kwargs)

    def search_count(self, model: str, domain: list | None = None) -> int:
        return self.execute_kw(model, "search_count", [domain or []])

    def read(
        self, model: str, ids: list[int], fields: list[str] | None = None
    ) -> list[dict]:
        return self.execute_kw(model, "read", [ids], {"fields": fields or []})

    def fields_get(self, model: str, attributes: list[str] | None = None) -> dict:
        return self.execute_kw(
            model,
            "fields_get",
            [],
            {"attributes": attributes or ["string", "type", "help", "required", "relation"]},
        )

    def list_models(self, name_filter: str | None = None) -> list[dict]:
        domain = []
        if name_filter:
            domain = [
                "|",
                ("model", "ilike", name_filter),
                ("name", "ilike", name_filter),
            ]
        return self.search_read(
            "ir.model",
            domain=domain,
            fields=["model", "name"],
            order="model",
        )

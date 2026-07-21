from __future__ import annotations

import os
from dataclasses import dataclass
from math import isfinite

from .errors import OdooConfigError


def _int_env(
    name: str, default: int, *, minimum: int | None = None
) -> int:
    """Parse an integer env var and enforce an optional inclusive minimum."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise OdooConfigError(f"{name} must be an integer, got {raw!r}")
    if minimum is not None and value < minimum:
        raise OdooConfigError(f"{name} must be >= {minimum}, got {value!r}")
    return value


def _float_env(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    strict: bool = False,
) -> float:
    """Parse a float env var and enforce an optional lower bound."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise OdooConfigError(f"{name} must be a number, got {raw!r}")
    if not isfinite(value):
        raise OdooConfigError(f"{name} must be a finite number, got {raw!r}")
    invalid = minimum is not None and (
        value <= minimum if strict else value < minimum
    )
    if invalid:
        operator = ">" if strict else ">="
        raise OdooConfigError(
            f"{name} must be {operator} {minimum}, got {value!r}"
        )
    return value


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
    schema_cache_ttl: float = 300.0
    schema_cache_max: int = 64
    max_attachment_bytes: int = 1048576
    timeout: float = 30.0

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
        max_records = _int_env("ODOO_MAX_RECORDS", 200, minimum=1)
        verify_ssl = os.environ.get("ODOO_VERIFY_SSL", "true").lower() not in (
            "false",
            "0",
            "no",
        )
        writable_models = frozenset(
            model.strip()
            for model in os.environ.get("ODOO_WRITABLE_MODELS", "").split(",")
            if model.strip()
        )
        allow_delete = os.environ.get("ODOO_ALLOW_DELETE", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        schema_cache_ttl = _float_env(
            "ODOO_SCHEMA_CACHE_TTL", 300.0, minimum=0.0
        )
        schema_cache_max = _int_env("ODOO_SCHEMA_CACHE_MAX", 64, minimum=1)
        max_attachment_bytes = _int_env(
            "ODOO_MAX_ATTACHMENT_BYTES", 1048576, minimum=1
        )
        timeout = _float_env("ODOO_TIMEOUT", 30.0, minimum=0.0, strict=True)

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
            schema_cache_ttl=schema_cache_ttl,
            schema_cache_max=schema_cache_max,
            max_attachment_bytes=max_attachment_bytes,
            timeout=timeout,
        )

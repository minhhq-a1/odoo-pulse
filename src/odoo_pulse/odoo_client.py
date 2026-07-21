"""Thin XML-RPC client for Odoo's external API.

Wraps the two standard endpoints exposed by every Odoo instance:
  - /xmlrpc/2/common  -> authentication / version info
  - /xmlrpc/2/object  -> execute_kw for model access (ORM over the wire)

The client is intentionally read-only friendly: it exposes generic helpers
(search_read, read, search_count, fields_get) and a guarded execute_kw that
blocks every method not on a read allow-list unless writes are explicitly enabled.
This keeps the MCP surface safe by default.
"""

from __future__ import annotations

import re
import ssl
import threading
import xmlrpc.client
from functools import cached_property
from typing import Any

from .cache import TTLCache
from .core.config import OdooConfig
from .core.errors import OdooConfigError, OdooError  # noqa: F401 - transitional re-exports for Task 3

# Methods execute_kw may run WITHOUT write authorisation. This is an
# allow-list on purpose: any method not listed here — including ORM button
# methods like action_cancel or toggle_active — is treated as a mutation
# and must clear _check_write. New/unknown methods therefore fail closed.
READ_METHODS = frozenset(
    {
        "search",
        "search_read",
        "search_count",
        "read",
        "fields_get",
        "read_group",
        "formatted_read_group",
        "name_search",
        "name_get",
        "default_get",
    }
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

# Default attribute set requested from Odoo's fields_get.
DEFAULT_FIELD_ATTRS = ["string", "type", "help", "required", "relation"]

# Aggregator suffixes that formatted_read_group accepts in its ``order`` spec
# (e.g. "price_subtotal:sum desc"). Legacy read_group's ``orderby`` does not
# understand them, so they are stripped before dispatching to Odoo <= 18.
_ORDER_AGGREGATORS = frozenset(
    {
        "sum",
        "avg",
        "min",
        "max",
        "count",
        "count_distinct",
        "array_agg",
        "bool_and",
        "bool_or",
    }
)

# Sentinel distinguishing "not yet looked up" from a real None major version.
_UNSET = object()


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


class OdooClient:
    def __init__(self, config: OdooConfig):
        self.config = config
        self._schema_cache = TTLCache(config.schema_cache_ttl, config.schema_cache_max)
        self._major_version: Any = _UNSET
        self._uid: int | None = None
        self._uid_lock = threading.Lock()

    @cached_property
    def _ssl_context(self) -> ssl.SSLContext | None:
        # Only relevant for https endpoints. When verification is disabled we
        # accept self-signed certs via a context with verification off.
        if self.config.verify_ssl:
            return None
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _make_transport(self) -> xmlrpc.client.Transport:
        # ServerProxy only wires up `context=` when it builds its own default
        # transport; since we need a custom Transport for the timeout, we
        # build it ourselves and forward the SSL context through it.
        if self.config.url.lower().startswith("https"):
            return _TimeoutSafeTransport(self.config.timeout, context=self._ssl_context)
        return _TimeoutTransport(self.config.timeout)

    def _proxy(self, path: str) -> xmlrpc.client.ServerProxy:
        """Fresh proxy per call: ServerProxy is not thread-safe, and the
        construction cost is negligible next to the XML-RPC round-trip."""
        return xmlrpc.client.ServerProxy(
            f"{self.config.url}{path}",
            allow_none=True,
            transport=self._make_transport(),
        )

    def _authenticate(self) -> int:
        try:
            uid = self._proxy("/xmlrpc/2/common").authenticate(
                self.config.db, self.config.username, self.config.api_key, {}
            )
        except xmlrpc.client.Fault as exc:  # pragma: no cover - network dependent
            raise OdooError(f"Authentication failed: {exc.faultString}") from exc
        except (OSError, xmlrpc.client.ProtocolError) as exc:
            raise OdooError(f"Cannot reach Odoo at {self.config.url}: {exc}") from exc
        if not uid:
            raise OdooError(
                "Authentication failed: invalid credentials or database name."
            )
        return uid

    @property
    def uid(self) -> int:
        if self._uid is None:
            with self._uid_lock:
                if self._uid is None:
                    self._uid = self._authenticate()
        return self._uid

    def version(self) -> dict[str, Any]:
        try:
            return self._proxy("/xmlrpc/2/common").version()
        except (OSError, xmlrpc.client.ProtocolError) as exc:
            raise OdooError(f"Cannot reach Odoo at {self.config.url}: {exc}") from exc

    @staticmethod
    def _parse_major(server_version: Any) -> int | None:
        if not server_version:
            return None
        match = re.search(r"(\d+)", str(server_version))
        return int(match.group(1)) if match else None

    def major_version(self) -> int | None:
        """Major Odoo version (e.g. 18), cached on the instance. None if unknown.

        Not lock-guarded: if two threads race here, both may compute and
        assign the same value redundantly (one extra network call). This is
        a benign race - the result is idempotent - so no lock is used.
        """
        if self._major_version is _UNSET:
            self._major_version = self._parse_major(self.version().get("server_version"))
        return self._major_version

    @staticmethod
    def _legacy_orderby(order: str) -> str:
        """Translate a formatted_read_group order spec for legacy read_group.

        Strips ':agg' suffixes (e.g. 'price_subtotal:sum desc' ->
        'price_subtotal desc'); non-aggregator suffixes are kept unchanged.
        """
        terms = []
        for term in order.split(","):
            term = term.strip()
            if not term:
                continue
            field, _, direction = term.partition(" ")
            name, sep, suffix = field.partition(":")
            if sep and suffix in _ORDER_AGGREGATORS:
                field = name
            terms.append(f"{field} {direction.strip()}".strip())
        return ", ".join(terms)

    @staticmethod
    def _normalise_legacy_rows(
        rows: list[dict], specs: list[str], group_by: list[str]
    ) -> list[dict]:
        """Rename legacy read_group aggregate keys to their spec form.

        Legacy rows carry aggregates under the bare field name; the
        formatted_read_group path keys them '<field>:<agg>'. Grouped field
        names are left alone so group labels survive.
        """
        group_names = {g.partition(":")[0] for g in group_by}
        for row in rows:
            for spec in specs:
                field = spec.partition(":")[0]
                if field in group_names:
                    continue
                if spec not in row and field in row:
                    row[spec] = row.pop(field)
        return rows

    def _read_group(self, model, domain, group_by, specs, limit, offset, order):
        kwargs: dict[str, Any] = {
            "fields": specs,
            "groupby": group_by,
            "lazy": False,
            "offset": offset,
        }
        if limit:
            kwargs["limit"] = limit
        if order:
            kwargs["orderby"] = self._legacy_orderby(order)
        return self.execute_kw(model, "read_group", [domain or []], kwargs)

    def _formatted_read_group(self, model, domain, group_by, specs, limit, offset, order):
        kwargs: dict[str, Any] = {
            "groupby": group_by,
            "aggregates": specs,
            "offset": offset,
        }
        if limit:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return self.execute_kw(model, "formatted_read_group", [domain or []], kwargs)

    def aggregate_records(
        self,
        model: str,
        group_by: list[str],
        measures: list[tuple[str, str]],
        domain: list | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> dict:
        """Server-side grouping. ``measures`` is a list of (field, aggregator).

        Dispatches between Odoo 19+ ``formatted_read_group`` and the legacy
        ``read_group`` used on Odoo <= 18. Both methods are read-only.
        """
        specs = [f"{field}:{agg}" for field, agg in measures]
        # formatted_read_group returns no count when aggregates is empty,
        # whereas legacy read_group(lazy=False) always includes __count.
        # Request it explicitly on both paths so every row carries __count
        # and every requested measure lands on its spec key.
        formatted_specs = [*specs, "__count"] if specs else ["__count"]
        capped = self._cap_limit(limit) if limit else None
        major = self.major_version()
        if major is not None and major >= 19:
            rows = self._formatted_read_group(
                model, domain, group_by, formatted_specs, capped, offset, order
            )
            return {"method": "formatted_read_group", "major_version": major, "rows": rows}
        if major is not None:
            rows = self._normalise_legacy_rows(
                self._read_group(model, domain, group_by, specs, capped, offset, order),
                specs,
                group_by,
            )
            return {"method": "read_group", "major_version": major, "rows": rows}
        try:
            rows = self._formatted_read_group(
                model, domain, group_by, formatted_specs, capped, offset, order
            )
            return {"method": "formatted_read_group", "major_version": None, "rows": rows}
        except OdooError:
            rows = self._normalise_legacy_rows(
                self._read_group(model, domain, group_by, specs, capped, offset, order),
                specs,
                group_by,
            )
            return {"method": "read_group", "major_version": None, "rows": rows}

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
        if method not in READ_METHODS:
            self._check_write(model, method)
        try:
            return self._proxy("/xmlrpc/2/object").execute_kw(
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
        except (OSError, xmlrpc.client.ProtocolError) as exc:
            raise OdooError(f"Cannot reach Odoo at {self.config.url}: {exc}") from exc

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
        context: dict | None = None,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {
            "fields": fields or [],
            "limit": self._cap_limit(limit),
            "offset": offset,
        }
        if order:
            kwargs["order"] = order
        if context:
            kwargs["context"] = context
        return self.execute_kw(model, "search_read", [domain or []], kwargs)

    def search_count(self, model: str, domain: list | None = None) -> int:
        return self.execute_kw(model, "search_count", [domain or []])

    def read(
        self, model: str, ids: list[int], fields: list[str] | None = None
    ) -> list[dict]:
        return self.execute_kw(model, "read", [ids], {"fields": fields or []})

    def create(self, model: str, values: dict) -> int:
        return self.execute_kw(model, "create", [values])

    def write(self, model: str, ids: list[int], values: dict) -> bool:
        return self.execute_kw(model, "write", [ids, values])

    def unlink(self, model: str, ids: list[int]) -> bool:
        return self.execute_kw(model, "unlink", [ids])

    def fields_get(
        self, model: str, attributes: list[str] | None = None, *, refresh: bool = False
    ) -> dict:
        attrs = attributes or DEFAULT_FIELD_ATTRS
        key = (model, tuple(attrs))
        if not refresh:
            hit = self._schema_cache.get(key)
            if hit is not None:
                return hit
        value = self.execute_kw(model, "fields_get", [], {"attributes": attrs})
        self._schema_cache.set(key, value)
        return value

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

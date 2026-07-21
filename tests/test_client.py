"""Tests for OdooClient against a fake XML-RPC proxy (no network)."""

from __future__ import annotations

import xmlrpc.client

import pytest

from odoo_pulse.core.config import OdooConfig
from odoo_pulse.core.errors import OdooError
from odoo_pulse.core.transport import _TimeoutSafeTransport, _TimeoutTransport
from odoo_pulse.odoo_client import OdooClient


class FakeProxy:
    """Stands in for the /xmlrpc/2/object ServerProxy."""

    def __init__(self, return_value=None, fault=None):
        self.return_value = return_value
        self.fault = fault
        self.calls: list[tuple] = []

    def execute_kw(self, db, uid, key, model, method, args, kwargs):
        self.calls.append((db, uid, key, model, method, args, kwargs))
        if self.fault:
            raise xmlrpc.client.Fault(2, self.fault)
        return self.return_value


def make_client(
    return_value=None,
    *,
    read_only=True,
    max_records=200,
    fault=None,
    writable_models=(),
    allow_delete=False,
):
    cfg = OdooConfig(
        url="https://acme.odoo.com",
        db="acme",
        username="me@acme.com",
        api_key="secret",
        read_only=read_only,
        max_records=max_records,
        writable_models=frozenset(writable_models),
        allow_delete=allow_delete,
    )
    client = OdooClient(cfg)
    proxy = FakeProxy(return_value=return_value, fault=fault)
    # Pre-seed the cached uid and stub out per-call proxy construction so no
    # real network/auth happens.
    client._uid = 42
    client._proxy = lambda path: proxy
    return client, proxy


def test_execute_kw_passes_credentials_and_payload():
    client, proxy = make_client(return_value=[{"id": 1}])
    out = client.execute_kw("res.partner", "search_read", [[("a", "=", 1)]], {"limit": 5})
    assert out == [{"id": 1}]
    db, uid, key, model, method, args, kwargs = proxy.calls[0]
    assert (db, uid, key) == ("acme", 42, "secret")
    assert model == "res.partner"
    assert method == "search_read"
    assert args == [[("a", "=", 1)]]
    assert kwargs == {"limit": 5}


def test_read_only_blocks_write_methods():
    client, proxy = make_client(read_only=True)
    for method in ("create", "write", "unlink"):
        with pytest.raises(OdooError):
            client.execute_kw("res.partner", method, [[1]])
    # Nothing should have reached the proxy.
    assert proxy.calls == []


def test_write_allowed_when_not_read_only():
    client, proxy = make_client(
        return_value=99, read_only=False, writable_models=["res.partner"]
    )
    assert client.execute_kw("res.partner", "create", [{"name": "X"}]) == 99
    assert proxy.calls[0][4] == "create"


def test_fault_is_wrapped_as_odoo_error():
    client, _ = make_client(fault="boom")
    with pytest.raises(OdooError) as exc:
        client.search_count("res.partner")
    assert "boom" in str(exc.value)


@pytest.mark.parametrize(
    "requested,expected",
    [(None, 200), (0, 200), (-1, 200), (5, 5), (500, 200)],
)
def test_search_read_caps_limit(requested, expected):
    client, proxy = make_client(return_value=[], max_records=200)
    client.search_read("res.partner", limit=requested)
    _, _, _, _, _, _, kwargs = proxy.calls[0]
    assert kwargs["limit"] == expected


def test_search_read_forwards_domain_fields_order():
    client, proxy = make_client(return_value=[])
    client.search_read(
        "sale.order",
        domain=[("state", "=", "sale")],
        fields=["name"],
        limit=10,
        offset=5,
        order="date_order desc",
    )
    _, _, _, model, method, args, kwargs = proxy.calls[0]
    assert model == "sale.order"
    assert method == "search_read"
    assert args == [[("state", "=", "sale")]]
    assert kwargs["fields"] == ["name"]
    assert kwargs["offset"] == 5
    assert kwargs["order"] == "date_order desc"


def test_read_and_fields_get_and_count():
    client, proxy = make_client(return_value=[{"id": 1, "name": "A"}])
    client.read("res.partner", [1], fields=["name"])
    assert proxy.calls[-1][4] == "read"
    assert proxy.calls[-1][5] == [[1]]

    client, proxy = make_client(return_value={"name": {"type": "char"}})
    client.fields_get("res.partner")
    assert proxy.calls[-1][4] == "fields_get"

    client, proxy = make_client(return_value=3)
    assert client.search_count("res.partner", [("x", "=", 1)]) == 3
    assert proxy.calls[-1][4] == "search_count"


def test_write_blocked_when_model_not_in_allow_list():
    client, proxy = make_client(read_only=False, writable_models=["crm.lead"])
    with pytest.raises(OdooError, match="allow-list|ODOO_WRITABLE_MODELS"):
        client.execute_kw("res.partner", "create", [{"name": "X"}])
    assert proxy.calls == []


def test_unknown_method_fails_closed_in_read_only():
    # action_cancel is not in READ_METHODS -> treated as a mutation ->
    # blocked by read-only mode before it ever reaches the proxy.
    client, proxy = make_client(read_only=True)
    with pytest.raises(OdooError, match="read-only"):
        client.execute_kw("sale.order", "action_cancel", [[1]])
    assert proxy.calls == []


def test_unknown_method_requires_writable_model():
    # Writes enabled, but 'sale.order' is NOT allow-listed -> an unknown
    # method is still blocked by the model allow-list.
    client, proxy = make_client(read_only=False, writable_models=["crm.lead"])
    with pytest.raises(OdooError, match="ODOO_WRITABLE_MODELS"):
        client.execute_kw("sale.order", "action_cancel", [[1]])
    assert proxy.calls == []


def test_unknown_method_allowed_on_writable_model():
    # On an allow-listed model with writes enabled, an ORM button method
    # clears the guard and reaches the proxy (same rule as action_confirm).
    client, proxy = make_client(
        return_value=True, read_only=False, writable_models=["sale.order"]
    )
    assert client.execute_kw("sale.order", "action_cancel", [[1]]) is True
    assert proxy.calls[0][4] == "action_cancel"



def test_system_models_blocked_even_if_listed():
    client, proxy = make_client(
        read_only=False, writable_models=["res.users", "ir.model", "base.x"]
    )
    for model in ("res.users", "ir.model", "ir.cron", "base.language.install"):
        with pytest.raises(OdooError, match="system model|protected"):
            client.execute_kw(model, "write", [[1], {"x": 1}])
    assert proxy.calls == []


def test_unlink_gated_by_allow_delete():
    client, proxy = make_client(read_only=False, writable_models=["crm.lead"])
    with pytest.raises(OdooError, match="delete|ODOO_ALLOW_DELETE"):
        client.execute_kw("crm.lead", "unlink", [[1]])
    assert proxy.calls == []

    client, proxy = make_client(
        read_only=False, writable_models=["crm.lead"], allow_delete=True
    )
    client.execute_kw("crm.lead", "unlink", [[1]])
    assert proxy.calls[0][4] == "unlink"


class _RaisingProxy:
    """Stands in for a ServerProxy whose transport can't reach the server."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def execute_kw(self, *args, **kwargs):
        raise self._exc

    def authenticate(self, *args, **kwargs):
        raise self._exc

    def version(self):
        raise self._exc


@pytest.mark.parametrize(
    "exc",
    [
        ConnectionError("connection refused"),
        TimeoutError("timed out"),
        OSError("network unreachable"),
        xmlrpc.client.ProtocolError("https://acme.odoo.com", 502, "Bad Gateway", {}),
    ],
)
def test_execute_kw_wraps_network_errors_as_odoo_error(exc):
    client, _ = make_client()
    client._proxy = lambda path: _RaisingProxy(exc)
    with pytest.raises(OdooError, match="Cannot reach Odoo"):
        client.execute_kw("res.partner", "search_read", [[]])


@pytest.mark.parametrize(
    "exc",
    [ConnectionError("connection refused"), OSError("network unreachable")],
)
def test_uid_wraps_network_errors_as_odoo_error(exc):
    cfg = OdooConfig(
        url="https://acme.odoo.com",
        db="acme",
        username="me@acme.com",
        api_key="secret",
    )
    client = OdooClient(cfg)
    client._proxy = lambda path: _RaisingProxy(exc)
    with pytest.raises(OdooError, match="Cannot reach Odoo"):
        client.uid  # noqa: B018 - property access is the thing under test


def test_version_wraps_network_errors_as_odoo_error():
    cfg = OdooConfig(
        url="https://acme.odoo.com",
        db="acme",
        username="me@acme.com",
        api_key="secret",
    )
    client = OdooClient(cfg)
    client._proxy = lambda path: _RaisingProxy(OSError("network unreachable"))
    with pytest.raises(OdooError, match="Cannot reach Odoo"):
        client.version()


def test_create_write_unlink_forward_to_execute_kw():
    client, proxy = make_client(
        return_value=55, read_only=False, writable_models=["crm.lead"], allow_delete=True
    )
    assert client.create("crm.lead", {"name": "X"}) == 55
    assert proxy.calls[-1][4] == "create"
    assert proxy.calls[-1][5] == [{"name": "X"}]

    client.write("crm.lead", [1, 2], {"name": "Y"})
    assert proxy.calls[-1][4] == "write"
    assert proxy.calls[-1][5] == [[1, 2], {"name": "Y"}]

    client.unlink("crm.lead", [3])
    assert proxy.calls[-1][4] == "unlink"
    assert proxy.calls[-1][5] == [[3]]


def test_make_transport_uses_timeout_safe_transport_for_https():
    cfg = OdooConfig(
        url="https://acme.odoo.com",
        db="acme",
        username="me@acme.com",
        api_key="secret",
        timeout=12.5,
    )
    client = OdooClient(cfg)
    transport = client._make_transport()
    assert isinstance(transport, _TimeoutSafeTransport)
    # No real connection is made; make_connection just builds the
    # (unconnected) HTTPSConnection and stamps the timeout on it.
    conn = transport.make_connection("acme.odoo.com")
    assert conn.timeout == 12.5


def test_make_transport_uses_plain_timeout_transport_for_http():
    cfg = OdooConfig(
        url="http://acme.local",
        db="acme",
        username="me@acme.com",
        api_key="secret",
        timeout=8,
    )
    client = OdooClient(cfg)
    transport = client._make_transport()
    assert isinstance(transport, _TimeoutTransport)
    assert not isinstance(transport, _TimeoutSafeTransport)
    conn = transport.make_connection("acme.local")
    assert conn.timeout == 8


def test_make_transport_honours_verify_ssl_false():
    cfg = OdooConfig(
        url="https://acme.odoo.com",
        db="acme",
        username="me@acme.com",
        api_key="secret",
        verify_ssl=False,
    )
    client = OdooClient(cfg)
    transport = client._make_transport()
    # SafeTransport stores the context passed at construction time; here it
    # must be the unverified context built from verify_ssl=False.
    assert transport.context is client._ssl_context
    assert transport.context.verify_mode.name == "CERT_NONE"


def test_each_execute_kw_builds_a_fresh_proxy(monkeypatch):
    import xmlrpc.client
    from odoo_pulse.odoo_client import OdooClient, OdooConfig

    instances = []

    class _FakeProxy:
        def __init__(self, url, allow_none=True, transport=None):
            instances.append(self)

        def execute_kw(self, *a, **k):
            return []

        def authenticate(self, *a, **k):
            return 2

    monkeypatch.setattr(xmlrpc.client, "ServerProxy", _FakeProxy)
    client = OdooClient(OdooConfig(
        url="http://x", db="d", username="u", api_key="k"))
    client.execute_kw("res.partner", "search_read", [[]])
    client.execute_kw("res.partner", "search_read", [[]])
    # 1 auth proxy + 2 object proxies
    assert len(instances) == 3


def test_uid_authenticates_once(monkeypatch):
    import xmlrpc.client
    from odoo_pulse.odoo_client import OdooClient, OdooConfig

    auth_calls = []

    class _FakeProxy:
        def __init__(self, url, allow_none=True, transport=None):
            self._url = url

        def authenticate(self, *a, **k):
            auth_calls.append(1)
            return 2

        def execute_kw(self, *a, **k):
            return []

    monkeypatch.setattr(xmlrpc.client, "ServerProxy", _FakeProxy)
    client = OdooClient(OdooConfig(
        url="http://x", db="d", username="u", api_key="k"))
    client.execute_kw("res.partner", "search_read", [[]])
    client.execute_kw("res.partner", "search_read", [[]])
    assert len(auth_calls) == 1


def test_search_read_forwards_context():
    client, proxy = make_client(return_value=[])
    client.search_read(
        "product.product", domain=[], fields=["id"],
        context={"allowed_company_ids": [1]},
    )
    kwargs = proxy.calls[0][6]  # calls: (db, uid, key, model, method, args, kwargs)
    assert kwargs["context"] == {"allowed_company_ids": [1]}


def test_search_read_omits_context_by_default():
    client, proxy = make_client(return_value=[])
    client.search_read("product.product", domain=[], fields=["id"])
    kwargs = proxy.calls[0][6]
    assert "context" not in kwargs

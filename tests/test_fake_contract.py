"""FakeClient must mirror OdooClient's public call signatures.

Every tool test runs against FakeClient, so a signature that drifts on the
real client (new parameter, changed default) would leave the suite green
while production breaks. This pins parameter names, kinds and defaults.
"""

from __future__ import annotations

import inspect

import pytest

from odoo_pulse.odoo_client import OdooClient
from tests.conftest import FakeClient

# Public OdooClient surface the tools rely on (and the fake implements).
CONTRACT = [
    "search_read",
    "search_count",
    "read",
    "fields_get",
    "execute_kw",
    "create",
    "write",
    "unlink",
    "aggregate_records",
    "list_models",
    "version",
    "major_version",
]


def _shape(func):
    return [
        (p.name, p.kind, p.default)
        for name, p in inspect.signature(func).parameters.items()
        if name != "self"
    ]


@pytest.mark.parametrize("method", CONTRACT)
def test_fake_signature_matches_real_client(method):
    assert _shape(getattr(FakeClient, method)) == _shape(getattr(OdooClient, method))


def test_contract_covers_every_public_client_method_the_fake_implements():
    real_public = {
        name
        for name, member in inspect.getmembers(OdooClient, inspect.isfunction)
        if not name.startswith("_")
    }
    fake_public = {
        name
        for name, member in inspect.getmembers(FakeClient, inspect.isfunction)
        if not name.startswith("_") and name != "last"
    }
    shared = real_public & fake_public
    assert shared <= set(CONTRACT), (
        f"methods shared by fake and real client but not pinned: "
        f"{sorted(shared - set(CONTRACT))}"
    )

"""Shared pytest fixtures: a fake Odoo client injected into the runtime so the
domain tools can be exercised without a real Odoo / network connection.
"""

from __future__ import annotations

import pytest

from odoo_pulse.mcp import runtime as mcp_runtime
from tests.support.fake_client import FakeClient


@pytest.fixture
def fake_client():
    fake = FakeClient()
    mcp_runtime._client = fake
    try:
        yield fake
    finally:
        mcp_runtime._client = None

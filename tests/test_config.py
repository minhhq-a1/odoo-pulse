"""Tests for OdooConfig.from_env()."""

from __future__ import annotations

import pytest

from odoo_mcp.odoo_client import OdooConfig, OdooConfigError

_REQUIRED = {
    "ODOO_URL": "https://acme.odoo.com/",
    "ODOO_DB": "acme",
    "ODOO_USERNAME": "me@acme.com",
    "ODOO_API_KEY": "secret",
}


def _set_env(monkeypatch, **overrides):
    env = {**_REQUIRED, **overrides}
    for key in (
        "ODOO_URL",
        "ODOO_DB",
        "ODOO_USERNAME",
        "ODOO_API_KEY",
        "ODOO_READ_ONLY",
        "ODOO_MAX_RECORDS",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_from_env_success_and_defaults(monkeypatch):
    _set_env(monkeypatch)
    cfg = OdooConfig.from_env()
    assert cfg.db == "acme"
    assert cfg.username == "me@acme.com"
    # Trailing slash is stripped from the URL.
    assert cfg.url == "https://acme.odoo.com"
    # Safe defaults.
    assert cfg.read_only is True
    assert cfg.max_records == 200


@pytest.mark.parametrize("missing", list(_REQUIRED))
def test_from_env_missing_required_raises(monkeypatch, missing):
    _set_env(monkeypatch, **{missing: ""})
    with pytest.raises(OdooConfigError) as exc:
        OdooConfig.from_env()
    assert missing in str(exc.value)


@pytest.mark.parametrize(
    "value,expected",
    [("false", False), ("0", False), ("no", False), ("true", True), ("anything", True)],
)
def test_read_only_parsing(monkeypatch, value, expected):
    _set_env(monkeypatch, ODOO_READ_ONLY=value)
    assert OdooConfig.from_env().read_only is expected


def test_max_records_parsing_and_fallback(monkeypatch):
    _set_env(monkeypatch, ODOO_MAX_RECORDS="50")
    assert OdooConfig.from_env().max_records == 50

    _set_env(monkeypatch, ODOO_MAX_RECORDS="not-a-number")
    assert OdooConfig.from_env().max_records == 200

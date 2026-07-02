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


def test_from_env_parses_writable_models_and_allow_delete(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://acme.odoo.com")
    monkeypatch.setenv("ODOO_DB", "acme")
    monkeypatch.setenv("ODOO_USERNAME", "me@acme.com")
    monkeypatch.setenv("ODOO_API_KEY", "secret")
    monkeypatch.setenv("ODOO_WRITABLE_MODELS", "crm.lead, res.partner ,")
    monkeypatch.setenv("ODOO_ALLOW_DELETE", "true")

    cfg = OdooConfig.from_env()

    assert cfg.writable_models == frozenset({"crm.lead", "res.partner"})
    assert cfg.allow_delete is True


def test_from_env_writable_models_defaults_empty(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://acme.odoo.com")
    monkeypatch.setenv("ODOO_DB", "acme")
    monkeypatch.setenv("ODOO_USERNAME", "me@acme.com")
    monkeypatch.setenv("ODOO_API_KEY", "secret")
    monkeypatch.delenv("ODOO_WRITABLE_MODELS", raising=False)
    monkeypatch.delenv("ODOO_ALLOW_DELETE", raising=False)

    cfg = OdooConfig.from_env()

    assert cfg.writable_models == frozenset()
    assert cfg.allow_delete is False


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("YES", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("", False),
        # Fail-safe: anything not explicitly truthy (including typos) stays
        # disabled, unlike the old "not in (false, 0, no, '')" logic that
        # would have enabled deletes here.
        ("flase", False),
        ("anything", False),
    ],
)
def test_allow_delete_only_true_for_explicit_values(monkeypatch, value, expected):
    _set_env(monkeypatch, ODOO_ALLOW_DELETE=value)
    assert OdooConfig.from_env().allow_delete is expected


def test_timeout_default(monkeypatch):
    _set_env(monkeypatch)
    monkeypatch.delenv("ODOO_TIMEOUT", raising=False)
    assert OdooConfig.from_env().timeout == 30.0


def test_timeout_parsing_and_fallback(monkeypatch):
    _set_env(monkeypatch, ODOO_TIMEOUT="5.5")
    assert OdooConfig.from_env().timeout == 5.5

    _set_env(monkeypatch, ODOO_TIMEOUT="not-a-number")
    assert OdooConfig.from_env().timeout == 30.0


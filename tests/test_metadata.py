"""Release metadata must stay in lock-step with pyproject.toml's version."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def _json(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_package_version_matches_pyproject():
    import odoo_pulse

    assert odoo_pulse.__version__ == _pyproject_version()


def test_server_json_versions_match_pyproject():
    data = _json("server.json")
    versions = {data["version"], *(p["version"] for p in data.get("packages", []))}
    assert versions == {_pyproject_version()}


@pytest.mark.parametrize("name", ["manifest.json", ".claude-plugin/plugin.json"])
def test_other_metadata_versions_match_pyproject(name):
    assert _json(name)["version"] == _pyproject_version()

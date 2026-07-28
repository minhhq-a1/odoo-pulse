"""Contract tests for the canonical release identity and tag rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release" / "release_contract.py"


def load_contract():
    spec = importlib.util.spec_from_file_location("release_contract", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_identity_stable():
    identity = load_contract().release_identity("1.9.0")
    assert identity.python_version == "1.9.0"
    assert identity.semver_version == "1.9.0"
    assert identity.tag == "v1.9.0"
    assert identity.prerelease is False


def test_release_identity_rc():
    identity = load_contract().release_identity("1.9.0rc12")
    assert identity.python_version == "1.9.0rc12"
    assert identity.semver_version == "1.9.0-rc.12"
    assert identity.tag == "v1.9.0rc12"
    assert identity.prerelease is True


@pytest.mark.parametrize("value", ["1.9", "1.9.0-rc.1", "1.9.0b1", "v1.9.0"])
def test_release_identity_rejects_unknown_shapes(value):
    with pytest.raises(ValueError, match="stable X.Y.Z or RC X.Y.ZrcN"):
        load_contract().release_identity(value)


def test_validate_tag_accepts_stable():
    module = load_contract()
    module.validate_tag("v1.9.0", module.release_identity("1.9.0"))


def test_validate_tag_accepts_rc():
    module = load_contract()
    module.validate_tag("v1.9.0rc1", module.release_identity("1.9.0rc1"))


@pytest.mark.parametrize("tag", ["1.9.0", "v1.9.0rc1", "v1.9.1"])
def test_validate_tag_rejects_non_exact_tag(tag):
    module = load_contract()
    with pytest.raises(ValueError, match="does not match project version"):
        module.validate_tag(tag, module.release_identity("1.9.0"))


def test_identity_cli_writes_github_outputs(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "odoo-pulse"\nversion = "1.9.0rc1"\n'
    )
    output = tmp_path / "github-output"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "identity",
            "--root",
            str(tmp_path),
            "--tag",
            "v1.9.0rc1",
            "--github-output",
            str(output),
        ],
        check=True,
    )
    assert output.read_text().splitlines() == [
        "version=1.9.0rc1",
        "semver_version=1.9.0-rc.1",
        "tag=v1.9.0rc1",
        "prerelease=true",
    ]

"""Contract tests for version synchronization and metadata integrity."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

try:  # Python 3.11+ ships tomllib; 3.10 needs the tomli backport.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def metadata_fixture(tmp_path):
    for name in ["pyproject.toml", "manifest.json", "server.json"]:
        shutil.copy(ROOT / name, tmp_path / name)
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    shutil.copy(ROOT / ".claude-plugin" / "plugin.json", plugin_dir / "plugin.json")
    return tmp_path


def run_sync(root, *args, check=True):
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/release/sync_version.py"),
            "--root",
            str(root),
            *args,
        ],
        check=check,
        capture_output=True,
        text=True,
    )


def test_package_version_matches_project_metadata():
    from odoo_pulse import __version__

    assert __version__ == project_version()


def test_sync_version_check_passes_for_repository():
    run_sync(ROOT, "--check")


def test_sync_version_check_reports_drift_without_writing(tmp_path):
    root = metadata_fixture(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["version"] = "0.0.0"
    before = json.dumps(manifest, indent=2) + "\n"
    (root / "manifest.json").write_text(before)
    result = run_sync(root, "--check", check=False)
    assert result.returncode == 1
    assert "manifest.json" in result.stdout
    assert (root / "manifest.json").read_text() == before


def test_sync_version_is_idempotent(tmp_path):
    root = metadata_fixture(tmp_path)
    run_sync(root)
    first = {
        path.relative_to(root): path.read_text()
        for path in root.rglob("*.json")
    }
    run_sync(root)
    second = {
        path.relative_to(root): path.read_text()
        for path in root.rglob("*.json")
    }
    assert second == first

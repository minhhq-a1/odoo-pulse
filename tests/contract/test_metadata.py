"""Contract tests for version synchronization and metadata integrity."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

try:  # Python 3.11+ ships tomllib; 3.10 needs the tomli backport.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def replace_project_version(path: Path, version: str) -> None:
    """Rewrite only the first ``version`` line inside ``[project]``."""

    lines = path.read_text().splitlines(keepends=True)
    in_project = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped == "[project]"
            continue
        if in_project and stripped.startswith("version"):
            lines[index] = f'version = "{version}"\n'
            path.write_text("".join(lines))
            return
    raise AssertionError(f"No [project] version line found in {path}")


def metadata_fixture(tmp_path, version: str = "1.8.2"):
    for name in ["pyproject.toml", "manifest.json", "server.json"]:
        shutil.copy(ROOT / name, tmp_path / name)
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    shutil.copy(ROOT / ".claude-plugin" / "plugin.json", plugin_dir / "plugin.json")
    replace_project_version(tmp_path / "pyproject.toml", version)
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


def test_project_declares_tested_mcp_v1_range():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert "mcp[cli]>=1.3,<2" in project["dependencies"]


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


def test_sync_version_maps_rc_across_ecosystems(tmp_path):
    root = metadata_fixture(tmp_path, version="1.9.0rc1")
    run_sync(root)
    manifest = json.loads((root / "manifest.json").read_text())
    plugin = json.loads((root / ".claude-plugin/plugin.json").read_text())
    server = json.loads((root / "server.json").read_text())
    assert manifest["version"] == "1.9.0-rc.1"
    assert plugin["version"] == "1.9.0-rc.1"
    assert server["version"] == "1.9.0-rc.1"
    assert server["packages"][0]["version"] == "1.9.0rc1"


def test_sync_version_maps_stable_identically(tmp_path):
    root = metadata_fixture(tmp_path, version="1.9.0")
    run_sync(root)
    manifest = json.loads((root / "manifest.json").read_text())
    plugin = json.loads((root / ".claude-plugin/plugin.json").read_text())
    server = json.loads((root / "server.json").read_text())
    assert manifest["version"] == plugin["version"] == server["version"] == "1.9.0"
    assert server["packages"][0]["version"] == "1.9.0"


@pytest.mark.parametrize(
    "relative",
    [
        "manifest.json",
        "server.json",
        ".claude-plugin/plugin.json",
        "pyproject.toml",
    ],
)
@pytest.mark.parametrize("check_mode", [False, True])
def test_sync_version_fails_when_required_target_is_missing(
    tmp_path, relative, check_mode
):
    root = metadata_fixture(tmp_path)
    (root / relative).unlink()
    args = ["--check"] if check_mode else []
    result = run_sync(root, *args, check=False)
    assert result.returncode != 0
    assert relative in result.stderr


@pytest.mark.parametrize("check_mode", [False, True])
def test_sync_version_fails_when_a_version_field_is_unreachable(tmp_path, check_mode):
    root = metadata_fixture(tmp_path)
    server = json.loads((root / "server.json").read_text())
    server["packages"] = []
    (root / "server.json").write_text(json.dumps(server, indent=2) + "\n")
    args = ["--check"] if check_mode else []
    result = run_sync(root, *args, check=False)
    assert result.returncode != 0
    assert "server.json" in result.stderr
    assert "packages.0.version" in result.stderr
    assert "Traceback" not in result.stderr

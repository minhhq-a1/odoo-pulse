from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "release" / "publish_smithery.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _python_310() -> str:
    if sys.version_info[:2] == (3, 10):
        return sys.executable
    executable = shutil.which("python3.10")
    if executable is None:
        pytest.skip("Python 3.10 is not available in this test environment")
    return executable


def _run_publish_script(
    tmp_path: Path,
    *,
    release_status: str,
    python_executable: str | None = None,
) -> subprocess.CompletedProcess[str]:
    repo = tmp_path / "repo"
    script = repo / "scripts" / "release" / SCRIPT.name
    script.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, script)

    (repo / "pyproject.toml").write_text('[project]\nversion = "1.9.0"\n')
    bundle = repo / "dist" / "odoo-pulse-1.9.0.mcpb"
    bundle.parent.mkdir()
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", '{"version":"1.9.0"}')

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "npx",
        "#!/usr/bin/env bash\nprintf '%s\\n' '{\"deploymentId\":\"deployment-123\"}'\n",
    )
    _write_executable(
        fake_bin / "curl",
        "#!/usr/bin/env bash\n"
        "printf '{\"releases\":[{\"id\":\"deployment-123\",\"status\":\"%s\"}]}\\n' "
        '"${SMITHERY_TEST_STATUS}"\n',
    )
    _write_executable(fake_bin / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "SMITHERY_API_KEY": "test-key-not-a-secret",
            "SMITHERY_TEST_STATUS": release_status,
        }
    )
    if python_executable is not None:
        (fake_bin / "python3").symlink_to(python_executable)
        tomli_shim = tmp_path / "python-modules"
        tomli_shim.mkdir()
        (tomli_shim / "tomli.py").write_text(
            "def load(stream):\n"
            "    text = stream.read().decode()\n"
            "    version = text.split('version = \\\"', 1)[1].split('\\\"', 1)[0]\n"
            "    return {'project': {'version': version}}\n"
        )
        env["PYTHONPATH"] = str(tomli_shim)

    return subprocess.run(
        ["bash", str(script)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_publish_smithery_fails_when_deployment_never_becomes_live(tmp_path: Path) -> None:
    result = _run_publish_script(tmp_path, release_status="PENDING")

    assert result.returncode != 0
    assert "treat the mirror as unverified" in result.stderr


def test_publish_smithery_loads_project_version_on_python_310(tmp_path: Path) -> None:
    result = _run_publish_script(
        tmp_path,
        release_status="SUCCESS",
        python_executable=_python_310(),
    )

    assert result.returncode == 0, result.stderr
    assert "deployment deployment-123 (version 1.9.0) is live" in result.stdout

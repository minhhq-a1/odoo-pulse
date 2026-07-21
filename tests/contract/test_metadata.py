import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(
        r'^version\s*=\s*"([^"]+)"$', text, flags=re.MULTILINE
    )
    assert match is not None
    return match.group(1)


def test_release_versions_match_pyproject():
    version = project_version()
    manifest = json.loads((ROOT / "manifest.json").read_text())
    server = json.loads((ROOT / "server.json").read_text())
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())

    assert manifest["version"] == version
    assert server["version"] == version
    assert server["packages"][0]["version"] == version
    assert plugin["version"] == version


def test_env_example_documents_groups_without_volatile_count():
    text = (ROOT / ".env.example").read_text()
    assert "Default: core,reports" in text
    assert not re.search(r"Default: core,reports \(\d+ tools\)", text)
    assert "business, hr, projects, operations, engagement, niche" in text

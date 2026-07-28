"""Static contract tests for the release workflow topology.

These assert structure, ordering, and permission scope in the workflow files
themselves. They never call GitHub, so a mistake that would publish the wrong
artifact fails locally instead of in production.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def docker_text() -> str:
    return (WORKFLOWS / "docker.yml").read_text()


def workflow_payload(name: str) -> dict:
    """Parse a workflow with BaseLoader so YAML 1.1 keeps ``on`` a string key."""

    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def test_docker_workflow_is_reusable_and_manual_not_tag_triggered():
    text = docker_text()
    assert "workflow_call:" in text
    assert "workflow_dispatch:" in text
    assert 'tags:\n      - "v*"' not in text


def test_docker_workflow_uses_pep440_and_removes_raw_latest():
    text = docker_text()
    assert "type=pep440,pattern={{version}}" in text
    assert "type=pep440,pattern={{major}}.{{minor}}" in text
    assert "type=pep440,pattern={{major}}" in text
    assert "type=raw,value=latest" not in text
    assert "type=semver" not in text


def test_docker_workflow_checks_exact_aliases_before_build():
    text = docker_text()
    check = text.index("check-docker-tags")
    build = text.index("docker/build-push-action")
    assert check < build


def test_docker_workflow_probes_before_any_push():
    text = docker_text()
    assert text.index("Probe MCP surface") < text.index("docker push --all-tags")


def test_docker_workflow_scopes_package_write_to_push_job():
    jobs = workflow_payload("docker.yml")["jobs"]
    assert jobs["build-probe"]["permissions"] == {"contents": "read"}
    assert jobs["push_image"]["permissions"] == {
        "contents": "read",
        "packages": "write",
    }

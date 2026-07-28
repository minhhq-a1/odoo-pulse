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


def release_text() -> str:
    return (WORKFLOWS / "release.yml").read_text()


def mcp_text() -> str:
    return (WORKFLOWS / "publish-mcp.yml").read_text()


def job_slice(text: str, job: str) -> str:
    """Return the raw text of one job, from its key to the next sibling key."""

    lines = text.splitlines()
    start = lines.index(f"  {job}:")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("   ") and line.strip():
            end = index
            break
    return "\n".join(lines[start:end])


def workflow_payload(name: str) -> dict:
    """Parse a workflow with BaseLoader so YAML 1.1 keeps ``on`` a string key."""

    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def test_docker_workflow_is_reusable_and_manual_not_tag_triggered():
    text = docker_text()
    assert "workflow_call:" in text
    assert "workflow_dispatch:" in text
    assert 'tags:\n      - "v*"' not in text
    # Structural, so a tag trigger cannot slip back in at another indentation
    # or in flow style.
    assert "push" not in workflow_payload("docker.yml")["on"]


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


def test_docker_workflow_verifies_the_pushed_set_against_the_probed_set():
    text = docker_text()
    push = text.index("docker push --all-tags")
    # The recorded alias list must gate the push and be re-checked after it,
    # rather than being uploaded and then ignored.
    assert text.index("diff probed.txt loaded.txt") < push
    assert text.rindex("tags.txt") > push
    assert "Manifest.Digest" in text


def test_docker_workflow_scopes_package_write_to_push_job():
    jobs = workflow_payload("docker.yml")["jobs"]
    assert jobs["build-probe"]["permissions"] == {"contents": "read"}
    assert jobs["push_image"]["permissions"] == {
        "contents": "read",
        "packages": "write",
    }


def test_release_workflow_is_the_only_tag_orchestrator():
    text = release_text()
    assert 'tags:\n      - "v*"' in text
    assert "release_contract.py identity" in text
    assert workflow_payload("release.yml")["on"]["push"] == {"tags": ["v*"]}
    for name in ["docker.yml", "publish-mcp.yml", "ci.yml", "playground.yml"]:
        triggers = workflow_payload(name)["on"]
        assert "tags" not in (triggers.get("push") or {}), name


def test_release_validates_before_build_or_publish():
    text = release_text()
    validate = text.index("release_contract.py identity")
    assert validate < text.index("python -m build")
    assert validate < text.index("pypa/gh-action-pypi-publish")


def test_release_builds_once_and_downstream_jobs_download_dist():
    text = release_text()
    assert text.count("python -m build") == 1
    assert "actions/download-artifact" in job_slice(text, "publish-pypi")
    assert "actions/download-artifact" in job_slice(text, "release-record")


def test_release_does_not_skip_existing_pypi_files():
    assert "skip-existing" not in release_text()


def test_release_sequences_docker_after_pypi():
    docker = job_slice(release_text(), "docker")
    assert "publish-pypi" in docker
    assert "./.github/workflows/docker.yml" in docker


def test_release_record_waits_for_docker_and_owns_contents_write():
    text = release_text()
    record = job_slice(text, "release-record")
    assert "docker" in record
    assert "contents: write" in record
    assert "contents: write" not in job_slice(text, "build")
    assert "contents: write" not in job_slice(text, "publish-pypi")


def test_release_record_marks_rc_as_prerelease():
    record = job_slice(release_text(), "release-record")
    assert "needs.validate.outputs.prerelease" in record
    assert record.count("--prerelease") == 1
    true_branch = record.index("true)")
    false_branch = record.index("false)")
    wildcard = record.index("*)")
    assert true_branch < record.index("--prerelease") < false_branch < wildcard
    # Fail closed: an unexpected value must abort, never fall through to stable.
    assert "exit 1" in record[wildcard:]


def test_release_checks_the_notes_file_before_publishing():
    text = release_text()
    # The notes path must follow the tag, not be pinned to one release.
    assert "docs/releases/v1.9.0.md" not in text
    assert 'test -f "docs/releases/${TAG}.md"' in job_slice(text, "validate")
    assert '--notes-file "docs/releases/${TAG}.md"' in job_slice(
        text, "release-record"
    )


def test_release_record_requires_a_pushed_image_digest():
    record = job_slice(release_text(), "release-record")
    assert "needs.docker.outputs.digest" in record
    assert 'test -n "$DIGEST"' in record


def test_mcp_publish_requires_explicit_release_ref():
    payload = workflow_payload("publish-mcp.yml")
    inputs = payload["on"]["workflow_dispatch"]["inputs"]
    assert inputs["release_ref"]["required"] == "true"
    assert inputs["release_ref"]["type"] == "string"
    assert "workflow_call" not in payload["on"]
    assert "push" not in payload["on"]


def test_mcp_publish_checks_out_explicit_ref():
    assert "ref: ${{ inputs.release_ref }}" in mcp_text()


def test_mcp_publish_rejects_prerelease_before_oidc_login():
    text = mcp_text()
    login = text.index("mcp-publisher login")
    # The gate must be fail-closed: a non-zero exit from the release contract,
    # not a shell string match that treats any anomaly as "stable".
    assert text.index("--require-stable") < login
    assert "grep -qx 'prerelease=true'" not in text
    assert text.index("sync_version.py --check") < login


def test_mcp_publish_validates_manifest_and_live_pypi_before_publish():
    text = mcp_text()
    publish = text.index("mcp-publisher publish")
    assert text.index("mcp-publisher validate server.json") < publish
    assert text.index("pypi.org/pypi/odoo-pulse/") < publish
    permissions = workflow_payload("publish-mcp.yml")["jobs"]["publish"][
        "permissions"
    ]
    assert permissions == {"contents": "read", "id-token": "write"}

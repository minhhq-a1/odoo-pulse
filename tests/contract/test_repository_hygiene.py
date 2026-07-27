import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_CONFIG_FILES = [
    ROOT / ".env.example",
    ROOT / "README.md",
    ROOT / "docs" / "guides" / "install.md",
]


def test_public_config_uses_placeholders_and_tls_verification():
    texts = {path: path.read_text() for path in PUBLIC_CONFIG_FILES}
    assert "ODOO_API_KEY=your-api-key" in texts[ROOT / ".env.example"]
    assert "ODOO_VERIFY_SSL=true" in texts[ROOT / ".env.example"]
    for path, text in texts.items():
        assert "ODOO_VERIFY_SSL=false" not in text, path
    assert "your-api-key" in texts[ROOT / "README.md"]
    assert "your-api-key" in texts[ROOT / "docs" / "guides" / "install.md"]


def test_install_docs_include_self_contained_redacted_secret_scans():
    text = (ROOT / "docs" / "guides" / "install.md").read_text()
    assert 'gitleaks git --redact --log-opts="--all" .' in text
    assert "git fsck --full --no-reflogs --unreachable" in text
    assert "git-leaks" not in text
    assert "gitleaks dir --redact" in text
    assert "audit-remediation plan" not in text
    assert "trusted private CA" in text


def test_shipped_docs_are_visible_and_do_not_reference_internal_plans():
    expected = [
        "docs/architecture/overview.md",
        "docs/guides/install.md",
        "docs/guides/playground.md",
        "docs/reference/tools.md",
        "docs/releases/project-finance-consistency.md",
    ]
    for relative in expected:
        path = ROOT / relative
        assert path.is_file(), f"Missing shipped doc: {relative}"
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", relative], cwd=ROOT
        )
        assert ignored.returncode == 1, f"Shipped doc is ignored: {relative}"
        assert "docs/superpowers/" not in path.read_text(), f"Internal plan link found in: {relative}"


def test_active_repository_paths_use_final_layout():
    expected = [
        "scripts/assets/make_icon.py",
        "scripts/assets/make_og.py",
        "scripts/demo/demo.tape",
        "scripts/demo/demo_pulse.py",
        "scripts/release/publish_smithery.sh",
        "scripts/release/sync_version.py",
        "scripts/smoke/live.py",
        "scripts/smoke/playground.sh",
        "scripts/smoke/project_status.py",
        "deploy/playground/compose.yml",
        "deploy/playground/seed/seed.py",
    ]
    assert all((ROOT / path).is_file() for path in expected)
    stale = [
        "docker-compose.playground.yml", "docker/seed/seed.py",
        "scripts/demo.tape", "scripts/demo_pulse.py",
        "scripts/make_icon.py", "scripts/make_og.py",
        "scripts/playground_smoke.sh", "scripts/publish_smithery.sh",
        "scripts/smoke_live.py", "scripts/smoke_project_status.py",
    ]
    assert all(not (ROOT / path).exists() for path in stale)

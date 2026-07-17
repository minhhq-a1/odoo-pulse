from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_CONFIG_FILES = [
    ROOT / ".env.example",
    ROOT / "README.md",
    ROOT / "docs" / "install.md",
]


def test_public_config_uses_placeholders_and_tls_verification():
    texts = {path: path.read_text() for path in PUBLIC_CONFIG_FILES}
    assert "ODOO_API_KEY=your-api-key" in texts[ROOT / ".env.example"]
    assert "ODOO_VERIFY_SSL=true" in texts[ROOT / ".env.example"]
    for path, text in texts.items():
        assert "ODOO_VERIFY_SSL=false" not in text, path
    assert "your-api-key" in texts[ROOT / "README.md"]
    assert "your-api-key" in texts[ROOT / "docs" / "install.md"]

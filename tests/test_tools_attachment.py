# tests/test_tools_attachment.py
import json

from odoo_mcp.tools_generic import read_attachment


def test_under_cap_includes_base64(fake_client):
    fake_client.read_responses["ir.attachment"] = [
        {
            "name": "invoice.pdf",
            "mimetype": "application/pdf",
            "file_size": 1024,
            "type": "binary",
            "url": False,
            "res_model": "account.move",
            "res_id": 42,
            "checksum": "abc",
            "create_date": "2026-06-01 10:00:00",
            "datas": "QkFTRTY0",
        }
    ]
    out = json.loads(read_attachment(7))
    assert out["data_included"] is True
    assert out["data_base64"] == "QkFTRTY0"
    assert out["warnings"] == []
    assert out["max_bytes"] == 1048576


def test_over_cap_omits_data_with_warning(fake_client):
    fake_client.config.max_attachment_bytes = 100
    fake_client.read_responses["ir.attachment"] = [
        {"name": "big.bin", "type": "binary", "file_size": 5000, "url": False, "datas": "X"}
    ]
    out = json.loads(read_attachment(7))
    assert out["data_included"] is False
    assert out["data_base64"] is None
    assert any("exceeds" in w for w in out["warnings"])


def test_url_type_returns_url_no_data(fake_client):
    fake_client.read_responses["ir.attachment"] = [
        {"name": "link", "type": "url", "url": "https://x/y", "file_size": 0}
    ]
    out = json.loads(read_attachment(7))
    assert out["data_included"] is False
    assert out["attachment"]["url"] == "https://x/y"
    assert any("URL" in w for w in out["warnings"])


def test_include_data_false_skips_blob(fake_client):
    fake_client.read_responses["ir.attachment"] = [
        {"name": "f", "type": "binary", "file_size": 10, "url": False, "datas": "Y"}
    ]
    out = json.loads(read_attachment(7, include_data=False))
    assert out["data_included"] is False
    assert out["data_base64"] is None


def test_missing_attachment_errors(fake_client):
    fake_client.read_responses["ir.attachment"] = []
    out = json.loads(read_attachment(999))
    assert "error" in out
    assert "999" in out["error"]

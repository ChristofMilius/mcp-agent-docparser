"""tests/test_receipts.py — receipt registry CRUD + validation."""
from __future__ import annotations

import json

import pytest

from mcp_agent_docparser.receipts import ReceiptRegistry


@pytest.fixture
def registry(tmp_path, sample_receipt):
    path = tmp_path / "receipts.json"
    path.write_text(json.dumps({"receipts": {}}, ensure_ascii=False), encoding="utf-8")
    reg = ReceiptRegistry(path)
    reg.upsert("sample", dict(sample_receipt), save=True)
    return reg


class TestLoad:
    def test_missing_file_starts_empty(self, tmp_path):
        reg = ReceiptRegistry(tmp_path / "nope.json")
        assert reg.keys() == []

    def test_creates_dir_on_save(self, tmp_path, sample_receipt):
        reg = ReceiptRegistry(tmp_path / "sub" / "dir" / "r.json")
        errors = reg.upsert("a", dict(sample_receipt), save=True)
        assert errors == []
        assert reg.get("a")["name"] == sample_receipt["name"]

    def test_roundtrip_preserves_all(self, registry, sample_receipt):
        got = registry.get("sample")
        for k, v in sample_receipt.items():
            assert got[k] == v


class TestUpsertValidate:
    def test_missing_required_field_rejected(self, registry):
        bad = {"name": "X", "urls": ["http://x"], "selectors": ["body"]}  # no language
        errors = registry.upsert("bad", bad, save=False)
        assert any("language" in e for e in errors)
        assert "bad" not in registry

    def test_urls_must_be_list(self, registry):
        bad = {"name": "X", "language": "py", "urls": "nope", "selectors": ["body"]}
        errors = registry.upsert("bad", bad, save=False)
        assert any("'urls' must be a list" in e for e in errors)

    def test_normalises_optional_keys(self, registry):
        minimal = {"name": "X", "language": "py", "urls": ["http://x"], "selectors": ["body"]}
        registry.upsert("min", minimal, save=True)
        got = registry.get("min")
        assert got["js_render"] is False
        assert got["markdown_passthrough"] is False
        assert got["notes"] == ""
        assert got["last_fetched"] is None
        assert got["strip_tags"] == []

    def test_upsert_replaces_existing(self, registry, sample_receipt):
        edited = dict(sample_receipt, name="Renamed")
        registry.upsert("sample", edited, save=True)
        assert registry.get("sample")["name"] == "Renamed"
        assert len(registry.keys()) == 1


class TestDeleteUpdate:
    def test_delete(self, registry):
        assert registry.delete("sample")
        assert not registry.delete("sample")

    def test_update_fields(self, registry):
        assert registry.update_fields("sample", {"notes": "updated"})
        assert registry.get("sample")["notes"] == "updated"

    def test_update_missing_key_returns_false(self, registry):
        assert not registry.update_fields("ghost", {"notes": "x"})


class TestMarkFetched:
    def test_records_fetch_metadata(self, registry):
        registry.mark_fetched("sample", "sample_20260101_000000.md")
        got = registry.get("sample")
        assert got["last_output"] == "sample_20260101_000000.md"
        assert got["last_fetched"] is not None

    def test_persists_to_disk(self, registry):
        registry.mark_fetched("sample", "x.md")
        raw = json.loads(registry.path.read_text(encoding="utf-8"))
        persisted = raw["receipts"]["sample"]
        assert persisted["last_output"] == "x.md"

"""tests/test_config.py — config path resolution."""
from __future__ import annotations

from mcp_agent_docparser.config import Config, _resolve_path


class TestResolvePath:
    def test_relative_resolves_against_project_root(self):
        p = _resolve_path("receipts.json")
        assert p.is_absolute()
        assert p.name == "receipts.json"

    def test_absolute_stays_absolute(self):
        import os

        root = "C:\\tmp\\x" if os.name == "nt" else "/tmp/x"
        p = _resolve_path(root)
        assert str(p) == root


class TestConfig:
    def test_defaults_without_env(self, monkeypatch):
        for k in (
            "DOCPARSER_RECEIPTS",
            "DOCPARSER_OUTPUT_DIR",
            "DOCPARSER_LOGS_DIR",
            "DOCPARSER_CACHE_DIR",
        ):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv("DOCPARSER_CACHE_TTL_SECONDS", raising=False)
        cfg = Config()
        assert cfg.receipts_path.name == "receipts.json"
        assert cfg.output_dir.name == "doc_output"
        assert cfg.logs_dir.name == "logs"
        assert cfg.cache_dir.name == "cache"
        assert cfg.cache_ttl_seconds == 0.0

    def test_env_override(self, monkeypatch, tmp_path):
        receipts = tmp_path / "r.json"
        out = tmp_path / "out"
        logs = tmp_path / "logs"
        cache_dir = tmp_path / "ccache"
        monkeypatch.setenv("DOCPARSER_RECEIPTS", str(receipts))
        monkeypatch.setenv("DOCPARSER_OUTPUT_DIR", str(out))
        monkeypatch.setenv("DOCPARSER_LOGS_DIR", str(logs))
        monkeypatch.setenv("DOCPARSER_CACHE_DIR", str(cache_dir))
        monkeypatch.setenv("DOCPARSER_CACHE_TTL_SECONDS", "600")
        cfg = Config()
        assert cfg.receipts_path == receipts
        assert cfg.output_dir == out
        assert cfg.logs_dir == logs
        assert cfg.cache_dir == cache_dir
        assert cfg.cache_ttl_seconds == 600.0

    def test_cache_ttl_junk_falls_back_to_zero(self, monkeypatch):
        for k in (
            "DOCPARSER_RECEIPTS",
            "DOCPARSER_OUTPUT_DIR",
            "DOCPARSER_LOGS_DIR",
            "DOCPARSER_CACHE_DIR",
        ):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("DOCPARSER_CACHE_TTL_SECONDS", "not-a-number")
        assert Config().cache_ttl_seconds == 0.0

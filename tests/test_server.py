"""tests/test_server.py — server assembly and parse pipeline."""

from __future__ import annotations

import types

import mcp.server.mcpserver
import pytest

from mcp_agent_docparser.context import AppContext
from mcp_agent_docparser.receipts import ReceiptRegistry
from mcp_agent_docparser.server import SERVER_NAME, create_server


def _ctx_paths(tmp_project, sample_receipt):
    """Like _ctx_sample but with Path objects for outputs (parse needs Path)."""
    from pathlib import Path

    root, env = tmp_project
    cfg = types.SimpleNamespace(
        receipts_path=Path(env["DOCPARSER_RECEIPTS"]),
        output_dir=Path(env["DOCPARSER_OUTPUT_DIR"]),
        logs_dir=Path(env["DOCPARSER_LOGS_DIR"]),
    )
    registry = ReceiptRegistry(cfg.receipts_path)
    registry.upsert("sample", dict(sample_receipt), save=False)
    return AppContext(cfg=cfg, registry=registry)


class TestCreateServer:
    def test_uses_mcpserver_contract(self, tmp_project, sample_receipt):
        server = create_server(_ctx_paths(tmp_project, sample_receipt))
        assert isinstance(server, mcp.server.mcpserver.MCPServer)
        assert server.name == SERVER_NAME

    def test_known_tool_names_registered(self, tmp_project, sample_receipt):
        server = create_server(_ctx_paths(tmp_project, sample_receipt))
        names = set(server._tool._tools) if hasattr(server, "_tool") else set()
        if not names:
            pytest.skip("mcpserver internals not introspectable on this version")
        assert {"doc_parse", "receipt_add", "doc_probe"}.issubset(names)


class TestParsePipeline:
    def test_dry_run_reports_without_fetching(self, tmp_project, sample_receipt, monkeypatch):
        root, env = tmp_project
        ctx = _ctx_paths(tmp_project, sample_receipt)

        def boom(*a, **kw):
            raise AssertionError("must not fetch in dry run")

        monkeypatch.setattr("mcp_agent_docparser.parse.fetch", boom)
        from mcp_agent_docparser.parse import parse_receipt

        result = parse_receipt("sample", ctx.registry, ctx.cfg.output_dir, dry_run=True)
        assert result["status"] == "dry_run"
        assert result["urls"] == sample_receipt["urls"]

    def test_parse_writes_file_and_updates_registry(self, tmp_project, sample_receipt, monkeypatch):
        root, env = tmp_project
        ctx = _ctx_paths(tmp_project, sample_receipt)

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(
            "<div><article><h1>Docs</h1><p>content here</p></article></div>",
            "html.parser",
        )

        def fake_fetch(url, js_render=False, js_settle_ms=None):
            return soup

        monkeypatch.setattr("mcp_agent_docparser.parse.fetch", fake_fetch)
        from mcp_agent_docparser.parse import parse_receipt

        result = parse_receipt("sample", ctx.registry, ctx.cfg.output_dir)
        assert result["status"] == "ok"
        assert result["total_chars"] > 0
        assert "content here" in result["markdown"]
        assert result["sections"][0]["url"] == sample_receipt["urls"][0]

        # File actually written
        out = ctx.cfg.output_dir
        written = list(out.glob("*.md"))
        assert len(written) == 1
        assert written[0].name == result["output_filename"]

        # Registry updated
        got = ctx.registry.get("sample")
        assert got["last_output"] == result["output_filename"]
        assert got["last_fetched"] is not None

    def test_unknown_receipt(self, tmp_project, sample_receipt):
        ctx = _ctx_paths(tmp_project, sample_receipt)
        from mcp_agent_docparser.parse import parse_receipt

        result = parse_receipt("ghost", ctx.registry, ctx.cfg.output_dir)
        assert result["status"] == "not_found"
